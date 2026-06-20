"""Out-of-sample / walk-forward validation — the test that matters for the allocator.

The bots warm up online (cointegration refit, EWMA scoring) over the train portion; performance
is judged only on the **out-of-sample** tail, comparing the dynamic allocator against the
equal-weight null hypothesis (pre-mortem A1). Sharpe is offset-invariant, so slicing cumulative
equity curves is a valid comparison. `windows` sub-divides the OOS tail to report robustness.
"""

from __future__ import annotations

from traderbot.backtest.metrics import equal_weight_benchmark, max_drawdown, sharpe


def oos_report(
    result,
    starting_equity: float,
    train_frac: float = 0.5,
    windows: int = 1,
    periods_per_year: int = 252,
) -> dict:
    n = len(result.equity_curve)
    cut = int(n * train_frac)

    def window(lo: int, hi: int) -> tuple[float, float]:
        eq = result.equity_curve[lo:hi]
        per_bot = {b: c[lo:hi] for b, c in result.per_bot_equity.items()}
        bench = equal_weight_benchmark(per_bot, starting_equity)
        return sharpe(eq, periods_per_year), sharpe(bench, periods_per_year)

    alloc_sharpe, ew_sharpe = window(cut, n)

    wins = total = 0
    if windows > 1 and (n - cut) >= windows:
        step = (n - cut) // windows
        for k in range(windows):
            lo = cut + k * step
            hi = n if k == windows - 1 else cut + (k + 1) * step
            wa, we = window(lo, hi)
            total += 1
            wins += int(wa >= we)
    else:
        total = 1
        wins = int(alloc_sharpe >= ew_sharpe)

    return {
        "oos_sharpe_allocator": alloc_sharpe,
        "oos_sharpe_equal_weight": ew_sharpe,
        "allocator_beats_equal_weight_oos": alloc_sharpe >= ew_sharpe,
        "oos_max_drawdown": max_drawdown(result.equity_curve[cut:]),
        "windows_allocator_won": wins,
        "windows_total": total,
    }
