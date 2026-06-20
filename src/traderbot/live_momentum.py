"""Live momentum rebalance — a once-per-day rebalance for the daily momentum factor.

Momentum is a daily factor, so it doesn't belong on the minute-streaming loop. Instead: warm the
bot on recent daily history, compute target positions, diff against the broker's real positions,
and submit only the deltas. Run this once per trading day (cron or a daily loop).
"""

from __future__ import annotations

from traderbot.strategies.momentum import CrossSectionalMomentumBot
from traderbot.types import Bar, OrderIntent


def momentum_rebalance(broker, bot: CrossSectionalMomentumBot, history: list[Bar], *,
                       deploy_fraction: float = 1.0, max_gross_leverage: float = 1.5) -> list[tuple]:
    """Warm `bot` on `history` (ts-ordered), size targets to the account, submit position deltas."""
    last_close: dict[str, float] = {}
    for bar in history:
        bot.on_bar(bar)
        last_close[bar.symbol] = bar.close

    out = bot.evaluate()
    equity = broker.equity()
    deployable = equity * deploy_fraction
    desired_gross = sum(
        abs(t.qty * last_close[t.symbol]) for t in out.targets
        if t.qty != 0 and t.symbol in last_close
    )
    if desired_gross <= 0:
        return []
    scale = deployable / desired_gross
    # clamp so real gross can't exceed the leverage cap
    scale = min(scale, equity * max_gross_leverage / desired_gross)

    positions = broker.positions()
    submitted: list[tuple] = []
    for t in out.targets:
        if t.symbol not in last_close:
            continue
        target_qty = round(t.qty * scale)
        current = positions[t.symbol].qty if t.symbol in positions else 0.0
        delta = target_qty - current
        if abs(delta) >= 1:
            broker.submit(OrderIntent("momentum", t.symbol, delta, t.stop_price))
            submitted.append((t.symbol, delta))
    return submitted
