from datetime import datetime, timedelta, timezone

from traderbot.config import Config
from traderbot.engine.engine import Engine
from traderbot.execution.broker import FakeBroker
from traderbot.risk.risk_manager import RiskManager
from traderbot.state.store import StateStore
from traderbot.strategies.fixed_target import FixedTargetBot
from traderbot.types import Bar

from tests.helpers import ListSource

T0 = datetime(2026, 6, 20, 13, 30, tzinfo=timezone.utc)


def _bar(symbol, m, price):
    return Bar(symbol, T0 + timedelta(minutes=m), price, price, price, price, 1_000_000)


async def test_portfolio_drawdown_halts_and_flattens(tmp_path):
    cfg = Config.default()  # total_dd_halt = 0.05
    store = StateStore(str(tmp_path / "s.db"))
    await store.init()
    bot = FixedTargetBot("A", "AAA", qty=100, stop_price=1.0)
    broker = FakeBroker(100_000.0)
    rm = RiskManager(cfg.risk)
    # buy 100 @100 ($10k), then price collapses to 40 → equity −6% → halt
    engine = Engine(cfg, ListSource([_bar("AAA", 0, 100), _bar("AAA", 1, 90), _bar("AAA", 2, 40)]),
                    [bot], broker, store, risk_manager=rm)

    await engine.run()

    assert rm.halted
    assert broker.positions() == {}  # flattened on halt
    assert await store.count("risk_events") >= 1
    await store.close()


async def test_per_bot_drawdown_suspends_only_that_bot(tmp_path):
    cfg = Config.default()  # per_bot_dd_kill 0.02 → $2k budget; total_dd_halt 0.05
    store = StateStore(str(tmp_path / "s.db"))
    await store.init()
    bots = [FixedTargetBot("A", "AAA", 100, 1.0), FixedTargetBot("B", "BBB", 100, 1.0)]
    broker = FakeBroker(100_000.0)
    rm = RiskManager(cfg.risk)
    # both enter; then AAA crashes 100→70 (A loses $3k > budget; portfolio only −3% → no halt)
    events = [_bar("AAA", 0, 100), _bar("BBB", 0, 100), _bar("AAA", 1, 70), _bar("BBB", 1, 100)]
    engine = Engine(cfg, ListSource(events), bots, broker, store, risk_manager=rm)

    await engine.run()

    assert "A" in engine._suspended
    assert not rm.halted
    assert "AAA" not in broker.positions()  # A flattened
    assert "BBB" in broker.positions()      # B untouched
    await store.close()
