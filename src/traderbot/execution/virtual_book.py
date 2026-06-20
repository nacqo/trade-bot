"""Per-bot virtual book. The broker holds only the *net* account, so each bot keeps its own
intended positions, marked to market, giving clean per-bot PnL for the allocator to score.
"""

from __future__ import annotations

from traderbot.types import Position


class VirtualBook:
    def __init__(self, bot_id: str) -> None:
        self.bot_id = bot_id
        self._pos: dict[str, tuple[float, float]] = {}  # symbol -> (qty, avg_price)
        self._marks: dict[str, float] = {}
        self.realized = 0.0

    def apply_fill(self, symbol: str, qty: float, price: float) -> None:
        cur_qty, cur_avg = self._pos.get(symbol, (0.0, 0.0))
        new_qty = cur_qty + qty

        if cur_qty == 0:
            self._pos[symbol] = (qty, price)
            return

        same_direction = (cur_qty > 0) == (qty > 0)
        if same_direction:
            avg = (cur_avg * cur_qty + price * qty) / new_qty
            self._pos[symbol] = (new_qty, avg)
            return

        # reducing or flipping: realize PnL on the closed amount
        close_amount = min(abs(qty), abs(cur_qty))
        direction = 1.0 if cur_qty > 0 else -1.0
        self.realized += direction * (price - cur_avg) * close_amount

        if abs(qty) < abs(cur_qty):
            self._pos[symbol] = (new_qty, cur_avg)  # partial close, avg unchanged
        elif abs(qty) == abs(cur_qty):
            self._pos.pop(symbol, None)
        else:
            self._pos[symbol] = (new_qty, price)  # flip: remainder opens at trade price

    def mark(self, prices: dict[str, float]) -> None:
        self._marks.update(prices)

    @property
    def unrealized(self) -> float:
        total = 0.0
        for symbol, (qty, avg) in self._pos.items():
            mark = self._marks.get(symbol, avg)
            total += qty * (mark - avg)
        return total

    @property
    def equity(self) -> float:
        return self.realized + self.unrealized

    @property
    def positions(self) -> dict[str, Position]:
        return {s: Position(s, q, a) for s, (q, a) in self._pos.items()}
