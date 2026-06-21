"""Backtest evaluation harness. Fetches real Alpaca bars once (cached to data/), then runs the
strategies solo and combined over the cached data and prints compact metrics. Re-run after code
changes to iterate without re-downloading.

Usage: .venv/bin/python scripts/eval.py
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import pickle
import sys
from datetime import datetime

sys.path.insert(0, "src")

from alpaca.data.historical import StockHistoricalDataClient  # noqa: E402

from traderbot.backtest.metrics import metrics  # noqa: E402
from traderbot.backtest.runner import run_backtest  # noqa: E402
from traderbot.backtest.validation import oos_report  # noqa: E402
from traderbot.cli import load_dotenv  # noqa: E402
from traderbot.config import Config  # noqa: E402
from traderbot.integrations.alpaca import fetch_historical_bars  # noqa: E402
from traderbot.market_data.source import ReplaySource  # noqa: E402
from traderbot.strategies.orb import ORBBot  # noqa: E402

SYMBOLS = ["KO", "PEP", "XOM", "CVX"]
PAIRS = [("KO", "PEP"), ("XOM", "CVX")]
START, END = "2026-03-02", "2026-06-13"


def get_bars(symbols, start, end):
    key = hashlib.md5(f"{symbols}{start}{end}".encode()).hexdigest()[:8]
    path = f"data/bars_{key}.pkl"
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    load_dotenv()
    client = StockHistoricalDataClient(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"])
    bars = fetch_historical_bars(client, symbols, datetime.fromisoformat(start), datetime.fromisoformat(end))
    os.makedirs("data", exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(bars, f)
    return bars


def cfg():
    return Config.default()


async def run(name, bots, bars, show_weights=False):
    res = await run_backtest(cfg(), ReplaySource(bars), bots)
    m = metrics(res, periods_per_year=252 * 390)
    oos = oos_report(res, cfg().starting_equity, windows=4)
    line = (f"{name:18} fills={len(res.fills):6} sharpe={m['sharpe']:8.2f} "
            f"dd={m['max_drawdown']:.3f} turn={m['turnover']:8.1f} "
            f"OOSa/ew={oos['oos_sharpe_allocator']:6.2f}/{oos['oos_sharpe_equal_weight']:6.2f}")
    if show_weights and res.weights_history:
        w = res.weights_history[-1]
        line += "  w=" + " ".join(f"{k}:{v:.2f}" for k, v in sorted(w.items()))
    print(line)


def make_combined():
    return [ORBBot("orb", SYMBOLS, opening_minutes=15)]


async def main():
    bars = get_bars(SYMBOLS, START, END)
    n = sum(len(v) for v in bars.values())
    print(f"data: {SYMBOLS} {START}..{END}  bars={n}")
    await run("solo orb", [ORBBot("orb", SYMBOLS, opening_minutes=15)], bars)
    await run("combined", make_combined(), bars, show_weights=True)

    # robustness: run combined over sequential thirds (different regimes)
    print("--- combined over sub-periods (risk/behaviour stability) ---")
    keys = list(bars)
    for i, (lo, hi) in enumerate([(0.0, 0.34), (0.33, 0.67), (0.66, 1.0)]):
        sub = {k: v[int(len(v) * lo):int(len(v) * hi)] for k, v in bars.items()}
        await run(f"third {i + 1}", make_combined(), sub, show_weights=True)


if __name__ == "__main__":
    asyncio.run(main())
