from datetime import datetime, timezone

from traderbot.state.store import StateStore
from traderbot.types import Fill


def _ts():
    return datetime(2026, 6, 20, 14, 0, tzinfo=timezone.utc)


async def test_record_and_load_fill(tmp_path):
    store = StateStore(str(tmp_path / "s.db"))
    await store.init()
    await store.record_fill(Fill("b1", "AAPL", 5, 100.0, _ts()))
    rows = await store.load_fills()
    assert len(rows) == 1
    assert rows[0]["bot_id"] == "b1"
    assert rows[0]["qty"] == 5
    assert rows[0]["price"] == 100.0
    await store.close()


async def test_allocation_equity_risk_roundtrip(tmp_path):
    store = StateStore(str(tmp_path / "s.db"))
    await store.init()
    await store.record_allocation(_ts(), "b1", score=0.5, weight=0.4, capital=40000.0, aggr=1.2)
    await store.record_bot_equity(_ts(), "b1", realized=10.0, unrealized=5.0, equity=100015.0)
    await store.record_risk_event(_ts(), "halt", "test trip")
    assert await store.count("allocations") == 1
    assert await store.count("bot_equity") == 1
    assert await store.count("risk_events") == 1
    await store.close()
