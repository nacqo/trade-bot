from datetime import datetime, timedelta, timezone

from traderbot.execution.broker import FakeBroker
from traderbot.live_momentum import momentum_rebalance
from traderbot.strategies.momentum import CrossSectionalMomentumBot
from traderbot.types import Bar

T0 = datetime(2026, 1, 2, tzinfo=timezone.utc)


def test_rebalance_longs_winners_shorts_losers_within_leverage():
    syms = [f"S{i}" for i in range(12)]
    broker = FakeBroker(100_000.0)
    history = []
    for t in range(25):
        for i, s in enumerate(syms):
            price = 100 + (i - 6) * 0.5 * t
            broker.set_mark(s, price)
            history.append(Bar(s, T0 + timedelta(days=t), price, price, price, price, 1000))
    history.sort(key=lambda b: b.ts)
    bot = CrossSectionalMomentumBot("mom", syms, lookback=20, skip=2, quantile=0.2, vol_scale=False)

    submitted = momentum_rebalance(broker, bot, history)
    d = dict(submitted)
    assert d.get("S11", 0) > 0    # long the winner
    assert d.get("S0", 0) < 0     # short the loser
    assert broker.gross() <= 1.5 * broker.equity() + 1.0  # within leverage cap


def test_rebalance_noop_without_history():
    broker = FakeBroker(100_000.0)
    bot = CrossSectionalMomentumBot("mom", ["A", "B"], lookback=20)
    assert momentum_rebalance(broker, bot, []) == []
