"""Shared test helpers."""

from __future__ import annotations


class ListSource:
    """Minimal MarketDataSource: yields a fixed list of events in order."""

    def __init__(self, events) -> None:
        self.events = list(events)

    async def stream(self):
        for event in self.events:
            yield event


class ScriptedBot:
    """Bot returning a scripted sequence of BotOutputs, one per evaluate() (last value repeats)."""

    def __init__(self, id, outputs) -> None:
        self.id = id
        self.symbols = []
        self.enabled = True
        self._outputs = list(outputs)
        self._i = 0

    def on_bar(self, bar):  # noqa: D401
        pass

    def on_quote(self, quote):
        pass

    def on_trade(self, tick):
        pass

    def evaluate(self):
        out = self._outputs[min(self._i, len(self._outputs) - 1)]
        self._i += 1
        return out
