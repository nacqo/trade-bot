from hypothesis import given, settings
from hypothesis import strategies as st

from traderbot.config import RiskCfg
from traderbot.risk.risk_manager import RiskManager
from traderbot.types import OrderIntent, Position


def test_rejects_order_without_stop():
    rm = RiskManager(RiskCfg())
    d = rm.check_order(
        OrderIntent("b1", "AAPL", 10, stop_price=None),
        equity=100_000, positions={}, buying_power=100_000, open_risk=0, price=100.0,
    )
    assert not d.approved and "stop" in d.reason.lower()


def test_flat_order_always_allowed():
    rm = RiskManager(RiskCfg())
    d = rm.check_order(
        OrderIntent("b1", "AAPL", 0, stop_price=None),
        equity=100_000, positions={}, buying_power=0.0, open_risk=1e9, price=100.0,
    )
    assert d.approved  # reducing/closing is always allowed


def test_rejects_when_buying_power_exhausted():
    rm = RiskManager(RiskCfg())
    d = rm.check_order(
        OrderIntent("b1", "AAPL", 1000, stop_price=99.0),
        equity=100_000, positions={}, buying_power=0.0, open_risk=0, price=100.0,
    )
    assert not d.approved


def test_blocks_when_heat_would_exceed_cap():
    rm = RiskManager(RiskCfg())  # max_total_open_risk_frac=0.10 → $10k cap
    d = rm.check_order(
        OrderIntent("b1", "AAPL", 6000, stop_price=98.0),  # risk = 2*6000 = $12k
        equity=100_000, positions={}, buying_power=1e9, open_risk=0, price=100.0,
    )
    assert not d.approved and "risk" in d.reason.lower()


def test_solvency_invariant_ceiling():
    rm = RiskManager(RiskCfg(max_total_open_risk_frac=0.9, maintenance_buffer_frac=0.25))
    # cap must be min(0.9, 1-0.25) = 0.75 of equity
    assert rm.effective_open_risk_cap(100_000) == 75_000


def test_total_open_risk_and_gross_net():
    rm = RiskManager(RiskCfg())
    positions = {"AAPL": Position("AAPL", 10, 100.0), "MSFT": Position("MSFT", -5, 200.0)}
    stops = {"AAPL": 98.0, "MSFT": 205.0}
    assert rm.total_open_risk(positions, stops) == 10 * 2 + 5 * 5  # 20 + 25
    prices = {"AAPL": 100.0, "MSFT": 200.0}
    assert rm.gross(positions, prices) == 1000 + 1000
    assert rm.net(positions, prices) == 1000 - 1000


def test_degross_factor_halts_on_drawdown():
    rm = RiskManager(RiskCfg(total_dd_halt=0.05))
    assert rm.degross_factor(margin_util=0.0, drawdown=0.05) == 0.0
    assert rm.degross_factor(margin_util=0.0, drawdown=0.0) == 1.0


@settings(max_examples=300)
@given(
    equity=st.floats(min_value=1e4, max_value=1e6),
    qty=st.floats(min_value=-1e4, max_value=1e4),
    price=st.floats(min_value=1.0, max_value=500.0),
    stop_off=st.floats(min_value=0.1, max_value=20.0),
    open_risk=st.floats(min_value=0.0, max_value=2e5),
    buying_power=st.floats(min_value=0.0, max_value=1e7),
)
def test_property_approved_orders_respect_caps(equity, qty, price, stop_off, open_risk, buying_power):
    rm = RiskManager(RiskCfg())
    stop = price - stop_off if qty >= 0 else price + stop_off
    d = rm.check_order(
        OrderIntent("b1", "AAPL", qty, stop_price=stop),
        equity=equity, positions={}, buying_power=buying_power, open_risk=open_risk, price=price,
    )
    if d.approved and qty != 0:
        new_risk = abs(qty) * abs(price - stop)
        assert open_risk + new_risk <= rm.effective_open_risk_cap(equity) + 1e-6
        assert abs(qty) * price <= buying_power + 1e-6
