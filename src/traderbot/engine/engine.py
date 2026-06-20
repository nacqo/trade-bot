"""Async engine loop.

Per bar: update marks → mark each bot's virtual book → (on the rebalance timer) score books
and run the allocator, recording the decision → act (diff targets vs broker, fill, attribute to
the bot's virtual book).

Capital/aggressiveness *sizing* of orders is applied in the OMS phase; here the allocator's
weights + aggressiveness are computed from per-bot virtual-book PnL and persisted.
"""

from __future__ import annotations

from typing import Iterable

from traderbot.allocator.allocator import Allocator
from traderbot.allocator.scoring import BotScorer
from traderbot.config import Config
from traderbot.execution.broker import Broker
from traderbot.execution.virtual_book import VirtualBook
from traderbot.state.store import StateStore
from traderbot.strategies.base import Strategy
from traderbot.types import Bar, OrderIntent, Quote, TradeTick


class Engine:
    def __init__(
        self,
        config: Config,
        source: object,
        bots: Iterable[Strategy],
        broker: Broker,
        store: StateStore,
    ) -> None:
        self.config = config
        self.source = source
        self.bots = list(bots)
        self.broker = broker
        self.store = store
        self._iter = None

        self.books: dict[str, VirtualBook] = {b.id: VirtualBook(b.id) for b in self.bots}
        self.scorer = BotScorer(
            half_life_hours=config.allocator.ewma_half_life_hours,
            drawdown_penalty=config.allocator.drawdown_penalty,
            min_obs=config.allocator.min_obs,
            eps=config.allocator.eps,
            interval_minutes=config.allocator.rebalance_minutes,
        )
        self.allocator = Allocator(config.allocator)
        self.weights: dict[str, float] = {}
        self.aggressiveness: dict[str, float] = {}
        self._prices: dict[str, float] = {}
        self._prev_equity: dict[str, float] = {b.id: 0.0 for b in self.bots}
        self._last_rebalance_ts = None

    async def step(self):
        if self._iter is None:
            self._iter = self.source.stream().__aiter__()
        try:
            event = await anext(self._iter)
        except StopAsyncIteration:
            return None
        await self._dispatch(event)
        return event

    async def run(self) -> None:
        while await self.step() is not None:
            pass

    async def _dispatch(self, event) -> None:
        if isinstance(event, Bar):
            self._prices[event.symbol] = event.close
            self.broker.set_mark(event.symbol, event.close)
            for book in self.books.values():
                book.mark(self._prices)
            for bot in self.bots:
                bot.on_bar(event)
            await self._maybe_rebalance(event.ts)
            await self._act()
        elif isinstance(event, Quote):
            for bot in self.bots:
                bot.on_quote(event)
        elif isinstance(event, TradeTick):
            for bot in self.bots:
                bot.on_trade(event)

    async def _maybe_rebalance(self, ts) -> None:
        if self._last_rebalance_ts is not None:
            elapsed_min = (ts - self._last_rebalance_ts).total_seconds() / 60.0
            if elapsed_min < self.config.allocator.rebalance_minutes:
                return
        self._last_rebalance_ts = ts

        active = {b.id for b in self.bots if b.enabled}
        for bot_id in active:
            book = self.books[bot_id]
            interval_return = (book.equity - self._prev_equity[bot_id]) / self.config.starting_equity
            self.scorer.update(bot_id, interval_return)
            self._prev_equity[bot_id] = book.equity

        scores = {bid: self.scorer.score(bid) for bid in active}
        result = self.allocator.allocate(scores, active=active, prev_weights=self.weights)
        deployable = self.broker.equity() * self.config.data.deploy_fraction
        for bot_id, res in result.items():
            self.weights[bot_id] = res.weight
            self.aggressiveness[bot_id] = res.aggressiveness
            await self.store.record_allocation(
                ts, bot_id, scores[bot_id], res.weight, res.weight * deployable, res.aggressiveness
            )

    async def _act(self) -> None:
        for bot in self.bots:
            out = bot.evaluate()
            if not out.enabled:
                continue
            for target in out.targets:
                positions = self.broker.positions()
                current = positions.get(target.symbol)
                current_qty = current.qty if current else 0.0
                delta = target.qty - current_qty
                if delta != 0:
                    fill = self.broker.submit(
                        OrderIntent(bot.id, target.symbol, delta, target.stop_price)
                    )
                    await self.store.record_fill(fill)
                    self.books[bot.id].apply_fill(target.symbol, delta, fill.price)
