from datetime import datetime, timedelta, timezone

from traderbot.core import CORE_EQUITIES, CORE_ETFS, build_core_bots, core_rebalance
from traderbot.execution.broker import FakeBroker
from traderbot.types import Bar

T0 = datetime(2026, 1, 2, tzinfo=timezone.utc)


def test_build_core_bots_is_three_daily_factors():
    bots = build_core_bots()
    assert [b.id for b in bots] == ["momentum", "residmom", "trend"]


async def test_core_rebalance_builds_target_within_leverage():
    syms = CORE_EQUITIES + CORE_ETFS
    broker = FakeBroker(100_000.0)
    history = []
    for t in range(260):
        for i, s in enumerate(syms):
            price = 500 + (i % 7 - 3) * 0.3 * t   # varied trends, stays positive
            broker.set_mark(s, price)
            history.append(Bar(s, T0 + timedelta(days=t), price, price, price, price, 100_000))
    history.sort(key=lambda b: b.ts)

    submitted = await core_rebalance(broker, history, broker.equity())
    assert len(submitted) > 0                              # builds a target portfolio
    assert broker.gross() <= 1.5 * broker.equity() + 1.0   # within the leverage cap
