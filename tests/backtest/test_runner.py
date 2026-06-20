import math
from datetime import datetime, timedelta, timezone

from traderbot.backtest.runner import run_backtest
from traderbot.config import Config
from traderbot.execution.recovery import reconcile
from traderbot.market_data.source import ReplaySource
from traderbot.strategies.fixed_target import FixedTargetBot
from traderbot.types import Bar

T0 = datetime(2026, 6, 20, 13, 30, tzinfo=timezone.utc)


def _bars(symbol, base):
    return [
        Bar(symbol, T0 + timedelta(minutes=m), base + m, base + m, base + m, base + m, 5000)
        for m in range(8)
    ]


async def test_backtest_runs_reconciles_and_respects_cap():
    cfg = Config.default()
    cfg.allocator.min_obs = 2
    cfg.allocator.rebalance_minutes = 1
    bots = [
        FixedTargetBot("A", "AAA", qty=10, stop_price=95.0),
        FixedTargetBot("B", "BBB", qty=10, stop_price=95.0),
    ]
    source = ReplaySource({"AAA": _bars("AAA", 100), "BBB": _bars("BBB", 100)})

    result = await run_backtest(cfg, source, bots)

    assert len(result.equity_curve) > 0
    # attribution reconciles: summed virtual books == broker net
    assert reconcile(result.books, result.broker_positions) == []
    # no fill exceeded the participation cap (5% of 5000 = 250)
    assert all(abs(f["qty"]) <= math.floor(0.05 * 5000) + 1e-9 for f in result.fills)
    # both bots got allocation weights recorded over time
    assert result.weights_history[-1]  # non-empty final weights
