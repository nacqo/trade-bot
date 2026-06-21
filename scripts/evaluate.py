"""Strategy evaluation engine (driven by the `evaluation` skill).

Backtests every implemented strategy on its appropriate real data, rates each /100, ranks them,
runs the same 2-month outcome simulation as scripts/project.py, and prints improve/drop guidance.

Rating /100 = Sharpe(50) + drawdown-control(20) + cost/turnover(15) + 2-month-positivity(15).

Usage: .venv/bin/python scripts/evaluate.py
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import pickle
import sys
from datetime import datetime

import numpy as np

sys.path.insert(0, "src")

from alpaca.data.historical import StockHistoricalDataClient  # noqa: E402
from alpaca.data.timeframe import TimeFrame  # noqa: E402

from traderbot.backtest.metrics import max_drawdown, sharpe, turnover  # noqa: E402
from traderbot.backtest.runner import run_backtest  # noqa: E402
from traderbot.cli import load_dotenv  # noqa: E402
from traderbot.config import Config  # noqa: E402
from traderbot.integrations.alpaca import fetch_historical_bars  # noqa: E402
from traderbot.market_data.source import ReplaySource  # noqa: E402
from traderbot.strategies.orb import ORBBot  # noqa: E402
from traderbot.strategies.momentum import CrossSectionalMomentumBot  # noqa: E402
from traderbot.strategies.residual_momentum import ResidualMomentumBot  # noqa: E402
from traderbot.strategies.stat_arb import StatArbBot  # noqa: E402
from traderbot.strategies.trend import TimeSeriesMomentumBot  # noqa: E402
from traderbot.strategies.vwap_reversion import VWAPReversionBot  # noqa: E402

U44 = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "BAC", "WFC",
       "XOM", "CVX", "COP", "KO", "PEP", "PG", "WMT", "HD", "MCD", "DIS",
       "NKE", "V", "MA", "UNH", "JNJ", "PFE", "MRK", "CSCO", "INTC", "AMD",
       "QCOM", "CRM", "ORCL", "IBM", "T", "VZ", "CMCSA", "COST", "TGT", "LOW",
       "CAT", "BA", "GE", "HON"]
ETFS = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "LQD", "HYG", "GLD",
        "SLV", "DBC", "USO", "VNQ", "UUP", "XLE", "XLK", "XLF"]
MIN4 = ["KO", "PEP", "XOM", "CVX"]


def _load(prefix, hash_input, universe, start, end, timeframe):
    path = f"data/{prefix}_{hashlib.md5(hash_input.encode()).hexdigest()[:8]}.pkl"
    if not os.path.exists(path):
        load_dotenv()
        client = StockHistoricalDataClient(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"])
        bars = fetch_historical_bars(client, universe, datetime.fromisoformat(start),
                                     datetime.fromisoformat(end), timeframe=timeframe)
        os.makedirs("data", exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(bars, f)
    with open(path, "rb") as f:
        return pickle.load(f)


def rate(sh, mdd, turn, pos):
    sh_pts = max(0.0, min(sh, 2.0)) / 2.0 * 50
    dd_pts = 20 * (1 - min(mdd / 0.25, 1.0))
    turn_pts = 15 * (1 - min(turn / 80.0, 1.0))
    pos_pts = 15 * pos
    return round(sh_pts + dd_pts + turn_pts + pos_pts)


async def evaluate(name, bot, bars, is_daily):
    res = await run_backtest(Config.default(), ReplaySource(bars), [bot])
    eq = np.asarray(res.equity_curve, dtype=float)
    n_sym = len(bars)
    days = max(1.0, len(eq) / n_sym / (1 if is_daily else 390))   # trading days of data
    years = max(days / 252.0, 1e-6)
    ppy = len(eq) / years                                         # bars per year
    r = np.diff(eq) / eq[:-1]
    r = r[np.isfinite(r)]
    sh = float(r.mean() / r.std() * np.sqrt(ppy)) if r.std() > 0 else 0.0
    mdd = max_drawdown(list(eq))
    turn = turnover(res.fills, float(eq.mean()))
    # 2-month outcomes: window the per-bar equity by the #bars in 2 months, stepped ~daily
    W = max(1, round(len(eq) * (2.0 / 12.0) / years))
    step = max(1, round(len(eq) / days))
    roll = (np.array([eq[i + W] / eq[i] - 1 for i in range(0, len(eq) - W, step)])
            if len(eq) > W else np.array([0.0]))
    pos = float((roll > 0).mean())
    return {
        "name": name, "sharpe": sh, "mdd": mdd, "turn": turn, "fills": len(res.fills),
        "rating": rate(sh, mdd, turn, pos), "roll": roll, "pos": pos, "years": years,
    }


GUIDANCE = {
    "momentum": "KEEP (core). Improve: widen universe to 100-500 names, sector-neutralize, blend 6-1+12-1.",
    "residmom": "KEEP (best risk-adj momentum; market-neutral). Improve: sector-neutralize, blend with plain momentum.",
    "trend": "KEEP (diversifier). Improve: add asset classes, blend fast+slow trend, target constant vol.",
    "stat-arb": "KEEP THIN. Improve: trade only strongly-cointegrated pairs, size for spread>cost, longer holds.",
    "orb": "FIX or drop. Improve: switch to a HIGH-VOL universe (NVDA/TSLA/AMD) + 30-60min holds; edgeless on low-vol.",
    "vwap": "DROP candidate. 15-min reversion edge (+1.8bps) < cost (~2-4bps) at retail; needs rebates/HFT to win.",
}


async def main():
    daily44 = _load("daily", f"daily{U44}2021-06-012026-06-13", U44, "2021-06-01", "2026-06-13", TimeFrame.Day)
    etf = _load("etf", f"etf{ETFS}2018-06-012026-06-13", ETFS, "2018-06-01", "2026-06-13", TimeFrame.Day)
    minute = _load("bars", f"{MIN4}2026-03-022026-06-13", MIN4, "2026-03-02", "2026-06-13", TimeFrame.Minute)

    configs = [
        ("momentum", CrossSectionalMomentumBot("m", list(daily44.keys())), daily44, True),
        ("residmom", ResidualMomentumBot("rm", list(daily44.keys())), daily44, True),
        ("trend", TimeSeriesMomentumBot("t", list(etf.keys())), etf, True),
        ("stat-arb", StatArbBot("s", [("KO", "PEP")], lookback=60), minute, False),
        ("orb", ORBBot("o", MIN4, opening_minutes=15), minute, False),
        ("vwap", VWAPReversionBot("v", MIN4, bb_period=20), minute, False),
    ]
    results = [await evaluate(n, b, d, daily) for n, b, d, daily in configs]
    results.sort(key=lambda r: r["rating"], reverse=True)

    print("\n================ STRATEGY RANKING ================")
    print(f"{'#':>2} {'strategy':10} {'rating':>7} {'sharpe':>7} {'maxDD':>6} {'turn':>6} {'fills':>6}")
    for i, r in enumerate(results, 1):
        print(f"{i:>2} {r['name']:10} {r['rating']:>5}/100 {r['sharpe']:>7.2f} "
              f"{r['mdd']:>6.1%} {r['turn']:>6.1f} {r['fills']:>6}")

    print("\n========= 2-MONTH SIMULATION on $100,000 (empirical) =========")
    for r in results:
        roll = r["roll"]
        med, p10, p90 = np.median(roll), np.percentile(roll, 10), np.percentile(roll, 90)
        flag = "" if r["years"] >= 1.5 else "  ⚠ LOW-CONFIDENCE (short sample / overlapping windows)"
        print(f"  {r['name']:10} median {med * 100_000:+8,.0f}  "
              f"[{p10 * 100_000:+8,.0f} .. {p90 * 100_000:+8,.0f}]  pos {r['pos']:.0%}{flag}")

    print("\n================ GUIDANCE ================")
    for r in results:
        print(f"  {r['name']:10} {GUIDANCE.get(r['name'], '')}")
    print(f"\nRecommended DROP: {results[-1]['name']} (lowest rated).")


if __name__ == "__main__":
    asyncio.run(main())
