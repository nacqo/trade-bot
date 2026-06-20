"""Broker boundary. `Broker` is the interface; `FakeBroker` is an in-memory test/sim double.

At this boundary `OrderIntent.target_qty` is the **signed order qty to execute** (a delta the
engine/OMS computed), not an absolute target.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from traderbot.types import Fill, OrderIntent, Position


class Broker(Protocol):
    def submit(self, intent: OrderIntent) -> Fill: ...
    def positions(self) -> dict[str, Position]: ...
    def equity(self) -> float: ...
    def buying_power(self) -> float: ...


class FakeBroker:
    def __init__(self, start_equity: float, max_leverage: float = 1.5) -> None:
        self._cash = start_equity
        self._start_equity = start_equity
        self._max_leverage = max_leverage
        self._positions: dict[str, Position] = {}
        self._marks: dict[str, float] = {}

    def set_mark(self, symbol: str, price: float) -> None:
        self._marks[symbol] = price

    def _mark(self, symbol: str) -> float:
        if symbol in self._marks:
            return self._marks[symbol]
        pos = self._positions.get(symbol)
        return pos.avg_price if pos else 0.0

    def submit(self, intent: OrderIntent) -> Fill:
        qty = intent.target_qty
        price = self._mark(intent.symbol)
        pos = self._positions.get(intent.symbol)
        prev_qty = pos.qty if pos else 0.0
        new_qty = prev_qty + qty
        if new_qty == 0:
            self._positions.pop(intent.symbol, None)
        elif pos and (prev_qty > 0) == (qty > 0):
            # adding in same direction → weighted avg price
            avg = (pos.avg_price * prev_qty + price * qty) / new_qty
            self._positions[intent.symbol] = Position(intent.symbol, new_qty, avg)
        else:
            # opening, or reducing/flipping → use trade price for the residual
            avg = pos.avg_price if (pos and (prev_qty > 0) == (new_qty > 0)) else price
            self._positions[intent.symbol] = Position(intent.symbol, new_qty, avg)
        self._cash -= qty * price
        return Fill(intent.bot_id, intent.symbol, qty, price, datetime.now(timezone.utc))

    def positions(self) -> dict[str, Position]:
        return dict(self._positions)

    def gross(self) -> float:
        return sum(abs(p.market_value(self._mark(s))) for s, p in self._positions.items())

    def equity(self) -> float:
        return self._cash + sum(p.market_value(self._mark(s)) for s, p in self._positions.items())

    def buying_power(self) -> float:
        return max(0.0, self.equity() * self._max_leverage - self.gross())
