"""Validate the blended live core: residmom + trend + momentum through ONE engine/allocator.
Shows the combined Sharpe + 2-month sim vs each strategy solo (diversification benefit).
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date

import numpy as np

sys.path.insert(0, "src")
sys.path.insert(0, "scripts")

from alpaca.data.timeframe import TimeFrame  # noqa: E402
from evaluate import ETFS, U44, _load  # noqa: E402

from traderbot.backtest.metrics import max_drawdown  # noqa: E402
from traderbot.backtest.runner import run_backtest  # noqa: E402
from traderbot.config import Config  # noqa: E402
from traderbot.market_data.source import ReplaySource  # noqa: E402
from traderbot.strategies.momentum import CrossSectionalMomentumBot  # noqa: E402
from traderbot.strategies.residual_momentum import ResidualMomentumBot  # noqa: E402
from traderbot.strategies.trend import TimeSeriesMomentumBot  # noqa: E402


def stats(eq, n_sym):
    deq = np.asarray(eq, float)[n_sym - 1::n_sym]
    r = np.diff(deq) / deq[:-1]
    r = r[np.isfinite(r)]
    sh = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0.0
    W = 42
    roll = np.array([deq[i + W] / deq[i] - 1 for i in range(len(deq) - W)]) if len(deq) > W else np.array([0.0])
    return sh, max_drawdown(list(deq)), np.median(roll), np.percentile(roll, 10), np.percentile(roll, 90)


async def main():
    daily44 = _load("daily", f"daily{U44}2021-06-012026-06-13", U44, "2021-06-01", "2026-06-13", TimeFrame.Day)
    etf = _load("etf", f"etf{ETFS}2018-06-012026-06-13", ETFS, "2018-06-01", "2026-06-13", TimeFrame.Day)
    etf = {s: [b for b in bl if b.ts.date() >= date(2021, 6, 1)] for s, bl in etf.items()}
    bars = {**daily44, **etf}
    n_sym = len(bars)
    print(f"blended core: {n_sym} symbols (44 equities + 18 ETFs)  days~{len(next(iter(daily44.values())))}")

    cfg = Config.default()
    cfg.allocator.min_obs = 20
    bots = [
        CrossSectionalMomentumBot("momentum", list(daily44.keys())),
        ResidualMomentumBot("residmom", list(daily44.keys())),
        TimeSeriesMomentumBot("trend", list(etf.keys())),
    ]
    res = await run_backtest(cfg, ReplaySource(bars), bots)
    sh, mdd, med, p10, p90 = stats(res.equity_curve, n_sym)
    print(f"\nBLENDED (allocator-weighted 3 factors):")
    print(f"  Sharpe {sh:+.2f}  maxDD {mdd:.1%}  fills {len(res.fills)}")
    print(f"  2-month on $100k: median {med*100_000:+,.0f}  [{p10*100_000:+,.0f} .. {p90*100_000:+,.0f}]")
    print(f"  final weights: " + " ".join(f"{k}:{v:.2f}" for k, v in res.weights_history[-1].items()))

    print("\nvs solo (Sharpe):")
    for name, blist in [("momentum", [bots[0]]), ("residmom", [bots[1]]), ("trend", [bots[2]])]:
        sub = daily44 if name != "trend" else etf
        b = (CrossSectionalMomentumBot("momentum", list(daily44.keys())) if name == "momentum"
             else ResidualMomentumBot("residmom", list(daily44.keys())) if name == "residmom"
             else TimeSeriesMomentumBot("trend", list(etf.keys())))
        r = await run_backtest(Config.default(), ReplaySource(sub), [b])
        s, _, _, _, _ = stats(r.equity_curve, len(sub))
        print(f"  {name:9} {s:+.2f}")


if __name__ == "__main__":
    asyncio.run(main())
