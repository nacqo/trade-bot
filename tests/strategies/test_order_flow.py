from datetime import datetime, timedelta, timezone

from traderbot.strategies.order_flow import OrderFlowBot
from traderbot.types import Quote

T0 = datetime(2026, 6, 20, 13, 30, tzinfo=timezone.utc)


def _quote(symbol, s, bid, ask, bid_size, ask_size):
    return Quote(symbol, T0 + timedelta(seconds=s), bid, ask, bid_size, ask_size)


def test_buy_imbalance_goes_long_with_tight_stop():
    bot = OrderFlowBot("of", ["AAPL"], imb_threshold=0.3)
    for s in range(5):
        bot.on_quote(_quote("AAPL", s, 99.99, 100.01, bid_size=900, ask_size=100))  # imb +0.8
    out = bot.evaluate()
    assert len(out.targets) == 1
    t = out.targets[0]
    assert t.qty > 0
    assert t.stop_price < 100.0  # tight stop below mid
    assert out.signal_strength > 0


def test_sell_imbalance_goes_short():
    bot = OrderFlowBot("of", ["AAPL"], imb_threshold=0.3)
    for s in range(5):
        bot.on_quote(_quote("AAPL", s, 99.99, 100.01, bid_size=100, ask_size=900))  # imb −0.8
    t = bot.evaluate().targets[0]
    assert t.qty < 0
    assert t.stop_price > 100.0


def test_balanced_book_no_target():
    bot = OrderFlowBot("of", ["AAPL"], imb_threshold=0.3)
    for s in range(5):
        bot.on_quote(_quote("AAPL", s, 99.99, 100.01, bid_size=500, ask_size=500))  # imb 0
    assert bot.evaluate().targets == []
