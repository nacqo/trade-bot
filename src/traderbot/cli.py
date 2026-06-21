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
from traderbot.strategies.orb import ORBBot
from traderbot.types import Bar


def configure_logging() -> None:
    structlog.configure(processors=[structlog.processors.add_log_level, structlog.dev.ConsoleRenderer()])


def load_dotenv(path: str = ".env") -> None:
    """Load KEY=VALUE lines from a local .env into the environment (no override, no dependency)."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


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
    return [ORBBot("orb", symbols, opening_minutes=15)]


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
        bots = [ORBBot("orb", ["AAA", "BBB"], opening_minutes=5, atr_period=5)]
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


MOMENTUM_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "BAC", "WFC",
    "XOM", "CVX", "COP", "KO", "PEP", "PG", "WMT", "HD", "MCD", "DIS",
    "NKE", "V", "MA", "UNH", "JNJ", "PFE", "MRK", "CSCO", "INTC", "AMD",
    "QCOM", "CRM", "ORCL", "IBM", "T", "VZ", "CMCSA", "COST", "TGT", "LOW",
    "CAT", "BA", "GE", "HON",
]


def cmd_momentum(args) -> int:
    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if not (key and secret):
        print("momentum needs ALPACA_API_KEY and ALPACA_SECRET_KEY env vars.")
        return 2
    from datetime import datetime, timedelta, timezone

    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.timeframe import TimeFrame

    from traderbot.integrations.alpaca import build_alpaca_broker, fetch_historical_bars
    from traderbot.live_momentum import momentum_rebalance
    from traderbot.strategies.momentum import CrossSectionalMomentumBot

    universe = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else MOMENTUM_UNIVERSE
    broker = build_alpaca_broker(key, secret, paper=True)
    client = StockHistoricalDataClient(key, secret)
    end = datetime.now(timezone.utc)
    bars = fetch_historical_bars(client, universe, end - timedelta(days=420), end, timeframe=TimeFrame.Day)
    history = sorted((b for bl in bars.values() for b in bl), key=lambda b: b.ts)
    bot = CrossSectionalMomentumBot("momentum", universe)

    submitted = momentum_rebalance(broker, bot, history)
    print(f"Momentum daily rebalance: {len(submitted)} orders submitted to Alpaca paper.")
    for sym, delta in submitted:
        print(f"  {sym}: {delta:+.0f}")
    print("Run this once per trading day (e.g. via cron after the close).")
    return 0


def cmd_core(args) -> int:
    import asyncio as _asyncio

    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if not (key and secret):
        print("core needs ALPACA_API_KEY and ALPACA_SECRET_KEY env vars.")
        return 2
    from datetime import datetime, timedelta, timezone

    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.timeframe import TimeFrame

    from traderbot.core import CORE_EQUITIES, CORE_ETFS, core_rebalance
    from traderbot.integrations.alpaca import build_alpaca_broker, fetch_historical_bars

    broker = build_alpaca_broker(key, secret, paper=True)
    client = StockHistoricalDataClient(key, secret)
    end = datetime.now(timezone.utc)
    bars = fetch_historical_bars(client, CORE_EQUITIES + CORE_ETFS, end - timedelta(days=450),
                                 end, timeframe=TimeFrame.Day)
    history = sorted((b for bl in bars.values() for b in bl), key=lambda b: b.ts)
    submitted = _asyncio.run(core_rebalance(broker, history, broker.equity()))
    print(f"Blended CORE rebalance (momentum + residmom + trend): {len(submitted)} orders to paper.")
    for sym, delta in submitted:
        print(f"  {sym}: {delta:+.0f}")
    print("Run once per trading day (cron after the close). This is the blended live core.")
    return 0


def cmd_residmom(args) -> int:
    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if not (key and secret):
        print("residmom needs ALPACA_API_KEY and ALPACA_SECRET_KEY env vars.")
        return 2
    from datetime import datetime, timedelta, timezone

    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.timeframe import TimeFrame

    from traderbot.integrations.alpaca import build_alpaca_broker, fetch_historical_bars
    from traderbot.live_momentum import momentum_rebalance
    from traderbot.strategies.residual_momentum import ResidualMomentumBot

    universe = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else MOMENTUM_UNIVERSE
    broker = build_alpaca_broker(key, secret, paper=True)
    client = StockHistoricalDataClient(key, secret)
    end = datetime.now(timezone.utc)
    bars = fetch_historical_bars(client, universe, end - timedelta(days=420), end, timeframe=TimeFrame.Day)
    history = sorted((b for bl in bars.values() for b in bl), key=lambda b: b.ts)
    bot = ResidualMomentumBot("residmom", universe)

    submitted = momentum_rebalance(broker, bot, history)
    print(f"Residual-momentum daily rebalance: {len(submitted)} orders to Alpaca paper.")
    for sym, delta in submitted:
        print(f"  {sym}: {delta:+.0f}")
    print("Run once per trading day (cron after the close).")
    return 0


TREND_UNIVERSE = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "LQD", "HYG", "GLD",
                  "SLV", "DBC", "USO", "VNQ", "UUP", "XLE", "XLK", "XLF"]


def cmd_trend(args) -> int:
    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if not (key and secret):
        print("trend needs ALPACA_API_KEY and ALPACA_SECRET_KEY env vars.")
        return 2
    from datetime import datetime, timedelta, timezone

    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.timeframe import TimeFrame

    from traderbot.integrations.alpaca import build_alpaca_broker, fetch_historical_bars
    from traderbot.live_momentum import momentum_rebalance
    from traderbot.strategies.trend import TimeSeriesMomentumBot

    universe = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else TREND_UNIVERSE
    broker = build_alpaca_broker(key, secret, paper=True)
    client = StockHistoricalDataClient(key, secret)
    end = datetime.now(timezone.utc)
    bars = fetch_historical_bars(client, universe, end - timedelta(days=450), end, timeframe=TimeFrame.Day)
    history = sorted((b for bl in bars.values() for b in bl), key=lambda b: b.ts)
    bot = TimeSeriesMomentumBot("trend", universe)

    submitted = momentum_rebalance(broker, bot, history)
    print(f"Trend (time-series momentum) daily rebalance: {len(submitted)} orders to Alpaca paper.")
    for sym, delta in submitted:
        print(f"  {sym}: {delta:+.0f}")
    print("Run once per trading day (cron after the close).")
    return 0


def cmd_cancel(args) -> int:
    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if not (key and secret):
        print("cancel needs ALPACA_API_KEY and ALPACA_SECRET_KEY env vars.")
        return 2
    from traderbot.integrations.alpaca import build_alpaca_broker

    broker = build_alpaca_broker(key, secret, paper=True)
    broker.cancel_all_orders()
    print("Cancelled all open orders on the Alpaca paper account.")
    pos = broker.positions()
    print(f"open positions now: {pos if pos else 'none'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    load_dotenv()
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
    p_mom = sub.add_parser("momentum")
    p_mom.add_argument("--symbols", default=None, help="comma-separated universe (default: 44 large-caps)")
    p_mom.set_defaults(func=cmd_momentum)
    p_rm = sub.add_parser("residmom")
    p_rm.add_argument("--symbols", default=None, help="comma-separated universe (default: 44 large-caps)")
    p_rm.set_defaults(func=cmd_residmom)
    p_trend = sub.add_parser("trend")
    p_trend.add_argument("--symbols", default=None, help="comma-separated ETF/asset universe")
    p_trend.set_defaults(func=cmd_trend)
    sub.add_parser("core").set_defaults(func=cmd_core)
    sub.add_parser("cancel").set_defaults(func=cmd_cancel)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
