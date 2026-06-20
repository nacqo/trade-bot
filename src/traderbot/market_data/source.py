"""Market-data sources. Live (Alpaca) and historical (replay) implement the same protocol so
the engine is identical in both modes.
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable

from traderbot.types import Bar, Quote, TradeTick

Event = Bar | Quote | TradeTick


@runtime_checkable
class MarketDataSource(Protocol):
    def stream(self) -> AsyncIterator[Event]: ...


class ReplaySource:
    """Yields historical events in strict timestamp order (closed bars only — no lookahead)."""

    def __init__(
        self,
        bars_by_symbol: dict[str, list[Bar]] | None = None,
        quotes: list[Quote] | None = None,
        trades: list[TradeTick] | None = None,
    ) -> None:
        events: list[Event] = []
        for bars in (bars_by_symbol or {}).values():
            events.extend(bars)
        events.extend(quotes or [])
        events.extend(trades or [])
        # stable sort by ts; bars/quotes/trades at the same ts keep insertion order
        self._events = sorted(events, key=lambda e: e.ts)

    async def stream(self) -> AsyncIterator[Event]:
        for event in self._events:
            yield event
