"""Async engine loop. P0: data → bots → (diff vs broker) → submit → record fills.

Later phases insert the allocator (scaling targets by capital_weight × aggressiveness),
risk checks, and the participation-cap OMS between `evaluate()` and `submit()`.
"""

from __future__ import annotations

from typing import Iterable

from traderbot.config import Config
from traderbot.execution.broker import Broker
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
            self.broker.set_mark(event.symbol, event.close)
            for bot in self.bots:
                bot.on_bar(event)
            await self._act()
        elif isinstance(event, Quote):
            for bot in self.bots:
                bot.on_quote(event)
        elif isinstance(event, TradeTick):
            for bot in self.bots:
                bot.on_trade(event)

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
