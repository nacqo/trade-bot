"""Bot 2 — Opening Range Breakout (intraday momentum).

Build the session's opening range from the first N bars; a close above OR-high → long
(stop = OR-low), below OR-low → short (stop = OR-high). Signal = breakout distance / ATR.
"""

from __future__ import annotations

from traderbot.strategies.base import BotOutput, Strategy, TargetPosition
from traderbot.types import Bar


class ORBBot(Strategy):
    def __init__(
        self,
        id: str,
        symbols: list[str],
        opening_minutes: int = 30,
        atr_period: int = 14,
        unit: float = 1.0,
    ) -> None:
        super().__init__(id, symbols)
        self.opening_minutes = opening_minutes
        self.atr_period = atr_period
        self.unit = unit
        self._s: dict[str, dict] = {}

    def on_bar(self, bar: Bar) -> None:
        s = self._s.setdefault(bar.symbol, {})
        if s.get("date") != bar.ts.date():
            s.clear()
            s["date"] = bar.ts.date()
            s["bars"] = []
        s["bars"].append(bar)

    def _atr(self, bars: list[Bar]) -> float:
        window = bars[-self.atr_period :]
        if not window:
            return 0.0
        return sum(b.high - b.low for b in window) / len(window)

    def evaluate(self) -> BotOutput:
        targets: list[TargetPosition] = []
        signal = 0.0
        for symbol, s in self._s.items():
            bars = s.get("bars", [])
            if len(bars) <= self.opening_minutes:
                continue
            opening = bars[: self.opening_minutes]
            or_high = max(b.high for b in opening)
            or_low = min(b.low for b in opening)
            close = bars[-1].close
            atr = self._atr(bars) or 1e-9
            if close > or_high:
                targets.append(TargetPosition(symbol, self.unit, stop_price=or_low))
                signal = max(signal, min(1.0, (close - or_high) / atr))
            elif close < or_low:
                targets.append(TargetPosition(symbol, -self.unit, stop_price=or_high))
                signal = max(signal, min(1.0, (or_low - close) / atr))
        return BotOutput(targets=targets, signal_strength=signal)
