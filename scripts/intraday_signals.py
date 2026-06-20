"""Intraday signal research — do the intraday bots' premises (reversion / breakout) actually
predict forward returns? Tests pooled IC across a DIVERSE universe, split by sub-period and by
name volatility, to find where (if anywhere) an edge exists — without overfitting one name/period.

Covers:
- VWAP/Bollinger reversion premise: does a short-term move predict REVERSAL? (signal = −past return)
- ORB/intraday-momentum premise: that's just the sign flip (momentum IC = −reversal IC).

Usage: .venv/bin/python scripts/intraday_signals.py
"""

from __future__ import annotations

import hashlib
import os
import pickle
import sys
from datetime import datetime

import numpy as np

sys.path.insert(0, "src")

from alpaca.data.historical import StockHistoricalDataClient  # noqa: E402
from alpaca.data.timeframe import TimeFrame  # noqa: E402

from traderbot.cli import load_dotenv  # noqa: E402
from traderbot.integrations.alpaca import fetch_historical_bars  # noqa: E402

UNIVERSE = ["AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "SPY", "QQQ", "JPM", "XOM", "KO", "PFE"]
START, END = "2026-03-15", "2026-06-13"


def get_bars():
    key = hashlib.md5(f"min{UNIVERSE}{START}{END}".encode()).hexdigest()[:8]
    path = f"data/min_{key}.pkl"
    if not os.path.exists(path):
        load_dotenv()
        client = StockHistoricalDataClient(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"])
        bars = fetch_historical_bars(client, UNIVERSE, datetime.fromisoformat(START),
                                     datetime.fromisoformat(END), timeframe=TimeFrame.Minute)
        os.makedirs("data", exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(bars, f)
    with open(path, "rb") as f:
        return pickle.load(f)


def reversal_pairs(closes_by_day, k, h):
    """Yield (signal=-past_k_return, fwd=next_h_return) within each day."""
    sigs, fwds = [], []
    for c in closes_by_day:
        c = np.asarray(c, dtype=float)
        if len(c) < k + h + 1:
            continue
        i0, i1 = k, len(c) - h
        sig = -(c[i0:i1] / c[i0 - k:i1 - k] - 1.0)
        fwd = c[i0 + h:i1 + h] / c[i0:i1] - 1.0
        sigs.append(sig)
        fwds.append(fwd)
    if not sigs:
        return np.array([]), np.array([])
    return np.concatenate(sigs), np.concatenate(fwds)


def ic(sig, fwd):
    if len(sig) < 100:
        return float("nan"), 0
    m = np.isfinite(sig) & np.isfinite(fwd)
    if m.sum() < 100:
        return float("nan"), 0
    return float(np.corrcoef(sig[m], fwd[m])[0, 1]), int(m.sum())


def by_day(bars_for_symbol):
    days: dict = {}
    for b in bars_for_symbol:
        days.setdefault(b.ts.date(), []).append(b.close)
    return list(days.values())


def main():
    bars = get_bars()
    total = sum(len(v) for v in bars.values())
    print(f"intraday: {len(bars)} names  bars={total}  {START}..{END}")

    # per-name daily closes + a volatility measure (for the high/low-vol split)
    closes = {s: by_day(v) for s, v in bars.items()}
    name_vol = {s: float(np.nanstd(np.concatenate([np.diff(np.log(d)) for d in dd if len(d) > 1])))
                for s, dd in closes.items()}
    median_vol = np.median(list(name_vol.values()))
    hi = [s for s in UNIVERSE if name_vol[s] >= median_vol]
    lo = [s for s in UNIVERSE if name_vol[s] < median_vol]

    print("reversal signal IC (positive IC = mean-reversion works; negative = momentum works)")
    print("  (k,h) min   pooled_IC      n        hi-vol_IC   lo-vol_IC")
    for k, h in [(5, 5), (15, 15), (30, 30), (30, 60)]:
        allsig = np.concatenate([reversal_pairs(closes[s], k, h)[0] for s in UNIVERSE])
        allfwd = np.concatenate([reversal_pairs(closes[s], k, h)[1] for s in UNIVERSE])
        pooled, n = ic(allsig, allfwd)
        his = np.concatenate([reversal_pairs(closes[s], k, h)[0] for s in hi])
        hif = np.concatenate([reversal_pairs(closes[s], k, h)[1] for s in hi])
        los = np.concatenate([reversal_pairs(closes[s], k, h)[0] for s in lo])
        lof = np.concatenate([reversal_pairs(closes[s], k, h)[1] for s in lo])
        print(f"  ({k:2d},{h:2d})      {pooled:+.4f}   {n:8d}   {ic(his, hif)[0]:+.4f}     {ic(los, lof)[0]:+.4f}")

    print("time stability — IS (first 60% of days) / OOS (last 40%):")

    def pooled_split(k, h, f0, f1, names):
        s, f = [], []
        for sym in names:
            dd = closes[sym]
            si, fi = reversal_pairs(dd[int(len(dd) * f0):int(len(dd) * f1)], k, h)
            s.append(si)
            f.append(fi)
        return ic(np.concatenate(s), np.concatenate(f))[0]

    for k, h in [(15, 15), (30, 60)]:
        print(f"  ({k},{h}) pooled IS={pooled_split(k, h, 0, 0.6, UNIVERSE):+.4f} "
              f"OOS={pooled_split(k, h, 0.6, 1.0, UNIVERSE):+.4f}   "
              f"hi-vol OOS={pooled_split(k, h, 0.6, 1.0, hi):+.4f}")

    print("edge vs cost — gross per-trade L/S edge (top−bottom signal quintile), in bps:")

    def quintile_edge(sig, fwd):
        m = np.isfinite(sig) & np.isfinite(fwd)
        sig, fwd = sig[m], fwd[m]
        q = np.quantile(sig, [0.2, 0.8])
        return (fwd[sig >= q[1]].mean() - fwd[sig <= q[0]].mean()) * 1e4

    for k, h, names in [(5, 5, UNIVERSE), (15, 15, UNIVERSE), (30, 60, hi)]:
        s = np.concatenate([reversal_pairs(closes[x], k, h)[0] for x in names])
        f = np.concatenate([reversal_pairs(closes[x], k, h)[1] for x in names])
        tag = "hi-vol" if names is hi else "all"
        print(f"  ({k:2d},{h:2d}) {tag:6} gross edge = {quintile_edge(s, f):+5.1f} bps/round-trip "
              f"(vs ~2-4 bps cost)")


if __name__ == "__main__":
    main()
