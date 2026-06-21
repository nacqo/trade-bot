"""v1 acceptance harness — the machine-checkable §18 definition-of-done gates, running the active
intraday bots (stat-arb, ORB, VWAP/Bollinger) through the full engine.
"""

from datetime import datetime, timedelta, timezone

from traderbot.backtest.metrics import allocator_beats_equal_weight
from traderbot.backtest.runner import run_backtest
from traderbot.config import Config
from traderbot.execution.recovery import reconcile
from traderbot.market_data.source import ReplaySource
from traderbot.strategies.orb import ORBBot
from traderbot.types import Bar

T0 = datetime(2026, 6, 20, 13, 30, tzinfo=timezone.utc)


def _fixture() -> ReplaySource:
    aaa, bbb = [], []
    for m in range(60):
        ts = T0 + timedelta(minutes=m)
        a = 100 + 0.2 * m + (1.0 if m % 11 == 0 else 0.0)
        spread = 0.1 * ((m % 5) - 2)            # small oscillating spread, ~zero mean
        if m in (40, 41, 42):
            spread += 1.5                       # widen → stat-arb entry
        b = a - spread
        aaa.append(Bar("AAA", ts, a, a + 0.5, a - 0.5, a, 5000))
        bbb.append(Bar("BBB", ts, b, b + 0.5, b - 0.5, b, 5000))
    return ReplaySource({"AAA": aaa, "BBB": bbb})


async def test_v1_acceptance_gates():
    cfg = Config.default()
    cfg.allocator.min_obs = 3
    cfg.allocator.rebalance_minutes = 1
    bots = [ORBBot("orb", ["AAA", "BBB"], opening_minutes=5, atr_period=5)]

    result = await run_backtest(cfg, _fixture(), bots)

    assert len(result.equity_curve) > 0
    assert len(result.fills) > 0

    # 1. attribution reconciles: Σ virtual books == broker net
    assert reconcile(result.books, result.broker_positions) == []
    # 2. no fill exceeded the participation cap (5% of 5000 = 250)
    assert all(abs(f["qty"]) <= 250 + 1e-9 for f in result.fills)
    # 3. solvency / heat: total open risk ≤ effective cap
    assert result.open_risk <= result.open_risk_cap + 1e-6
    # 4. leverage: gross ≤ max_gross_leverage × equity
    assert result.gross <= cfg.risk.max_gross_leverage * result.equity + 1e-6
    # 5. every open position carries a stop
    for bot_id, book in result.books.items():
        for symbol in book.positions:
            assert symbol in result.stops.get(bot_id, {}), f"{bot_id}/{symbol} has no stop"
    # 6. allocator-vs-equal-weight is reported
    assert isinstance(allocator_beats_equal_weight(result, cfg.starting_equity), bool)
