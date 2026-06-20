"""Net each bot's desired position-deltas into one order per symbol, and attribute fills back.

A bot's delta = (its target) − (its own virtual-book position). Because Σ virtual books = the
real net account, Σ deltas = the real net order. A partial fill is attributed back to each bot by
the same fill ratio, so attribution always sums exactly to what was filled.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NetOrder:
    symbol: str
    qty: float  # net order = Σ contributor deltas
    contributors: dict[str, float]  # bot_id -> that bot's delta

    def attribute(self, filled_qty: float) -> dict[str, float]:
        if self.qty == 0:
            return {bot: 0.0 for bot in self.contributors}
        ratio = filled_qty / self.qty
        return {bot: delta * ratio for bot, delta in self.contributors.items()}


def net_targets(bot_deltas: dict[str, dict[str, float]]) -> dict[str, NetOrder]:
    acc: dict[str, dict] = {}
    for bot, deltas in bot_deltas.items():
        for symbol, delta in deltas.items():
            entry = acc.setdefault(symbol, {"qty": 0.0, "contrib": {}})
            entry["qty"] += delta
            entry["contrib"][bot] = entry["contrib"].get(bot, 0.0) + delta
    return {sym: NetOrder(sym, v["qty"], dict(v["contrib"])) for sym, v in acc.items()}
