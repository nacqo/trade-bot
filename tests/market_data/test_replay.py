from datetime import datetime, timedelta, timezone

from traderbot.market_data.source import ReplaySource
from traderbot.types import Bar

T0 = datetime(2026, 6, 20, 13, 30, tzinfo=timezone.utc)


def _bar(symbol, m):
    return Bar(symbol, T0 + timedelta(minutes=m), 100, 100, 100, 100, 1000)


async def test_replay_interleaves_by_timestamp():
    bars = {"AAA": [_bar("AAA", 0), _bar("AAA", 2)], "BBB": [_bar("BBB", 1)]}
    src = ReplaySource(bars)
    out = [e async for e in src.stream()]
    assert [e.symbol for e in out] == ["AAA", "BBB", "AAA"]
    assert [e.ts for e in out] == sorted(e.ts for e in out)
