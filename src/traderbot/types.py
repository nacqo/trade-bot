"""Core domain types shared across every layer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Side(Enum):
    BUY = "buy"
    SELL = "sell"

    @staticmethod
    def from_qty(qty: float) -> "Side":
        return Side.BUY if qty >= 0 else Side.SELL


@dataclass(frozen=True)
class Bar:
    symbol: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Quote:
    symbol: str
    ts: datetime
    bid: float
    ask: float
    bid_size: float
    ask_size: float


@dataclass(frozen=True)
class TradeTick:
    symbol: str
    ts: datetime
    price: float
    size: float


@dataclass(frozen=True)
class Position:
    symbol: str
    qty: float
    avg_price: float

    @property
    def is_short(self) -> bool:
        return self.qty < 0

    @property
    def is_long(self) -> bool:
        return self.qty > 0

    def market_value(self, price: float) -> float:
        return self.qty * price


@dataclass(frozen=True)
class OrderIntent:
    bot_id: str
    symbol: str
    target_qty: float  # signed: + long, − short
    stop_price: float | None
    exit_plan: object | None = None  # TP-ladder/exit plan (bot 5 / Phase F); None in v1


@dataclass(frozen=True)
class Fill:
    bot_id: str
    symbol: str
    qty: float  # signed
    price: float
    ts: datetime
