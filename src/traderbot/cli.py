"""Command-line entry points: `traderbot status | backtest | paper`."""

from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime, timedelta, timezone

import structlog

from traderbot.backtest.metrics import metrics
from traderbot.backtest.runner import run_backtest
from traderbot.backtest.validation import oos_report
from traderbot.config import Config
from traderbot.market_data.source import ReplaySource
from traderbot.state.store import StateStore
from traderbot.strategies.dormant import DormantBot
from traderbot.strategies.orb import ORBBot
from traderbot.strategies.stat_arb import StatArbBot
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


def _build_bots(symbols: list[str]) -> list:
    bots = [
        ORBBot("orb", symbols, opening_minutes=15),
        VWAPReversionBot("vwap", symbols, bb_period=20),
        DormantBot("general", "MES/MNQ futures (Phase F)"),
    ]
    if len(symbols) >= 2:
        bots.insert(0, StatArbBot("statarb", [(symbols[0], symbols[1])], lookback=60))
    return bots


def cmd_backtest(args) -> int:
    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if args.symbols and key and secret:
        from datetime import datetime as _dt

        from traderbot.integrations.alpaca import build_historical_source

        symbols = [s.strip().upper() for s in args.symbols.split(",")]
        source = build_historical_source(
            key, secret, symbols, _dt.fromisoformat(args.start), _dt.fromisoformat(args.end),
            feed=args.feed,
        )
        cfg = Config.default()
        bots = _build_bots(symbols)
        print(f"Real Alpaca backtest: {symbols}  {args.start}..{args.end}  feed={args.feed}")
    else:
        cfg = Config.default()
        cfg.allocator.min_obs = 3
        cfg.allocator.rebalance_minutes = 1
        source = _demo_source()
        bots = [
            ORBBot("orb", ["AAA", "BBB"], opening_minutes=5, atr_period=5),
            VWAPReversionBot("vwap", ["AAA", "BBB"], bb_period=10),
            DormantBot("general", "MES/MNQ futures (Phase F)"),
        ]
        print("Synthetic demo backtest (pass --symbols + ALPACA creds for real data).")

    result = asyncio.run(run_backtest(cfg, source, bots))
    m = metrics(result, periods_per_year=252 * 390)
    print("Backtest complete.")
    print(f"  bars: {len(result.equity_curve)}  fills: {len(result.fills)}")
    print(f"  sharpe: {m['sharpe']:.3f}  max_drawdown: {m['max_drawdown']:.4f}")
    print(f"  hit_rate: {m['hit_rate']:.3f}  turnover: {m['turnover']:.3f}")
    oos = oos_report(result, cfg.starting_equity, train_frac=0.5, windows=4)
    print(f"  OOS sharpe — allocator: {oos['oos_sharpe_allocator']:.3f}  "
          f"equal-weight: {oos['oos_sharpe_equal_weight']:.3f}")
    print(f"  allocator beats equal-weight OOS: {oos['allocator_beats_equal_weight_oos']}  "
          f"(won {oos['windows_allocator_won']}/{oos['windows_total']} windows)")
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
    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if not (key and secret):
        print("paper trading needs ALPACA_API_KEY and ALPACA_SECRET_KEY env vars.")
        return 2
    from traderbot.integrations.alpaca import build_alpaca_broker

    broker = build_alpaca_broker(key, secret, paper=True)
    print("Connected to Alpaca paper.")
    print(f"  equity: {broker.equity():.2f}  buying_power: {broker.buying_power():.2f}")
    print(f"  positions: {broker.positions()}")
    if args.symbols:
        from traderbot.integrations.alpaca import build_live_source
        from traderbot.live import run_paper

        symbols = [s.strip().upper() for s in args.symbols.split(",")]
        source = build_live_source(key, secret, symbols)
        bots = _build_bots(symbols)
        print(f"Starting live paper loop on {symbols} (Ctrl-C to stop)...")
        asyncio.run(run_paper(Config.default(), broker, source, bots))
    else:
        print("NOTE: pass --symbols A,B to start the live streaming loop; this confirmed connectivity.")
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="traderbot")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_bt = sub.add_parser("backtest")
    p_bt.add_argument("--symbols", default=None, help="comma-separated, e.g. AAPL,MSFT")
    p_bt.add_argument("--start", default="2026-01-02", help="ISO date/datetime")
    p_bt.add_argument("--end", default="2026-01-09", help="ISO date/datetime")
    p_bt.add_argument("--feed", default="iex", choices=["iex", "sip"])
    p_bt.set_defaults(func=cmd_backtest)
    p_status = sub.add_parser("status")
    p_status.add_argument("--db", default="traderbot.sqlite")
    p_status.set_defaults(func=cmd_status)
    p_paper = sub.add_parser("paper")
    p_paper.add_argument("--symbols", default=None, help="comma-separated; starts the live loop")
    p_paper.set_defaults(func=cmd_paper)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
