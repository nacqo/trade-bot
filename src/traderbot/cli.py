"""Command-line entry points: `traderbot status | backtest | paper`."""

from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime, timedelta, timezone

import structlog

from traderbot.backtest.metrics import metrics
from traderbot.backtest.runner import run_backtest
from traderbot.config import Config
from traderbot.market_data.source import ReplaySource
from traderbot.state.store import StateStore
from traderbot.strategies.dormant import DormantBot
from traderbot.strategies.orb import ORBBot
from traderbot.strategies.vwap_reversion import VWAPReversionBot
from traderbot.types import Bar


def configure_logging() -> None:
    structlog.configure(processors=[structlog.processors.add_log_level, structlog.dev.ConsoleRenderer()])


def _demo_source() -> ReplaySource:
    t0 = datetime(2026, 6, 20, 13, 30, tzinfo=timezone.utc)
    bars = {}
    for sym, base, slope in (("AAA", 100.0, 0.3), ("BBB", 100.0, -0.2)):
        series = []
        for m in range(40):
            price = base + slope * m + (1.5 if m % 7 == 0 else 0.0)
            series.append(Bar(sym, t0 + timedelta(minutes=m), price, price + 0.5, price - 0.5, price, 5000))
        bars[sym] = series
    return ReplaySource(bars)


def cmd_backtest(args) -> int:
    cfg = Config.default()
    cfg.allocator.min_obs = 3
    cfg.allocator.rebalance_minutes = 1
    bots = [
        ORBBot("orb", ["AAA", "BBB"], opening_minutes=5, atr_period=5),
        VWAPReversionBot("vwap", ["AAA", "BBB"], bb_period=10),
        DormantBot("general", "MES/MNQ futures (Phase F)"),
    ]
    result = asyncio.run(run_backtest(cfg, _demo_source(), bots))
    m = metrics(result, periods_per_year=252 * 390)
    print("Backtest complete.")
    print(f"  bars: {len(result.equity_curve)}  fills: {len(result.fills)}")
    print(f"  sharpe: {m['sharpe']:.3f}  max_drawdown: {m['max_drawdown']:.4f}")
    print(f"  hit_rate: {m['hit_rate']:.3f}  turnover: {m['turnover']:.3f}")
    print(f"  final weights: {result.weights_history[-1] if result.weights_history else {}}")
    return 0


def cmd_status(args) -> int:
    async def _run() -> int:
        store = StateStore(args.db)
        await store.init()
        rows = await store.load_fills()
        n_alloc = await store.count("allocations")
        print(f"Status for {args.db}")
        print(f"  fills recorded: {len(rows)}")
        print(f"  allocation decisions: {n_alloc}")
        async with store.db.execute(
            "SELECT bot_id, weight, aggressiveness FROM allocations ORDER BY ts DESC LIMIT 8"
        ) as cur:
            for r in await cur.fetchall():
                print(f"  bot={r['bot_id']:>8}  weight={r['weight']:.3f}  aggr={r['aggressiveness']:.2f}")
        await store.close()
        return 0

    return asyncio.run(_run())


def cmd_paper(args) -> int:
    if not (os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY")):
        print("paper trading needs ALPACA_API_KEY and ALPACA_SECRET_KEY env vars.")
        return 2
    print("paper trading wiring is available; connect AlpacaBroker/AlpacaFeed here.")
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="traderbot")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backtest").set_defaults(func=cmd_backtest)
    p_status = sub.add_parser("status")
    p_status.add_argument("--db", default="traderbot.sqlite")
    p_status.set_defaults(func=cmd_status)
    sub.add_parser("paper").set_defaults(func=cmd_paper)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
