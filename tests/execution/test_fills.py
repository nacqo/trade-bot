import math
from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from traderbot.execution.fills import CarryOrder, SimulatedFillModel
from traderbot.types import Bar

TS = datetime(2026, 6, 20, 14, 0, tzinfo=timezone.utc)


def _bar(volume, price=100.0):
    return Bar("AAPL", TS, price, price, price, price, volume)


def _model():
    return SimulatedFillModel(participation_cap=0.05, slippage_bps=1.0, revalidate_on_carry=True)


def test_fill_capped_at_participation():
    r = _model().fill(
        CarryOrder("b1", "AAPL", 1000, is_entry=True), _bar(8000), still_valid=lambda: True
    )
    assert r.filled_qty == 400  # 5% of 8000
    assert r.remainder == 600
    assert not r.cancelled


def test_iterative_carry_until_filled():
    m = _model()
    remaining, fills = 1000.0, []
    while remaining > 0:
        r = m.fill(CarryOrder("b1", "AAPL", remaining, is_entry=True), _bar(8000),
                   still_valid=lambda: True)
        fills.append(r.filled_qty)
        remaining = r.remainder
    assert fills == [400, 400, 200]


def test_revalidation_cancels_entry_remainder():
    r = _model().fill(
        CarryOrder("b1", "AAPL", 600, is_entry=True), _bar(8000), still_valid=lambda: False
    )
    assert r.cancelled and r.filled_qty == 0
    assert r.remainder == 600


def test_exit_remainder_not_cancelled_on_invalidation():
    r = _model().fill(
        CarryOrder("b1", "AAPL", 600, is_entry=False), _bar(8000), still_valid=lambda: False
    )
    assert not r.cancelled and r.filled_qty == 400


def test_buy_pays_up_sell_receives_down():
    m = _model()
    buy = m.fill(CarryOrder("b1", "AAPL", 100, True), _bar(1e9, 100.0), still_valid=lambda: True)
    sell = m.fill(CarryOrder("b1", "AAPL", -100, True), _bar(1e9, 100.0), still_valid=lambda: True)
    assert buy.price > 100.0 > sell.price


@settings(max_examples=300)
@given(
    volume=st.floats(min_value=0, max_value=1e7),
    remaining=st.integers(min_value=-100000, max_value=100000),
)
def test_property_fill_never_exceeds_cap(volume, remaining):
    m = _model()
    r = m.fill(CarryOrder("b1", "AAPL", float(remaining), is_entry=False),
               _bar(volume), still_valid=lambda: True)
    assert abs(r.filled_qty) <= math.floor(0.05 * volume)
    assert abs(r.filled_qty) <= abs(remaining)
