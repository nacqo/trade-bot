"""Async engine loop.

Per bar: update marks → mark each bot's virtual book → (rebalance timer) score + allocate →
act. Two execution paths:
- direct (no OMS): submit target deltas straight to the broker (used by P0/P1 smoke tests).
- OMS path: admit targets through risk (mandatory stop + portfolio-heat cap), scale by the
  allocator's weight × aggressiveness, then route through the participation-capped OMS.
"""

from __future__ import annotations

from typing import Iterable

from traderbot.allocator.allocator import Allocator
from traderbot.allocator.scoring import BotScorer
from traderbot.config import Config
from traderbot.execution.broker import Broker
from traderbot.execution.virtual_book import VirtualBook
from traderbot.state.store import StateStore
from traderbot.strategies.base import Strategy, TargetPosition
from traderbot.types import Bar, OrderIntent, Quote, TradeTick


class Engine:
    def __init__(
        self,
        config: Config,
        source: object,
        bots: Iterable[Strategy],
        broker: Broker,
        store: StateStore,
        risk_manager=None,
        oms=None,
    ) -> None:
        self.config = config
        self.source = source
        self.bots = list(bots)
        self.broker = broker
        self.store = store
        self.risk = risk_manager
        self.oms = oms
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
        self._stops: dict[str, dict[str, float]] = {}
        self._prev_equity: dict[str, float] = {b.id: 0.0 for b in self.bots}
        self._last_rebalance_ts = None
        self.equity_curve: list[float] = []
        self.per_bot_equity: dict[str, list[float]] = {b.id: [] for b in self.bots}
        self.weights_history: list[dict[str, float]] = []

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
            if self.oms is not None:
                await self._act_via_oms(event)
            else:
                await self._act_direct()
            self.equity_curve.append(self.broker.equity())
            for bot_id, book in self.books.items():
                self.per_bot_equity[bot_id].append(book.equity)
            self.weights_history.append(dict(self.weights))
        elif isinstance(event, Quote):
            for bot in self.bots:
                bot.on_quote(event)
        elif isinstance(event, TradeTick):
            for bot in self.bots:
                bot.on_trade(event)

    async def _maybe_rebalance(self, ts) -> None:
        if self._last_rebalance_ts is not None:
            elapsed = (ts - self._last_rebalance_ts).total_seconds() / 60.0
            if elapsed < self.config.allocator.rebalance_minutes:
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

    def current_open_risk(self) -> float:
        total = 0.0
        for bot_id, book in self.books.items():
            stops = self._stops.get(bot_id, {})
            for symbol, pos in book.positions.items():
                stop = stops.get(symbol)
                if stop is not None:
                    total += abs(pos.qty) * abs(pos.avg_price - stop)
        return total

    def _contrib(self, bot_id: str, symbol: str) -> float:
        stop = self._stops.get(bot_id, {}).get(symbol)
        pos = self.books[bot_id].positions.get(symbol)
        if stop is None or pos is None:
            return 0.0
        return abs(pos.qty) * abs(pos.avg_price - stop)

    async def _act_via_oms(self, bar: Bar) -> None:
        active = [b for b in self.bots if b.enabled]
        n = len(active) or 1
        equity = self.broker.equity()
        cap = self.risk.effective_open_risk_cap(equity) if self.risk else float("inf")
        price = bar.close
        bot_targets: dict[str, list[TargetPosition]] = {}
        for bot in active:
            out = bot.evaluate()
            if not out.enabled:
                continue
            factor = self.weights.get(bot.id, 1.0 / n) * n * self.aggressiveness.get(bot.id, 1.0)
            stops = self._stops.setdefault(bot.id, {})
            kept: list[TargetPosition] = []
            for t in out.targets:
                if t.symbol != bar.symbol:
                    continue
                if t.qty == 0:
                    kept.append(t)
                    stops.pop(t.symbol, None)
                    continue
                if t.stop_price is None:
                    continue  # risk: no stop → reject
                scaled = t.qty * factor
                new_risk = abs(scaled) * abs(price - t.stop_price)
                without = self.current_open_risk() - self._contrib(bot.id, t.symbol)
                if without + new_risk <= cap + 1e-9:
                    kept.append(TargetPosition(t.symbol, scaled, t.stop_price))
                    stops[t.symbol] = t.stop_price
            if kept:
                bot_targets[bot.id] = kept
        if bot_targets:
            fills = await self.oms.execute(bot_targets, bar, equity, self.books)
            for fill in fills:
                await self.store.record_fill(fill)

    async def _act_direct(self) -> None:
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
