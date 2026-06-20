"""Honest projection: run the momentum strategy through the full system, measure the last 2 years,
and report the EMPIRICAL distribution of 2-month (42-trading-day) outcomes on a $100k account.
"""

from __future__ import annotations

import asyncio
import sys

import numpy as np

sys.path.insert(0, "src")
sys.path.insert(0, "scripts")

from signals import get_daily_bars  # noqa: E402

from traderbot.backtest.runner import run_backtest  # noqa: E402
from traderbot.config import Config  # noqa: E402
from traderbot.market_data.source import ReplaySource  # noqa: E402
from traderbot.strategies.momentum import CrossSectionalMomentumBot  # noqa: E402

START_BAL = 100_000.0


async def main():
    bars = get_daily_bars()
    n_sym = len(bars)
    cfg = Config.default()  # suspension now resets per session (fixed), so default risk is fine
    res = await run_backtest(cfg, ReplaySource(bars), [CrossSectionalMomentumBot("mom", list(bars.keys()))])

    eq = np.array(res.equity_curve, dtype=float)  # one point per bar (~n_sym/day)
    eq2y = eq[-504 * n_sym:]  # last ~2 years of bars
    total = eq2y[-1] / eq2y[0] - 1
    peak = np.maximum.accumulate(eq2y)
    mdd = ((peak - eq2y) / peak).max()

    W = 42 * n_sym  # a 2-month window, in bars
    roll = np.array([eq2y[i + W] / eq2y[i] - 1 for i in range(0, len(eq2y) - W, n_sym)])

    print(f"=== momentum strategy through the FULL system, last 2 years ===")
    print(f"  total return: {total:+.2%}   max drawdown: {mdd:.2%}   fills: {len(res.fills)}")
    print(f"  (note: nearly-static book on this 44 large-cap universe — low turnover, low risk)")
    print()
    print(f"=== 2-month outcome on ${START_BAL:,.0f} (empirical, {len(roll)} overlapping windows) ===")
    for label, pct in [("worst", roll.min()), ("10th pct", np.percentile(roll, 10)),
                       ("median", np.median(roll)), ("mean", roll.mean()),
                       ("90th pct", np.percentile(roll, 90)), ("best", roll.max())]:
        print(f"  {label:9} {pct:+7.2%}  ->  ${START_BAL * (1 + pct):>11,.0f}   (Δ ${START_BAL * pct:+,.0f})")
    print(f"  share of 2-month windows positive: {(roll > 0).mean():.0%}")


if __name__ == "__main__":
    asyncio.run(main())
