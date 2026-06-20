from datetime import datetime, timedelta, timezone

import numpy as np

from traderbot.strategies.stat_arb import StatArbBot
from traderbot.types import Bar

T0 = datetime(2026, 6, 20, 13, 30, tzinfo=timezone.utc)


def _bar(symbol, m, price):
    return Bar(symbol, T0 + timedelta(minutes=m), price, price, price, price, 1000)


def _feed_pairs(bot, a_prices, b_prices):
    for m, (a, b) in enumerate(zip(a_prices, b_prices)):
        bot.on_bar(_bar("AAA", m, a))
        bot.on_bar(_bar("BBB", m, b))


def test_wide_spread_opens_market_neutral_legs():
    # z_stop high so we isolate the entry branch (not the cointegration-break flat branch)
    bot = StatArbBot("sa", [("AAA", "BBB")], z_in=2.0, z_stop=100.0, lookback=20)
    bot._refit_cointegration = lambda: None  # isolate z-logic from the cointegration gate
    bot._tradable[("AAA", "BBB")] = True
    b = [100 + (i % 5) for i in range(21)]            # ramped → β ≈ 1, low corr with spread
    a = [b[i] + (0.1 if i % 2 == 0 else -0.1) for i in range(20)]  # spread ±0.1
    a.append(b[20] + 1.0)                              # final spread spikes → |z| ≥ z_in
    _feed_pairs(bot, a, b)

    out = bot.evaluate()
    syms = {t.symbol: t for t in out.targets}
    assert "AAA" in syms and "BBB" in syms
    assert syms["AAA"].qty < 0          # short the rich leg
    assert syms["BBB"].qty > 0          # long the cheap leg
    assert syms["AAA"].stop_price > a[-1]  # stop above entry for the short
    assert out.signal_strength > 0


def test_cointegration_gate_blocks_independent_pairs():
    rng = np.random.default_rng(0)
    a = np.cumsum(rng.normal(size=200)) + 100      # base random walk
    b = a + rng.normal(size=200) * 0.5             # cointegrated with a
    c = np.cumsum(rng.normal(size=200)) + 100      # independent random walk
    bot = StatArbBot("sa", [("CA", "CB"), ("IA", "IB")], lookback=200, refit_every=1)
    for m in range(200):
        for sym, val in [("CA", a[m]), ("CB", b[m]), ("IA", a[m]), ("IB", c[m])]:
            bot.on_bar(Bar(sym, T0 + timedelta(minutes=m), val, val, val, val, 1000))
    bot.evaluate()  # triggers cointegration refit
    assert bot._tradable[("CA", "CB")] is True      # cointegrated → tradable
    assert bot._tradable[("IA", "IB")] is False     # independent → gated out


def test_tight_spread_flat():
    bot = StatArbBot("sa", [("AAA", "BBB")], z_in=2.0, z_out=0.5, lookback=20)
    bot._refit_cointegration = lambda: None  # isolate z-logic from the cointegration gate
    bot._tradable[("AAA", "BBB")] = True
    b = [100 + (i % 2) for i in range(21)]
    a = [b[i] + (0.1 if i % 2 == 0 else -0.1) for i in range(21)]  # spread stays small → |z| small
    _feed_pairs(bot, a, b)
    out = bot.evaluate()
    # within z_out band → flat targets (qty 0)
    assert all(t.qty == 0 for t in out.targets)
