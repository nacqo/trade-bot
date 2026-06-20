from datetime import datetime, timedelta, timezone

from traderbot.strategies.vwap_reversion import VWAPReversionBot
from traderbot.types import Bar

T0 = datetime(2026, 6, 20, 13, 30, tzinfo=timezone.utc)


def _bar(m, price):
    return Bar("AAPL", T0 + timedelta(minutes=m), price, price, price, price, 1000)


def _feed(bot, prices):
    for m, p in enumerate(prices):
        bot.on_bar(_bar(m, p))


def test_overextended_above_band_goes_short_with_stop_above_entry():
    bot = VWAPReversionBot("vwap", ["AAPL"], bb_period=5, bb_sigma=2.0)
    _feed(bot, [99, 100, 101, 100, 99, 104])  # history flat ~100, then spike to 104
    out = bot.evaluate()
    assert len(out.targets) == 1
    t = out.targets[0]
    assert t.qty < 0  # short the spike
    assert t.stop_price > 104  # stop above entry for a short
    assert out.signal_strength > 0


def test_within_band_no_target():
    bot = VWAPReversionBot("vwap", ["AAPL"], bb_period=5, bb_sigma=2.0)
    _feed(bot, [99, 100, 101, 100, 99, 100])  # last bar within band
    assert bot.evaluate().targets == []


def test_below_band_goes_long_with_stop_below_entry():
    bot = VWAPReversionBot("vwap", ["AAPL"], bb_period=5, bb_sigma=2.0)
    _feed(bot, [101, 100, 99, 100, 101, 96])  # spike down to 96
    t = bot.evaluate().targets[0]
    assert t.qty > 0
    assert t.stop_price < 96
