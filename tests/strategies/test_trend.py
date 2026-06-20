from datetime import datetime, timedelta, timezone

from traderbot.strategies.trend import TimeSeriesMomentumBot
from traderbot.types import Bar

T0 = datetime(2026, 1, 2, tzinfo=timezone.utc)


def _feed(bot, prices_by_symbol):
    n = len(next(iter(prices_by_symbol.values())))
    for t in range(n):
        for s, prices in prices_by_symbol.items():
            bot.on_bar(Bar(s, T0 + timedelta(days=t), prices[t], prices[t], prices[t], prices[t], 1000))


def test_long_uptrend_short_downtrend_with_stops():
    bot = TimeSeriesMomentumBot("trend", ["UP", "DN"], lookback=20, vol_lookback=10, stop_frac=0.2)
    _feed(bot, {
        "UP": [100 + t for t in range(25)],   # uptrend
        "DN": [100 - t for t in range(25)],   # downtrend
    })
    out = bot.evaluate()
    q = {t.symbol: t for t in out.targets}
    assert q["UP"].qty > 0 and q["DN"].qty < 0
    assert q["UP"].stop_price < q["UP"].qty * 0 + 124  # stop below the up-name's last price (124)
    assert q["DN"].stop_price > 76                      # stop above the down-name's last price (76)


def test_insufficient_history_skips():
    bot = TimeSeriesMomentumBot("trend", ["A"], lookback=20)
    bot.on_bar(Bar("A", T0, 100, 100, 100, 100, 1000))
    assert bot.evaluate().targets == []
