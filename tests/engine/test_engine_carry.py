"""Condition 2: carried entry remainders are re-validated in the engine loop — if the bots no
longer want the symbol, the leftover is cancelled instead of chased.
"""

from datetime import datetime, timedelta, timezone

from traderbot.config import Config, RiskCfg
from traderbot.engine.engine import Engine
from traderbot.execution.broker import FakeBroker
from traderbot.execution.fills import SimulatedFillModel
from traderbot.execution.oms import OMS
from traderbot.risk.risk_manager import RiskManager
from traderbot.state.store import StateStore
from traderbot.strategies.base import BotOutput, TargetPosition
from traderbot.types import Bar

from tests.helpers import ListSource, ScriptedBot

T0 = datetime(2026, 6, 20, 13, 30, tzinfo=timezone.utc)


async def test_carried_entry_cancelled_when_signal_gone(tmp_path):
    # bar0: want +1000 AAA but low volume (cap 5% of 2000 = 100) → 100 fills, 900 carries
    # bar1: bot now flat → carried entry re-validates False → remainder cancelled
    bot = ScriptedBot("S", [
        BotOutput([TargetPosition("AAA", 1000, stop_price=99.5)], 1.0),
        BotOutput([TargetPosition("AAA", 0, None)], 0.0),
    ])
    store = StateStore(str(tmp_path / "s.db"))
    await store.init()
    broker = FakeBroker(100_000.0)
    broker.set_mark("AAA", 100.0)
    oms = OMS(SimulatedFillModel(0.05, 1.0, True), RiskManager(RiskCfg()), broker)
    engine = Engine(Config.default(), ListSource([
        Bar("AAA", T0, 100, 100, 100, 100, 2000),
        Bar("AAA", T0 + timedelta(minutes=1), 100, 100, 100, 100, 2000),
    ]), [bot], broker, store, risk_manager=RiskManager(RiskCfg()), oms=oms)

    await engine.run()

    assert "AAA" not in oms.pending                       # leftover cancelled, not stuck
    assert engine.books["S"].positions["AAA"].qty == 100  # only the first capped fill, not 1000
    await store.close()
