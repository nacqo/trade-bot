from datetime import datetime, timedelta, timezone

from traderbot.strategies.residual_momentum import ResidualMomentumBot
from traderbot.types import Bar

T0 = datetime(2026, 1, 2, tzinfo=timezone.utc)


def test_longs_high_idiosyncratic_momentum():
    syms = [f"S{i}" for i in range(12)]
    bot = ResidualMomentumBot("rm", syms, lookback=20, skip=2, quantile=0.2)
    for t in range(25):
        for i, s in enumerate(syms):
            common = 0.5 * t                       # shared market trend (stripped by residual)
            idio = (i - 6) * 0.3 * t                # name-specific drift → drives residual momentum
            price = 100 + common + idio
            bot.on_bar(Bar(s, T0 + timedelta(days=t), price, price, price, price, 1000))
    out = bot.evaluate()
    q = {t.symbol: t.qty for t in out.targets}
    assert q["S11"] > 0 and q["S10"] > 0   # strongest idiosyncratic up → long
    assert q["S0"] < 0 and q["S1"] < 0     # strongest idiosyncratic down → short
    for tp in out.targets:
        if tp.qty != 0:
            assert tp.stop_price is not None


def test_insufficient_history_skips():
    bot = ResidualMomentumBot("rm", ["A", "B"], lookback=20)
    bot.on_bar(Bar("A", T0, 100, 100, 100, 100, 1000))
    assert bot.evaluate().targets == []
