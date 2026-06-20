"""Trivial bot used to seed/smoke-test the engine: always targets a fixed position."""

from __future__ import annotations

from traderbot.strategies.base import BotOutput, Strategy, TargetPosition


class FixedTargetBot(Strategy):
    def __init__(self, id: str, symbol: str, qty: float, stop_price: float | None = None) -> None:
        super().__init__(id, symbols=[symbol])
        self.symbol = symbol
        self.qty = qty
        self.stop_price = stop_price

    def evaluate(self) -> BotOutput:
        return BotOutput(
            targets=[TargetPosition(self.symbol, self.qty, self.stop_price)],
            signal_strength=1.0,
        )
