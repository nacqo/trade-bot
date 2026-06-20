"""Bot 3 — VWAP / Bollinger reversion (single-name mean reversion).

Bands are computed over the trailing window *excluding* the current bar, so a fresh outlier is
judged against recent history. Close ≥ upper band and above VWAP → short (stop above entry);
close ≤ lower band and below VWAP → long (stop below entry). Signal = deviation in σ.
"""

from __future__ import annotations

import statistics

from traderbot.strategies.base import BotOutput, Strategy, TargetPosition
from traderbot.types import Bar


class VWAPReversionBot(Strategy):
    def __init__(
        self,
        id: str,
        symbols: list[str],
        bb_period: int = 20,
        bb_sigma: float = 2.0,
        unit: float = 1.0,
    ) -> None:
        super().__init__(id, symbols)
        self.bb_period = bb_period
        self.bb_sigma = bb_sigma
        self.unit = unit
        self._s: dict[str, dict] = {}

    def on_bar(self, bar: Bar) -> None:
        s = self._s.setdefault(bar.symbol, {})
        if s.get("date") != bar.ts.date():
            s.clear()
            s["date"] = bar.ts.date()
            s["bars"] = []
            s["pv"] = 0.0  # Σ typical*volume
            s["vol"] = 0.0
        s["bars"].append(bar)
        typical = (bar.high + bar.low + bar.close) / 3.0
        s["pv"] += typical * bar.volume
        s["vol"] += bar.volume

    def evaluate(self) -> BotOutput:
        targets: list[TargetPosition] = []
        signal = 0.0
        for symbol, s in self._s.items():
            bars = s.get("bars", [])
            if len(bars) <= self.bb_period:
                continue
            window = [b.close for b in bars[-(self.bb_period + 1) : -1]]
            mean = statistics.fmean(window)
            std = statistics.pstdev(window)
            if std <= 0:
                continue
            vwap = s["pv"] / s["vol"] if s["vol"] else mean
            close = bars[-1].close
            z = (close - mean) / std
            upper = mean + self.bb_sigma * std
            lower = mean - self.bb_sigma * std
            if close >= upper and close > vwap:
                stop = close + self.bb_sigma * std  # above entry (short)
                targets.append(TargetPosition(symbol, -self.unit, stop_price=stop))
                signal = max(signal, min(1.0, abs(z) / (self.bb_sigma * 2)))
            elif close <= lower and close < vwap:
                stop = close - self.bb_sigma * std  # below entry (long)
                targets.append(TargetPosition(symbol, self.unit, stop_price=stop))
                signal = max(signal, min(1.0, abs(z) / (self.bb_sigma * 2)))
        return BotOutput(targets=targets, signal_strength=signal)
