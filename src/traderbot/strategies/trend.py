"""Time-series (trend) momentum bot — "managed-futures" style, on a diversified ETF basket.

Each asset: long if its trailing 12-month return is positive, short if negative; sized inverse to
its volatility (risk parity). Decorrelated from cross-sectional equity momentum (it trades own-asset
trend across equities, bonds, gold, commodities → crisis-alpha diversification). Daily bars.

Validated (scripts/tsmom.py): pooled IC +0.037, vol-scaled portfolio Sharpe +0.46 (OOS +1.0).
"""

from __future__ import annotations

from collections import deque

import numpy as np

from traderbot.strategies.base import BotOutput, Strategy, TargetPosition
from traderbot.types import Bar


class TimeSeriesMomentumBot(Strategy):
    def __init__(
        self,
        id: str,
        symbols: list[str],
        lookback: int = 252,
        vol_lookback: int = 60,
        unit: float = 1.0,
        stop_frac: float = 0.20,
    ) -> None:
        super().__init__(id, symbols)
        self.lookback = lookback
        self.vol_lookback = vol_lookback
        self.unit = unit
        self.stop_frac = stop_frac
        self._hist: dict[str, deque] = {s: deque(maxlen=lookback + 2) for s in symbols}

    def on_bar(self, bar: Bar) -> None:
        if bar.symbol in self._hist:
            self._hist[bar.symbol].append(bar.close)

    def evaluate(self) -> BotOutput:
        targets: list[TargetPosition] = []
        strengths: list[float] = []
        for symbol, hist in self._hist.items():
            if len(hist) < self.lookback + 1:
                continue
            h = list(hist)
            trail = h[-1] / h[-self.lookback] - 1.0
            window = np.array(h[-self.vol_lookback - 1:])
            vol = (np.diff(window) / window[:-1]).std() + 1e-9
            price = h[-1]
            direction = 1.0 if trail >= 0 else -1.0
            qty = direction * self.unit / vol / price  # inverse-vol weight; |qty*price| = unit/vol
            stop = price * (1 - self.stop_frac) if direction > 0 else price * (1 + self.stop_frac)
            targets.append(TargetPosition(symbol, qty, stop_price=stop))
            strengths.append(min(1.0, abs(trail) / 0.3))
        if not targets:
            return BotOutput([], 0.0)
        return BotOutput(targets, signal_strength=float(np.mean(strengths)))
