"""Backtest metrics + the equal-weight benchmark (the allocator's null hypothesis).

Computed directly with numpy/pandas so results are deterministic and dependency-light;
empyrical/quantstats can be swapped in later for richer tear-sheets.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _returns(curve: list[float]) -> np.ndarray:
    arr = np.asarray(curve, dtype=float)
    if arr.size < 2:
        return np.array([])
    prev = arr[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(prev != 0, np.diff(arr) / prev, 0.0)
    return r


def sharpe(curve: list[float], periods_per_year: int = 252) -> float:
    r = _returns(curve)
    if r.size == 0 or r.std() == 0:
        return 0.0
    return float(r.mean() / r.std() * np.sqrt(periods_per_year))


def max_drawdown(curve: list[float]) -> float:
    if not curve:
        return 0.0
    arr = np.asarray(curve, dtype=float)
    peak = np.maximum.accumulate(arr)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peak > 0, (peak - arr) / peak, 0.0)
    return float(dd.max())


def hit_rate(curve: list[float]) -> float:
    r = _returns(curve)
    if r.size == 0:
        return 0.0
    return float((r > 0).mean())


def turnover(fills: list[dict], avg_equity: float) -> float:
    if avg_equity <= 0:
        return 0.0
    traded = sum(abs(f["qty"] * f["price"]) for f in fills)
    return traded / avg_equity


def inter_bot_correlation(per_bot_equity: dict[str, list[float]]) -> pd.DataFrame:
    cols = {bot: _returns(curve) for bot, curve in per_bot_equity.items()}
    n = min((c.size for c in cols.values()), default=0)
    if n == 0:
        return pd.DataFrame()
    frame = pd.DataFrame({bot: c[-n:] for bot, c in cols.items()})
    return frame.corr()


def equal_weight_benchmark(per_bot_equity: dict[str, list[float]], starting_equity: float) -> list[float]:
    curves = [np.asarray(c, dtype=float) for c in per_bot_equity.values() if c]
    if not curves:
        return []
    n = min(c.size for c in curves)
    stacked = np.vstack([c[-n:] for c in curves])
    return list(starting_equity + stacked.mean(axis=0))


def metrics(result, periods_per_year: int = 252) -> dict:
    curve = result.equity_curve
    avg_equity = float(np.mean(curve)) if curve else 0.0
    return {
        "sharpe": sharpe(curve, periods_per_year),
        "max_drawdown": max_drawdown(curve),
        "hit_rate": hit_rate(curve),
        "turnover": turnover(result.fills, avg_equity),
    }


def allocator_beats_equal_weight(result, starting_equity: float, periods_per_year: int = 252) -> bool:
    bench = equal_weight_benchmark(result.per_bot_equity, starting_equity)
    return sharpe(result.equity_curve, periods_per_year) >= sharpe(bench, periods_per_year)
