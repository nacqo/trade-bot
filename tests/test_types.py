from datetime import datetime, timezone

from traderbot.types import Bar, Fill, OrderIntent, Position, Side


def _ts():
    return datetime(2026, 6, 20, 14, 0, tzinfo=timezone.utc)


def test_position_signed_and_market_value():
    p = Position(symbol="AAPL", qty=-10, avg_price=100.0)
    assert p.is_short
    assert not p.is_long
    assert p.market_value(105.0) == -1050.0


def test_long_position():
    p = Position(symbol="AAPL", qty=10, avg_price=100.0)
    assert p.is_long
    assert p.market_value(105.0) == 1050.0


def test_side_from_signed_qty():
    assert Side.from_qty(5) is Side.BUY
    assert Side.from_qty(-5) is Side.SELL


def test_bar_and_fill_are_frozen():
    b = Bar(symbol="AAPL", ts=_ts(), open=1, high=2, low=0.5, close=1.5, volume=1000)
    assert b.close == 1.5
    f = Fill(bot_id="b1", symbol="AAPL", qty=5, price=100.0, ts=_ts())
    assert f.qty == 5


def test_order_intent_defaults_exit_plan_none():
    o = OrderIntent(bot_id="b1", symbol="AAPL", target_qty=10, stop_price=99.0)
    assert o.exit_plan is None
