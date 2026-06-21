"""Residual (idiosyncratic) momentum bot — bot 5.

Momentum on the part of each stock's return that is NOT explained by the market (the residual after
a rolling beta regression). Strips the market/beta component, so it's more market-neutral and less
correlated with plain momentum, with a higher Sharpe in validation (IC t=3.6, L/S Sharpe +0.80,
OOS +1.14 — scripts/signals.py). Cross-sectional, daily bars, prices-only.
"""

from __future__ import annotations

from collections import deque

import numpy as np

from traderbot.strategies.base import BotOutput, Strategy, TargetPosition
from traderbot.types import Bar


class ResidualMomentumBot(Strategy):
    def __init__(
        self,
        id: str,
        symbols: list[str],
        lookback: int = 252,
        skip: int = 21,
        quantile: float = 0.2,
        unit: float = 1.0,
        stop_frac: float = 0.15,
    ) -> None:
        super().__init__(id, symbols)
        self.lookback = lookback
        self.skip = skip
        self.quantile = quantile
        self.unit = unit
        self.stop_frac = stop_frac
        self._hist: dict[str, deque] = {s: deque(maxlen=lookback + 2) for s in symbols}

    def on_bar(self, bar: Bar) -> None:
        if bar.symbol in self._hist:
            self._hist[bar.symbol].append(bar.close)

    def evaluate(self) -> BotOutput:
        syms = [s for s, h in self._hist.items() if len(h) >= self.lookback + 1]
        if len(syms) < 10:
            return BotOutput([], 0.0)
        length = min(len(self._hist[s]) for s in syms)
        closes = {s: np.array(list(self._hist[s])[-length:], dtype=float) for s in syms}
        rets = np.vstack([np.diff(closes[s]) / closes[s][:-1] for s in syms])  # (n, length-1)
        mkt = rets.mean(axis=0)
        var_mkt = mkt.var() + 1e-12

        scores: dict[str, float] = {}
        last: dict[str, float] = {}
        for i, s in enumerate(syms):
            beta = np.cov(rets[i], mkt)[0, 1] / var_mkt
            resid = rets[i] - beta * mkt
            window = resid[-self.lookback:-self.skip] if len(resid) >= self.lookback else resid[:-self.skip]
            scores[s] = float(window.sum())
            last[s] = closes[s][-1]

        ranked = sorted(scores, key=scores.get)
        n = max(1, int(len(ranked) * self.quantile))
        longs, shorts = set(ranked[-n:]), set(ranked[:n])
        targets: list[TargetPosition] = []
        for s in longs:
            q = self.unit / last[s]
            targets.append(TargetPosition(s, q, stop_price=last[s] * (1 - self.stop_frac)))
        for s in shorts:
            q = self.unit / last[s]
            targets.append(TargetPosition(s, -q, stop_price=last[s] * (1 + self.stop_frac)))
        for s in scores:
            if s not in longs and s not in shorts:
                targets.append(TargetPosition(s, 0.0, None))
        return BotOutput(targets, signal_strength=min(1.0, 2.0 * n / len(scores)))
