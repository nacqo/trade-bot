from traderbot.strategies.base import Strategy, TargetPosition


def test_target_position_carries_stop():
    t = TargetPosition(symbol="AAPL", qty=10, stop_price=99.0)
    assert t.stop_price == 99.0


def test_strategy_is_abstract():
    import pytest

    with pytest.raises(TypeError):
        Strategy("x")  # abstract evaluate()
