"""Bot 1 — Statistical arbitrage pairs (market-neutral mean reversion). REQUIRED.

For each pair (a, b): rolling OLS hedge ratio β (regress a on b), spread = a − β·b, z-score the
spread. |z| ≥ z_in → short the rich leg / long the cheap leg (dollar-neutral-ish). |z| ≤ z_out →
flat. |z| ≥ z_stop → flat (cointegration breaking). Per-leg stops are placed z_stop·σ away in
price terms (a v1 approximation of the spread stop).

The cointegration *gate* (statsmodels) is an offline refit hook (Phase: backtest/adapters); v1's
hot path trades the z-score on whatever pairs are configured.
"""

from __future__ import annotations

from collections import deque

import numpy as np

from traderbot.strategies.base import BotOutput, Strategy, TargetPosition
from traderbot.types import Bar


class StatArbBot(Strategy):
    def __init__(
        self,
        id: str,
        pairs: list[tuple[str, str]],
        z_in: float = 2.0,
        z_out: float = 0.5,
        z_stop: float = 3.5,
        lookback: int = 120,
        unit: float = 1.0,
        coint_pvalue: float = 0.05,
        refit_every: int = 390,
    ) -> None:
        symbols = sorted({s for pair in pairs for s in pair})
        super().__init__(id, symbols)
        self.pairs = pairs
        self.z_in = z_in
        self.z_out = z_out
        self.z_stop = z_stop
        self.lookback = lookback
        self.unit = unit
        self.coint_pvalue = coint_pvalue
        self.refit_every = refit_every  # re-test cointegration every N evaluate()s (~1 day)
        self._w: dict[str, deque] = {s: deque(maxlen=lookback) for s in symbols}
        self._tradable: dict[tuple[str, str], bool] = {pair: False for pair in pairs}
        self._eval_count = 0

    def _refit_cointegration(self) -> None:
        """Engle–Granger gate: only trade pairs whose spread is cointegrated (p < threshold).

        Lazy-imports statsmodels so the bot still imports without it (then trades ungated).
        For large universes this should move to a worker (run_in_executor) — fine inline for a
        handful of pairs.
        """
        try:
            from statsmodels.tsa.stattools import coint
        except ImportError:
            for pair in self.pairs:
                self._tradable[pair] = True
            return
        for a_sym, b_sym in self.pairs:
            wa, wb = self._w[a_sym], self._w[b_sym]
            n = min(len(wa), len(wb))
            if n < self.lookback:
                self._tradable[(a_sym, b_sym)] = False
                continue
            a = np.array(list(wa)[-n:], dtype=float)
            b = np.array(list(wb)[-n:], dtype=float)
            try:
                self._tradable[(a_sym, b_sym)] = bool(coint(a, b)[1] < self.coint_pvalue)
            except Exception:
                self._tradable[(a_sym, b_sym)] = False

    def on_bar(self, bar: Bar) -> None:
        if bar.symbol in self._w:
            self._w[bar.symbol].append(bar.close)

    def evaluate(self) -> BotOutput:
        self._eval_count += 1
        if (self._eval_count - 1) % self.refit_every == 0:
            self._refit_cointegration()
        targets: list[TargetPosition] = []
        signal = 0.0
        for a_sym, b_sym in self.pairs:
            if not self._tradable.get((a_sym, b_sym), False):
                continue  # cointegration gate
            wa, wb = self._w[a_sym], self._w[b_sym]
            n = min(len(wa), len(wb))
            if n < self.lookback:
                continue
            a = np.array(list(wa)[-n:], dtype=float)
            b = np.array(list(wb)[-n:], dtype=float)
            beta = float(np.polyfit(b, a, 1)[0])
            spread = a - beta * b
            mean = spread.mean()
            std = spread.std()
            if std <= 0:
                continue
            z = (spread[-1] - mean) / std
            pa, pb = a[-1], b[-1]
            stop_dist = self.z_stop * std
            signal = max(signal, min(1.0, abs(z) / self.z_stop))

            if abs(z) >= self.z_stop or abs(z) <= self.z_out:
                targets.append(TargetPosition(a_sym, 0.0, None))
                targets.append(TargetPosition(b_sym, 0.0, None))
            elif z >= self.z_in:  # spread rich → short a, long b
                targets.append(TargetPosition(a_sym, -self.unit, stop_price=pa + stop_dist))
                targets.append(TargetPosition(b_sym, beta * self.unit, stop_price=pb - stop_dist / beta))
            elif z <= -self.z_in:  # spread cheap → long a, short b
                targets.append(TargetPosition(a_sym, self.unit, stop_price=pa - stop_dist))
                targets.append(TargetPosition(b_sym, -beta * self.unit, stop_price=pb + stop_dist / beta))
            # else: hold (emit nothing for these symbols)
        return BotOutput(targets=targets, signal_strength=signal)
