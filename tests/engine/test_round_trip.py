from datetime import datetime, timezone

from traderbot.config import Config
from traderbot.engine.engine import Engine
from traderbot.execution.broker import FakeBroker
from traderbot.state.store import StateStore
from traderbot.strategies.fixed_target import FixedTargetBot
from traderbot.types import Bar

from tests.helpers import ListSource


def _bar(price):
    return Bar("AAPL", datetime(2026, 6, 20, 14, 0, tzinfo=timezone.utc),
               price, price, price, price, 1000)


async def test_engine_round_trip_fills_and_records(tmp_path):
    store = StateStore(str(tmp_path / "s.db"))
    await store.init()
    bot = FixedTargetBot("b1", "AAPL", qty=1)
    broker = FakeBroker(100_000.0)
    engine = Engine(Config.default(), ListSource([_bar(100.0)]), [bot], broker, store)

    await engine.step()

    assert broker.positions()["AAPL"].qty == 1
    fills = await store.load_fills()
    assert len(fills) == 1
    assert fills[0]["symbol"] == "AAPL" and fills[0]["qty"] == 1
    await store.close()


async def test_engine_only_trades_delta(tmp_path):
    store = StateStore(str(tmp_path / "s.db"))
    await store.init()
    bot = FixedTargetBot("b1", "AAPL", qty=1)
    broker = FakeBroker(100_000.0)
    engine = Engine(Config.default(), ListSource([_bar(100.0), _bar(101.0)]), [bot], broker, store)

    await engine.run()

    # second bar already at target → no new fill
    assert broker.positions()["AAPL"].qty == 1
    assert len(await store.load_fills()) == 1
    await store.close()
