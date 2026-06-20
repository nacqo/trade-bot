from datetime import datetime, timedelta, timezone

from traderbot.strategies.orb import ORBBot
from traderbot.types import Bar

T0 = datetime(2026, 6, 20, 13, 30, tzinfo=timezone.utc)


def _bar(symbol, m, o, h, low, c):
    return Bar(symbol, T0 + timedelta(minutes=m), o, h, low, c, 5000)


def _feed(bot, bars):
    for b in bars:
        bot.on_bar(b)


def test_breakout_long_with_stop_at_or_low():
    bot = ORBBot("orb", ["AAPL"], opening_minutes=3, atr_period=3)
    # opening range -> high 101, low 100
    _feed(bot, [
        _bar("AAPL", 0, 100, 101, 100, 100.5),
        _bar("AAPL", 1, 100.5, 101, 100, 100.5),
        _bar("AAPL", 2, 100, 101, 100, 100.5),
        _bar("AAPL", 3, 101, 102, 101, 102),  # breakout up
    ])
    out = bot.evaluate()
    assert len(out.targets) == 1
    t = out.targets[0]
    assert t.qty > 0
    assert t.stop_price == 100  # OR low
    assert out.signal_strength > 0


def test_no_breakout_no_target():
    bot = ORBBot("orb", ["AAPL"], opening_minutes=3, atr_period=3)
    _feed(bot, [
        _bar("AAPL", 0, 100, 101, 100, 100.5),
        _bar("AAPL", 1, 100.5, 101, 100, 100.5),
        _bar("AAPL", 2, 100, 101, 100, 100.5),
        _bar("AAPL", 3, 100.5, 100.9, 100.2, 100.6),  # inside range
    ])
    assert bot.evaluate().targets == []


def test_breakout_short():
    bot = ORBBot("orb", ["AAPL"], opening_minutes=3, atr_period=3)
    _feed(bot, [
        _bar("AAPL", 0, 100, 101, 100, 100.5),
        _bar("AAPL", 1, 100.5, 101, 100, 100.5),
        _bar("AAPL", 2, 100, 101, 100, 100.5),
        _bar("AAPL", 3, 100, 100, 98, 98),  # breakdown
    ])
    t = bot.evaluate().targets[0]
    assert t.qty < 0
    assert t.stop_price == 101  # OR high
