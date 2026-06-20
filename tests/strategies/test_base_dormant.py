from traderbot.strategies.base import BotOutput, Strategy, TargetPosition
from traderbot.strategies.dormant import DormantBot


def test_dormant_bot_is_disabled_and_emits_nothing():
    bot = DormantBot("bot5", instrument_note="MES/MNQ micro futures (Phase F)")
    assert bot.enabled is False
    out = bot.evaluate()
    assert isinstance(out, BotOutput)
    assert out.enabled is False
    assert out.targets == []
    assert out.signal_strength == 0.0


def test_target_position_carries_stop():
    t = TargetPosition(symbol="AAPL", qty=10, stop_price=99.0)
    assert t.stop_price == 99.0


def test_strategy_is_abstract():
    import pytest

    with pytest.raises(TypeError):
        Strategy("x")  # abstract evaluate()
