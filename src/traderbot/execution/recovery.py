"""Exact crash recovery + reconciliation.

Per-bot virtual books are rebuilt by replaying persisted fills (not best-effort). Any drift
between the summed virtual books and the broker's real net position is reported as an explicit
adjustment to be logged.
"""

from __future__ import annotations

from traderbot.execution.virtual_book import VirtualBook
from traderbot.types import Position


async def rebuild_books(store) -> dict[str, VirtualBook]:
    books: dict[str, VirtualBook] = {}
    for row in await store.load_fills():
        book = books.setdefault(row["bot_id"], VirtualBook(row["bot_id"]))
        book.apply_fill(row["symbol"], row["qty"], row["price"])
    return books


def reconcile(
    books: dict[str, VirtualBook],
    broker_positions: dict[str, Position],
    tol: float = 1e-6,
) -> list[dict]:
    virtual: dict[str, float] = {}
    for book in books.values():
        for symbol, pos in book.positions.items():
            virtual[symbol] = virtual.get(symbol, 0.0) + pos.qty

    symbols = set(virtual) | set(broker_positions)
    adjustments: list[dict] = []
    for symbol in symbols:
        v = virtual.get(symbol, 0.0)
        r = broker_positions[symbol].qty if symbol in broker_positions else 0.0
        drift = v - r
        if abs(drift) > tol:
            adjustments.append({"symbol": symbol, "virtual": v, "real": r, "drift": drift})
    return adjustments
