"""Strategy interface. Bots consume market data and emit target positions + a signal.

Bots never touch the broker; the engine applies allocation (capital + aggressiveness) and
the OMS/risk layers handle execution. Every TargetPosition MUST carry a stop_price (risk
rejects stop-less orders).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from traderbot.types import Bar, Quote, TradeTick


@dataclass(frozen=True)
class TargetPosition:
    symbol: str
    qty: float  # signed target: + long, − short, 0 flat
    stop_price: float | None  # required for any non-flat target


@dataclass(frozen=True)
class ExitPlan:
    """TP-ladder + breakeven rule (bot 5 / Phase F). Unused in v1."""

    take_profits: list[float] = field(default_factory=list)
    move_stop_to_be_on_first_tp: bool = True


@dataclass(frozen=True)
class BotOutput:
    targets: list[TargetPosition]
    signal_strength: float  # 0..1 normalized confidence
    enabled: bool = True


class Strategy(ABC):
    def __init__(self, id: str, symbols: list[str] | None = None) -> None:
        self.id = id
        self.symbols = symbols or []
        self.enabled = True

    def on_bar(self, bar: Bar) -> None:  # noqa: D401
        """Update internal state from a closed bar. Default: no-op."""

    def on_quote(self, quote: Quote) -> None:
        """Update internal state from a top-of-book quote. Default: no-op."""

    def on_trade(self, tick: TradeTick) -> None:
        """Update internal state from a trade tick. Default: no-op."""

    @abstractmethod
    def evaluate(self) -> BotOutput:
        """Return current target positions + signal strength."""
