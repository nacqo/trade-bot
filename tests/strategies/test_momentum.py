from datetime import datetime, timedelta, timezone

from traderbot.strategies.momentum import CrossSectionalMomentumBot
from traderbot.types import Bar

T0 = datetime(2026, 1, 2, tzinfo=timezone.utc)


def test_longs_winners_shorts_losers():
    syms = [f"S{i}" for i in range(12)]
    bot = CrossSectionalMomentumBot("mom", syms, lookback=20, skip=2, quantile=0.2, vol_scale=False)
    for t in range(25):
        for i, s in enumerate(syms):
            price = 100 + (i - 6) * 0.5 * t  # slope rises with i → momentum ordered by i
            bot.on_bar(Bar(s, T0 + timedelta(days=t), price, price, price, price, 1000))

    out = bot.evaluate()
    qty = {tp.symbol: tp.qty for tp in out.targets}
    assert qty["S11"] > 0 and qty["S10"] > 0   # top momentum → long
    assert qty["S0"] < 0 and qty["S1"] < 0     # bottom momentum → short
    assert qty.get("S6", 0.0) == 0.0           # middle → flat (rotated out)
    # every non-flat target carries a stop
    for tp in out.targets:
        if tp.qty != 0:
            assert tp.stop_price is not None


def test_insufficient_history_no_targets():
    bot = CrossSectionalMomentumBot("mom", ["A", "B"], lookback=20)
    bot.on_bar(Bar("A", T0, 100, 100, 100, 100, 1000))
    assert bot.evaluate().targets == []
