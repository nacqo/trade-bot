from datetime import datetime, timedelta, timezone

from traderbot.config import Config
from traderbot.engine.engine import Engine
from traderbot.execution.broker import FakeBroker
from traderbot.state.store import StateStore
from traderbot.strategies.fixed_target import FixedTargetBot
from traderbot.types import Bar

from tests.helpers import ListSource

T0 = datetime(2026, 6, 20, 13, 30, tzinfo=timezone.utc)


def _events():
    events = []
    for m in range(14):
        ts = T0 + timedelta(minutes=m)
        events.append(Bar("AAA", ts, 100 + m, 100 + m, 100 + m, 100 + m, 5000))  # winner: rising
        events.append(Bar("BBB", ts, 100 - m, 100 - m, 100 - m, 100 - m, 5000))  # loser: falling
    return events


async def test_allocator_favours_the_winner(tmp_path):
    cfg = Config.default()
    cfg.allocator.min_obs = 5
    cfg.allocator.rebalance_minutes = 1
    cfg.allocator.cap = 0.9  # let two bots differ (default 0.5 would force 50/50)

    store = StateStore(str(tmp_path / "s.db"))
    await store.init()
    bots = [FixedTargetBot("A", "AAA", 1), FixedTargetBot("B", "BBB", 1)]
    broker = FakeBroker(100_000.0)
    engine = Engine(cfg, ListSource(_events()), bots, broker, store)

    await engine.run()

    assert engine.weights["A"] > engine.weights["B"]
    assert await store.count("allocations") > 0
    await store.close()
