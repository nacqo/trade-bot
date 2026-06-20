"""Signal research harness — measures whether a candidate signal PREDICTS forward returns.

Cross-sectional daily research over a universe: for each day, rank names by the signal and
correlate that ranking with forward returns (rank Information Coefficient). A real signal has a
consistent IC sign in-sample AND out-of-sample, a decent information ratio (mean IC / std IC), and
a positive top-minus-bottom decile spread after we account for it being daily.

This is research (does X predict returns?), not strategy tuning. Most candidates fail — that's the
point.

Usage: .venv/bin/python scripts/signals.py
"""

from __future__ import annotations

import hashlib
import os
import pickle
import sys
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, "src")

from alpaca.data.historical import StockHistoricalDataClient  # noqa: E402
from alpaca.data.timeframe import TimeFrame  # noqa: E402

from traderbot.cli import load_dotenv  # noqa: E402
from traderbot.integrations.alpaca import fetch_historical_bars  # noqa: E402

UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "BAC", "WFC",
    "XOM", "CVX", "COP", "KO", "PEP", "PG", "WMT", "HD", "MCD", "DIS",
    "NKE", "V", "MA", "UNH", "JNJ", "PFE", "MRK", "CSCO", "INTC", "AMD",
    "QCOM", "CRM", "ORCL", "IBM", "T", "VZ", "CMCSA", "COST", "TGT", "LOW",
    "CAT", "BA", "GE", "HON",
]
START, END = "2021-06-01", "2026-06-13"


def get_daily_bars():
    key = hashlib.md5(f"daily{UNIVERSE}{START}{END}".encode()).hexdigest()[:8]
    path = f"data/daily_{key}.pkl"
    if not os.path.exists(path):
        load_dotenv()
        client = StockHistoricalDataClient(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"])
        bars = fetch_historical_bars(
            client, UNIVERSE, datetime.fromisoformat(START), datetime.fromisoformat(END),
            timeframe=TimeFrame.Day,
        )
        os.makedirs("data", exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(bars, f)
    with open(path, "rb") as f:
        return pickle.load(f)


def panel_from_bars(bars):
    series = {sym: pd.Series({b.ts.date(): b.close for b in blist}) for sym, blist in bars.items()}
    return pd.DataFrame(series).sort_index()


def rank_ic_series(signal: pd.DataFrame, fwd: pd.DataFrame, min_names: int = 8) -> pd.Series:
    ics = {}
    for dt in signal.index:
        s, f = signal.loc[dt], fwd.loc[dt]
        v = s.notna() & f.notna()
        if v.sum() >= min_names:
            ics[dt] = s[v].rank().corr(f[v].rank())
    return pd.Series(ics).dropna()


def report(name: str, signal: pd.DataFrame, panel: pd.DataFrame, horizons=(1, 5, 10)) -> None:
    for h in horizons:
        fwd = panel.pct_change(h).shift(-h)
        ic = rank_ic_series(signal, fwd)
        if ic.empty:
            continue
        split = int(len(ic) * 0.6)
        is_ic, oos_ic = ic.iloc[:split], ic.iloc[split:]
        ir = ic.mean() / (ic.std() + 1e-12)
        t = ir * np.sqrt(len(ic))
        print(f"  {name:14} h={h:2d}  IC={ic.mean():+.4f}  IR={ir:+.3f}  t={t:+.1f}  "
              f"IS={is_ic.mean():+.4f}  OOS={oos_ic.mean():+.4f}  n={len(ic)}")


def long_short(signal: pd.DataFrame, panel: pd.DataFrame, q: float = 0.2) -> pd.Series:
    """Daily-rebalanced equal-weight long-top-q / short-bottom-q decile spread, next-day return."""
    fwd1 = panel.pct_change().shift(-1)
    out = {}
    for dt in signal.index:
        s, f = signal.loc[dt], fwd1.loc[dt]
        v = s.notna() & f.notna()
        if v.sum() < 10:
            continue
        sv, fv = s[v], f[v]
        n = max(1, int(len(sv) * q))
        order = sv.sort_values().index
        out[dt] = fv[order[-n:]].mean() - fv[order[:n]].mean()
    return pd.Series(out).dropna()


def ls_report(name: str, signal: pd.DataFrame, panel: pd.DataFrame) -> None:
    ls = long_short(signal, panel)
    if ls.empty:
        return
    split = int(len(ls) * 0.6)
    is_ls, oos_ls = ls.iloc[:split], ls.iloc[split:]

    def sh(x):
        return x.mean() / (x.std() + 1e-12) * np.sqrt(252)

    print(f"  {name:14} L/S ann_ret={ls.mean() * 252:+.3f}  sharpe={sh(ls):+.2f}  "
          f"IS_sharpe={sh(is_ls):+.2f}  OOS_sharpe={sh(oos_ls):+.2f}")


async def system_backtest(bars):
    import asyncio  # noqa

    from traderbot.backtest.metrics import metrics
    from traderbot.backtest.runner import run_backtest
    from traderbot.config import Config
    from traderbot.market_data.source import ReplaySource
    from traderbot.strategies.momentum import CrossSectionalMomentumBot

    from traderbot.backtest.metrics import max_drawdown, sharpe

    cfg = Config.default()
    n_sym = len(bars)
    bot = CrossSectionalMomentumBot("mom", list(bars.keys()))
    res = await run_backtest(cfg, ReplaySource(bars), [bot])
    # equity_curve has one point PER BAR (n_sym/day); sample end-of-day for a daily Sharpe
    daily_eq = res.equity_curve[n_sym - 1 :: n_sym]
    m = metrics(res, periods_per_year=252)
    print(f"  system momentum bot: days={len(daily_eq)} fills={len(res.fills)} "
          f"sharpe(daily)={sharpe(daily_eq, 252):+.2f} dd={max_drawdown(daily_eq):.3f} turn={m['turnover']:.1f}")


def main():
    import asyncio

    bars = get_daily_bars()
    panel = panel_from_bars(bars)
    rets = panel.pct_change()
    print(f"universe={panel.shape[1]} names  days={panel.shape[0]}  {START}..{END}")

    signals = {
        "rev_1d": -rets,
        "rev_5d": -panel.pct_change(5),
        "mom_3_1": (panel.shift(21) / panel.shift(63) - 1),
        "mom_6_1": (panel.shift(21) / panel.shift(126) - 1),
        "mom_12_1": (panel.shift(21) / panel.shift(252) - 1),
        "mom_12_1_volscaled": (panel.shift(21) / panel.shift(252) - 1) / (rets.rolling(126).std() + 1e-9),
        "lowvol_21d": -rets.rolling(21).std(),
    }
    print("signal          horizon   IC      IR      t      IS       OOS")
    for name, sig in signals.items():
        report(name, sig, panel)
    print("--- long/short decile backtest (gross, daily reb) ---")
    for name, sig in signals.items():
        ls_report(name, sig, panel)
    print("--- momentum signal through the full system (stops/sizing/risk/costs) ---")
    asyncio.run(system_backtest(bars))


if __name__ == "__main__":
    main()
