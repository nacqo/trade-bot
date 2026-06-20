"""Shared test helpers."""

from __future__ import annotations


class ListSource:
    """Minimal MarketDataSource: yields a fixed list of events in order."""

    def __init__(self, events) -> None:
        self.events = list(events)

    async def stream(self):
        for event in self.events:
            yield event
