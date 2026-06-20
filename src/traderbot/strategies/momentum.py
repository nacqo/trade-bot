"""Cross-sectional momentum bot (validated signal — see docs/superpowers/BACKTEST_FINDINGS.md).

Ranks the universe by 12-1 momentum (price `skip` days ago / price `lookback` days ago − 1) and
goes long the top quantile, short the bottom quantile, dollar-neutral. Rotates names out as they
leave the deciles. Designed for DAILY bars (it's a daily-horizon factor, not intraday).

Risk requires a stop on every position; momentum is a slow portfolio factor, so stops are wide
(`stop_frac`, default 15%) — they bound tail risk without churning the factor.
"""

from __future__ import annotations

from collections import deque

import numpy as np

from traderbot.strategies.base import BotOutput, Strategy, TargetPosition
from traderbot.types import Bar


class CrossSectionalMomentumBot(Strategy):
    def __init__(
        self,
        id: str,
        symbols: list[str],
        lookback: int = 252,
        skip: int = 21,
        quantile: float = 0.2,
        unit: float = 1.0,
        stop_frac: float = 0.15,
        vol_scale: bool = True,
        vol_lookback: int = 126,
    ) -> None:
        super().__init__(id, symbols)
        self.lookback = lookback
        self.skip = skip
        self.quantile = quantile
        self.unit = unit
        self.stop_frac = stop_frac
        self.vol_scale = vol_scale
        self.vol_lookback = vol_lookback
        self._hist: dict[str, deque] = {s: deque(maxlen=lookback + 2) for s in symbols}

    def on_bar(self, bar: Bar) -> None:
        if bar.symbol in self._hist:
            self._hist[bar.symbol].append(bar.close)

    def evaluate(self) -> BotOutput:
        moms: dict[str, float] = {}
        last: dict[str, float] = {}
        for symbol, hist in self._hist.items():
            if len(hist) >= self.lookback + 1:
                h = list(hist)
                mom = h[-1 - self.skip] / h[-self.lookback] - 1.0
                if self.vol_scale:
                    window = np.array(h[-self.vol_lookback - 1 :])
                    vol = (np.diff(window) / window[:-1]).std() + 1e-9
                    mom = mom / vol  # risk-scaled momentum (don't overload high-vol names)
                moms[symbol] = mom
                last[symbol] = h[-1]
        if len(moms) < 10:
            return BotOutput([], 0.0)

        ranked = sorted(moms, key=moms.get)
        n = max(1, int(len(ranked) * self.quantile))
        longs, shorts = set(ranked[-n:]), set(ranked[:n])

        targets: list[TargetPosition] = []
        for symbol in longs:  # equal-DOLLAR legs (qty ∝ 1/price) — matches the equal-weight factor
            q = self.unit / last[symbol]
            targets.append(TargetPosition(symbol, q, stop_price=last[symbol] * (1 - self.stop_frac)))
        for symbol in shorts:
            q = self.unit / last[symbol]
            targets.append(TargetPosition(symbol, -q, stop_price=last[symbol] * (1 + self.stop_frac)))
        for symbol in moms:  # rotate out names no longer in a decile
            if symbol not in longs and symbol not in shorts:
                targets.append(TargetPosition(symbol, 0.0, None))
        return BotOutput(targets, signal_strength=min(1.0, 2.0 * n / len(moms)))
