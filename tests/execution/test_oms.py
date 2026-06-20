from datetime import datetime, timezone

from traderbot.config import RiskCfg
from traderbot.execution.broker import FakeBroker
from traderbot.execution.fills import SimulatedFillModel
from traderbot.execution.oms import OMS
from traderbot.execution.virtual_book import VirtualBook
from traderbot.risk.risk_manager import RiskManager
from traderbot.strategies.base import TargetPosition
from traderbot.types import Bar

TS = datetime(2026, 6, 20, 14, 0, tzinfo=timezone.utc)


def _oms():
    fm = SimulatedFillModel(0.05, 1.0, True)
    broker = FakeBroker(100_000.0)
    broker.set_mark("AAPL", 100.0)
    return OMS(fm, RiskManager(RiskCfg()), broker), broker


async def test_nets_caps_attributes_and_queues_remainder():
    oms, broker = _oms()
    books = {"A": VirtualBook("A"), "B": VirtualBook("B")}
    targets = {
        "A": [TargetPosition("AAPL", 600, 99.0)],
        "B": [TargetPosition("AAPL", -100, 101.0)],
    }
    candle = Bar("AAPL", TS, 100.0, 100.0, 100.0, 100.0, 8000)  # cap = 400

    fills = await oms.execute(targets, candle, 100_000.0, books)

    assert broker.positions()["AAPL"].qty == 400          # net real fill capped at 5%
    assert books["A"].positions["AAPL"].qty == 480        # pro-rata of +600
    assert books["B"].positions["AAPL"].qty == -80        # pro-rata of -100
    assert len(fills) == 1
    assert oms.pending["AAPL"].qty == 100                 # remainder queued (500 ordered − 400)


class _HalfFillBroker:
    """Broker that fills exactly half of every requested order (simulates live partial fills)."""

    def submit(self, intent):
        from datetime import datetime, timezone

        from traderbot.types import Fill
        return Fill(intent.bot_id, intent.symbol, intent.target_qty / 2, 100.0,
                    datetime(2026, 6, 20, tzinfo=timezone.utc))

    def positions(self):
        return {}

    def equity(self):
        return 100_000.0

    def buying_power(self):
        return 1e9


async def test_partial_fill_attributes_actual_and_carries_shortfall():
    fm = SimulatedFillModel(0.05, 1.0, True)
    oms = OMS(fm, RiskManager(RiskCfg()), _HalfFillBroker())
    books = {"A": VirtualBook("A")}
    targets = {"A": [TargetPosition("AAPL", 400, 99.0)]}
    candle = Bar("AAPL", TS, 100.0, 100.0, 100.0, 100.0, 1_000_000)  # cap not binding

    await oms.execute(targets, candle, 100_000.0, books)

    assert books["A"].positions["AAPL"].qty == 200       # only the broker's actual (half) fill
    assert oms.pending["AAPL"].qty == 200                # unfilled half carried


async def test_buying_power_guard_blocks_unfundable_order():
    fm = SimulatedFillModel(0.05, 1.0, True)
    broker = FakeBroker(1_000.0)  # tiny account
    broker.set_mark("AAPL", 100.0)
    oms = OMS(fm, RiskManager(RiskCfg()), broker)
    books = {"A": VirtualBook("A")}
    targets = {"A": [TargetPosition("AAPL", 100000, 99.0)]}  # ~$10M notional
    candle = Bar("AAPL", TS, 100.0, 100.0, 100.0, 100.0, 10_000_000)

    fills = await oms.execute(targets, candle, 1_000.0, books)
    assert fills == []
    assert "AAPL" not in broker.positions()
