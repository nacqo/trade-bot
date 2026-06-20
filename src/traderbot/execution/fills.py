"""Volume-aware simulated fills (spec §10).

- **Speed limit:** a fill never exceeds `participation_cap × candle.volume`.
- **Leftovers:** the remainder carries to the next candle and re-runs the same cap check.
- **Re-validation:** before filling a carried *entry* slice, if the bot's signal is no longer
  valid (`still_valid()` is False), cancel the remainder rather than chase. Reductions (exits)
  always continue.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from traderbot.types import Bar


@dataclass(frozen=True)
class CarryOrder:
    bot_id: str
    symbol: str
    remaining: float  # signed
    is_entry: bool


@dataclass(frozen=True)
class FillResult:
    filled_qty: float  # signed
    price: float
    remainder: float  # signed
    cancelled: bool


class SimulatedFillModel:
    def __init__(
        self, participation_cap: float, slippage_bps: float, revalidate_on_carry: bool
    ) -> None:
        self.participation_cap = participation_cap
        self.slippage_bps = slippage_bps
        self.revalidate_on_carry = revalidate_on_carry

    def fill(
        self, order: CarryOrder, candle: Bar, *, still_valid: Callable[[], bool]
    ) -> FillResult:
        if self.revalidate_on_carry and order.is_entry and not still_valid():
            return FillResult(0.0, 0.0, order.remaining, cancelled=True)

        cap_qty = math.floor(self.participation_cap * candle.volume)
        fill_size = min(abs(order.remaining), cap_qty)
        sign = 1.0 if order.remaining > 0 else -1.0
        filled = sign * fill_size
        remainder = order.remaining - filled

        slip = candle.open * self.slippage_bps / 1e4
        price = candle.open + slip * sign  # buyers pay up, sellers receive down
        return FillResult(filled, price, remainder, cancelled=False)
