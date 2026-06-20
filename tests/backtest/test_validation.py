from datetime import datetime, timedelta, timezone

from traderbot.backtest.runner import run_backtest
from traderbot.backtest.validation import oos_report
from traderbot.config import Config
from traderbot.market_data.source import ReplaySource
from traderbot.strategies.orb import ORBBot
from traderbot.strategies.vwap_reversion import VWAPReversionBot
from traderbot.types import Bar

T0 = datetime(2026, 6, 20, 13, 30, tzinfo=timezone.utc)


def _bars(symbol, base, slope):
    return [
        Bar(symbol, T0 + timedelta(minutes=m), base + slope * m, base + slope * m + 0.5,
            base + slope * m - 0.5, base + slope * m, 5000)
        for m in range(40)
    ]


async def test_oos_report_compares_allocator_to_equal_weight():
    cfg = Config.default()
    cfg.allocator.min_obs = 2
    cfg.allocator.rebalance_minutes = 1
    bots = [
        ORBBot("orb", ["AAA", "BBB"], opening_minutes=3, atr_period=3),
        VWAPReversionBot("vwap", ["AAA", "BBB"], bb_period=5),
    ]
    source = ReplaySource({"AAA": _bars("AAA", 100, 0.3), "BBB": _bars("BBB", 100, -0.2)})
    result = await run_backtest(cfg, source, bots)

    rep = oos_report(result, cfg.starting_equity, train_frac=0.5, windows=3)
    assert isinstance(rep["allocator_beats_equal_weight_oos"], bool)
    assert rep["windows_total"] >= 1
    assert 0 <= rep["windows_allocator_won"] <= rep["windows_total"]
    assert "oos_sharpe_allocator" in rep and "oos_sharpe_equal_weight" in rep
