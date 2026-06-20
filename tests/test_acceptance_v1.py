"""v1 acceptance harness — the machine-checkable §18 definition-of-done gates, with all four
active bots plus the dormant futures bot running through the full engine.
"""

from datetime import datetime, timedelta, timezone

from traderbot.backtest.metrics import allocator_beats_equal_weight
from traderbot.backtest.runner import run_backtest
from traderbot.config import Config
from traderbot.execution.recovery import reconcile
from traderbot.market_data.source import ReplaySource
from traderbot.strategies.dormant import DormantBot
from traderbot.strategies.order_flow import OrderFlowBot
from traderbot.strategies.orb import ORBBot
from traderbot.strategies.stat_arb import StatArbBot
from traderbot.strategies.vwap_reversion import VWAPReversionBot
from traderbot.types import Bar, Quote

T0 = datetime(2026, 6, 20, 13, 30, tzinfo=timezone.utc)


def _fixture() -> ReplaySource:
    aaa, bbb, quotes = [], [], []
    for m in range(60):
        ts = T0 + timedelta(minutes=m)
        a = 100 + 0.2 * m + (1.0 if m % 11 == 0 else 0.0)
        spread = 0.1 * ((m % 5) - 2)            # small oscillating spread, ~zero mean
        if m in (40, 41, 42):
            spread += 1.5                       # widen → stat-arb entry
        b = a - spread
        aaa.append(Bar("AAA", ts, a, a + 0.5, a - 0.5, a, 5000))
        bbb.append(Bar("BBB", ts, b, b + 0.5, b - 0.5, b, 5000))
        if m % 10 == 0:
            quotes.append(Quote("AAA", ts - timedelta(seconds=30), a - 0.01, a + 0.01, 900, 100))
    return ReplaySource({"AAA": aaa, "BBB": bbb}, quotes=quotes)


async def test_v1_acceptance_gates():
    cfg = Config.default()
    cfg.allocator.min_obs = 3
    cfg.allocator.rebalance_minutes = 1
    bots = [
        StatArbBot("statarb", [("AAA", "BBB")], z_in=1.5, z_stop=6.0, lookback=20),
        ORBBot("orb", ["AAA", "BBB"], opening_minutes=5, atr_period=5),
        VWAPReversionBot("vwap", ["AAA", "BBB"], bb_period=10),
        OrderFlowBot("flow", ["AAA"], imb_threshold=0.3),
        DormantBot("general", "MES/MNQ futures (Phase F)"),
    ]

    result = await run_backtest(cfg, _fixture(), bots)

    # ran and traded
    assert len(result.equity_curve) > 0
    assert len(result.fills) > 0

    # 1. attribution reconciles: Σ virtual books == broker net
    assert reconcile(result.books, result.broker_positions) == []

    # 2. no fill exceeded the participation cap (5% of 5000 = 250)
    assert all(abs(f["qty"]) <= 250 + 1e-9 for f in result.fills)

    # 3. solvency / heat: total open risk ≤ effective cap (≤ equity − maintenance buffer)
    assert result.open_risk <= result.open_risk_cap + 1e-6

    # 4. leverage: gross ≤ max_gross_leverage × equity
    assert result.gross <= cfg.risk.max_gross_leverage * result.equity + 1e-6

    # 5. every open position carries a stop
    for bot_id, book in result.books.items():
        for symbol in book.positions:
            assert symbol in result.stops.get(bot_id, {}), f"{bot_id}/{symbol} has no stop"

    # 6. allocator-vs-equal-weight is reported (the null hypothesis is evaluated)
    assert isinstance(allocator_beats_equal_weight(result, cfg.starting_equity), bool)

    # 7. dormant bot 5 takes zero allocation and never trades
    final_weights = result.weights_history[-1]
    assert "general" not in final_weights
    assert all(e == 0.0 for e in result.per_bot_equity["general"])
