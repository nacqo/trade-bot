"""Bot 4 — Order-flow imbalance (microstructure).

From top-of-book quotes: imbalance = (bid_size − ask_size)/(bid_size + ask_size), reinforced by
signed trade-flow. Strong positive → brief long (tight stop = recent low); strong negative →
short (tight stop = recent high). Top-of-book only (Alpaca free feed) — a light proxy, not deep
L2; validated mainly in paper.
"""

from __future__ import annotations

from collections import deque

from traderbot.strategies.base import BotOutput, Strategy, TargetPosition
from traderbot.types import Quote, TradeTick


class OrderFlowBot(Strategy):
    def __init__(
        self,
        id: str,
        symbols: list[str],
        window: int = 60,
        imb_threshold: float = 0.3,
        unit: float = 1.0,
    ) -> None:
        super().__init__(id, symbols)
        self.window = window
        self.imb_threshold = imb_threshold
        self.unit = unit
        self._imb: dict[str, float] = {}
        self._mids: dict[str, deque] = {}
        self._flow: dict[str, float] = {}

    def on_quote(self, quote: Quote) -> None:
        total = quote.bid_size + quote.ask_size
        self._imb[quote.symbol] = (quote.bid_size - quote.ask_size) / total if total else 0.0
        mids = self._mids.setdefault(quote.symbol, deque(maxlen=self.window))
        mids.append((quote.bid + quote.ask) / 2.0)

    def on_trade(self, tick: TradeTick) -> None:
        # signed trade-flow proxy: accumulate, decayed lightly each tick
        prev = self._flow.get(tick.symbol, 0.0)
        self._flow[tick.symbol] = 0.9 * prev + tick.size  # magnitude only in v1

    def evaluate(self) -> BotOutput:
        targets: list[TargetPosition] = []
        signal = 0.0
        for symbol, imb in self._imb.items():
            mids = self._mids.get(symbol)
            if not mids:
                continue
            if imb >= self.imb_threshold:
                targets.append(TargetPosition(symbol, self.unit, stop_price=min(mids) - 1e-6))
                signal = max(signal, min(1.0, abs(imb)))
            elif imb <= -self.imb_threshold:
                targets.append(TargetPosition(symbol, -self.unit, stop_price=max(mids) + 1e-6))
                signal = max(signal, min(1.0, abs(imb)))
        return BotOutput(targets=targets, signal_strength=signal)
