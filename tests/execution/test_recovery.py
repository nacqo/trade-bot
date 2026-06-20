from datetime import datetime, timezone

from traderbot.execution.recovery import rebuild_books, reconcile
from traderbot.execution.virtual_book import VirtualBook
from traderbot.state.store import StateStore
from traderbot.types import Fill, Position

TS = datetime(2026, 6, 20, 14, 0, tzinfo=timezone.utc)


async def test_rebuild_books_from_persisted_fills(tmp_path):
    store = StateStore(str(tmp_path / "s.db"))
    await store.init()
    await store.record_fill(Fill("A", "AAPL", 10, 100.0, TS))
    await store.record_fill(Fill("A", "AAPL", -4, 110.0, TS))
    await store.record_fill(Fill("B", "MSFT", -5, 200.0, TS))

    books = await rebuild_books(store)
    assert books["A"].positions["AAPL"].qty == 6
    assert books["B"].positions["MSFT"].qty == -5
    await store.close()


def test_reconcile_detects_and_clears_drift():
    book = VirtualBook("A")
    book.apply_fill("AAPL", 6, 100.0)
    books = {"A": book}

    drifted = reconcile(books, {"AAPL": Position("AAPL", 5, 100.0)})
    assert len(drifted) == 1
    assert drifted[0]["symbol"] == "AAPL"
    assert drifted[0]["drift"] == 1.0  # virtual 6 − real 5

    assert reconcile(books, {"AAPL": Position("AAPL", 6, 100.0)}) == []
