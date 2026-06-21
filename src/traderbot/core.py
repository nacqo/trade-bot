"""Blended live core — residmom + trend + momentum through ONE allocator, one daily rebalance.

`core_rebalance` computes the target portfolio by running the blended engine over recent history
with a fresh FakeBroker seeded at the real account equity (the FakeBroker's ending book = the
allocator-weighted, risk-managed target), then diffs against the real broker's positions and
submits only the deltas. Run once per trading day (cron after the close).
"""

from __future__ import annotations

from traderbot.backtest.runner import run_backtest
from traderbot.config import Config
from traderbot.market_data.source import ReplaySource
from traderbot.strategies.momentum import CrossSectionalMomentumBot
from traderbot.strategies.residual_momentum import ResidualMomentumBot
from traderbot.strategies.trend import TimeSeriesMomentumBot
from traderbot.types import Bar, OrderIntent

CORE_EQUITIES = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "BAC", "WFC",
                 "XOM", "CVX", "COP", "KO", "PEP", "PG", "WMT", "HD", "MCD", "DIS",
                 "NKE", "V", "MA", "UNH", "JNJ", "PFE", "MRK", "CSCO", "INTC", "AMD",
                 "QCOM", "CRM", "ORCL", "IBM", "T", "VZ", "CMCSA", "COST", "TGT", "LOW",
                 "CAT", "BA", "GE", "HON"]
CORE_ETFS = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "LQD", "HYG", "GLD",
             "SLV", "DBC", "USO", "VNQ", "UUP", "XLE", "XLK", "XLF"]


def build_core_bots():
    return [
        CrossSectionalMomentumBot("momentum", CORE_EQUITIES),
        ResidualMomentumBot("residmom", CORE_EQUITIES),
        TimeSeriesMomentumBot("trend", CORE_ETFS),
    ]


async def core_rebalance(
    real_broker, history: list[Bar], equity: float,
    deploy_fraction: float = 1.0, max_gross_leverage: float = 1.5,
) -> list[tuple]:
    cfg = Config.default()
    cfg.starting_equity = equity
    cfg.allocator.min_obs = 20
    cfg.data.deploy_fraction = deploy_fraction        # < 1.0 holds a cash buffer (live: conservative)
    cfg.risk.max_gross_leverage = max_gross_leverage
    result = await run_backtest(cfg, ReplaySource({_grp: [b for b in history if b.symbol == _grp]
                                                   for _grp in {b.symbol for b in history}}),
                                build_core_bots())
    target = result.broker_positions          # FakeBroker(equity) ending book = desired portfolio
    real = real_broker.positions()

    submitted: list[tuple] = []
    for symbol in set(target) | set(real):
        tq = round(target[symbol].qty) if symbol in target else 0
        cq = real[symbol].qty if symbol in real else 0.0
        delta = tq - cq
        if abs(delta) >= 1:
            real_broker.submit(OrderIntent("core", symbol, delta, None))
            submitted.append((symbol, delta))
    return submitted
