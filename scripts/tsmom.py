"""Validate TIME-SERIES (trend) momentum on a diversified multi-asset ETF basket — a candidate
new bot, decorrelated from cross-sectional equity momentum. Tests pooled IC + a vol-scaled
long/short trend portfolio (Sharpe IS/OOS, maxDD). Prices-only → retail-viable, no new data API.
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

# diversified across equity regions, rates, credit, commodities, real estate, USD
ETFS = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "LQD", "HYG", "GLD",
        "SLV", "DBC", "USO", "VNQ", "UUP", "XLE", "XLK", "XLF"]
START, END = "2018-06-01", "2026-06-13"


def get_panel():
    key = hashlib.md5(f"etf{ETFS}{START}{END}".encode()).hexdigest()[:8]
    path = f"data/etf_{key}.pkl"
    if not os.path.exists(path):
        load_dotenv()
        client = StockHistoricalDataClient(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"])
        bars = fetch_historical_bars(client, ETFS, datetime.fromisoformat(START),
                                     datetime.fromisoformat(END), timeframe=TimeFrame.Day)
        os.makedirs("data", exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(bars, f)
    with open(path, "rb") as f:
        bars = pickle.load(f)
    series = {s: pd.Series({b.ts.date(): b.close for b in bl}) for s, bl in bars.items()}
    return pd.DataFrame(series).sort_index()


def sharpe(x):
    return x.mean() / (x.std() + 1e-12) * np.sqrt(252)


def maxdd(curve):
    peak = np.maximum.accumulate(curve)
    return float(((peak - curve) / peak).max())


def main():
    panel = get_panel()
    rets = panel.pct_change()
    print(f"ETFs={panel.shape[1]}  days={panel.shape[0]}  {START}..{END}")

    trail = panel.pct_change(252)               # 12-month trend
    vol = rets.rolling(60).std()

    # pooled IC: does trailing trend predict forward 21d return? (time-series, pooled)
    fwd = panel.pct_change(21).shift(-21)
    s = trail.values.flatten()
    f = fwd.values.flatten()
    m = np.isfinite(s) & np.isfinite(f)
    ic = np.corrcoef(s[m], f[m])[0, 1]
    print(f"pooled TSMOM IC (trailing 12m vs fwd 21d): {ic:+.4f}  n={m.sum()}")

    # vol-scaled trend portfolio: long up-trend / short down-trend, inverse-vol, gross-normalized
    pos = np.sign(trail) / (vol + 1e-9)
    pos = pos.div(pos.abs().sum(axis=1), axis=0)        # gross = 1 each day
    port = (pos.shift(1) * rets).sum(axis=1).dropna()   # next-day return, no lookahead
    curve = 100_000 * (1 + port).cumprod()

    split = int(len(port) * 0.6)
    print(f"trend portfolio: ann_ret={port.mean()*252:+.1%}  sharpe={sharpe(port):+.2f}  "
          f"IS={sharpe(port.iloc[:split]):+.2f}  OOS={sharpe(port.iloc[split:]):+.2f}  "
          f"maxDD={maxdd(curve.values):.1%}")


if __name__ == "__main__":
    main()
