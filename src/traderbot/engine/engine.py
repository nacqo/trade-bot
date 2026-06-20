"""Async engine loop.

Per bar: update marks → mark each bot's virtual book → (rebalance timer) score + allocate →
act. Two execution paths:
- direct (no OMS): submit target deltas straight to the broker (used by P0/P1 smoke tests).
- OMS path: admit targets through risk (mandatory stop + portfolio-heat cap), scale by the
  allocator's weight × aggressiveness, then route through the participation-capped OMS.
"""

from __future__ import annotations

from typing import Iterable

from traderbot.allocator.allocator import Allocator, sleeve_scale
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
        self._now = None
        self._suspended: set[str] = set()
        self._peak_equity = config.starting_equity
        self._bot_peak: dict[str, float] = {}
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
            self._now = event.ts
            self._prices[event.symbol] = event.close
            self.broker.set_mark(event.symbol, event.close)
            for book in self.books.values():
                book.mark(self._prices)
            for bot in self.bots:
                bot.on_bar(event)
            await self._maybe_rebalance(event.ts)
            if self.risk is not None:
                await self._risk_checks()
            if not (self.risk is not None and self.risk.halted):
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

    async def _risk_checks(self) -> None:
        """Portfolio drawdown → halt + flatten everything; per-bot drawdown → flatten + suspend."""
        equity = self.broker.equity()
        self._peak_equity = max(self._peak_equity, equity)
        if self._peak_equity > 0:
            dd = (self._peak_equity - equity) / self._peak_equity
            if dd >= self.config.risk.total_dd_halt:
                self.risk.halt()
                await self._flatten_all()
                await self.store.record_risk_event(self._now, "halt", f"portfolio drawdown {dd:.4f}")
                return
        budget = self.config.risk.per_bot_dd_kill * self.config.starting_equity
        for bot in self.bots:
            if not bot.enabled or bot.id in self._suspended:
                continue
            eq = self.books[bot.id].equity
            self._bot_peak[bot.id] = max(self._bot_peak.get(bot.id, eq), eq)
            if self._bot_peak[bot.id] - eq >= budget:
                await self._flatten_bot(bot.id)
                await self.store.record_risk_event(self._now, "bot_suspend", bot.id)

    async def _flatten_all(self) -> None:
        for symbol, pos in list(self.broker.positions().items()):
            if pos.qty != 0:
                fill = self.broker.submit(OrderIntent("halt", symbol, -pos.qty, None))
                await self.store.record_fill(fill)
        for book in self.books.values():
            for symbol, pos in list(book.positions.items()):
                book.apply_fill(symbol, -pos.qty, self._prices.get(symbol, pos.avg_price))
        self._stops.clear()

    async def _flatten_bot(self, bot_id: str) -> None:
        book = self.books[bot_id]
        for symbol, pos in list(book.positions.items()):
            if pos.qty != 0:
                fill = self.broker.submit(OrderIntent(bot_id, symbol, -pos.qty, None))
                await self.store.record_fill(fill)
                book.apply_fill(symbol, -pos.qty, fill.price)
        self._suspended.add(bot_id)
        self._stops.pop(bot_id, None)

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
            if bot.id in self._suspended:
                continue
            out = bot.evaluate()
            if not out.enabled:
                continue
            weight = self.weights.get(bot.id, 1.0 / n)
            aggr = self.aggressiveness.get(bot.id, 1.0)
            deployable = equity * self.config.data.deploy_fraction
            desired_gross = sum(
                abs(t.qty * self._prices.get(t.symbol, price))
                for t in out.targets
                if t.qty != 0 and t.stop_price is not None
            )
            scale = sleeve_scale(weight, aggr, deployable, desired_gross)
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
                scaled = t.qty * scale
                new_risk = abs(scaled) * abs(price - t.stop_price)
                without = self.current_open_risk() - self._contrib(bot.id, t.symbol)
                if without + new_risk <= cap + 1e-9:
                    kept.append(TargetPosition(t.symbol, scaled, t.stop_price))
                    stops[t.symbol] = t.stop_price
            if kept:
                bot_targets[bot.id] = kept
        # Re-validation: a carried entry is only still valid if the bots still want this symbol.
        net_desired = sum(t.qty for ts in bot_targets.values() for t in ts if t.symbol == bar.symbol)
        still_valid = {bar.symbol: (lambda nd=net_desired: nd != 0)}
        if bot_targets or bar.symbol in self.oms.pending:
            fills = await self.oms.execute(
                bot_targets, bar, equity, self.books, still_valid=still_valid
            )
            for fill in fills:
                await self.store.record_fill(fill)

    async def _act_direct(self) -> None:
        for bot in self.bots:
            if bot.id in self._suspended:
                continue
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
