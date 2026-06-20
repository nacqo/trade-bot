"""Alpaca market-data feed adapter (implements `MarketDataSource`).

Wraps an async stream of raw Alpaca bar objects and normalizes them to `Bar`. Bars are
corporate-action-adjusted at the source (Alpaca `adjustment="all"`); the thin SDK shim that
produces `raw_stream` is wired in the live phase.
"""

from __future__ import annotations

from typing import AsyncIterator

from traderbot.types import Bar


class AlpacaFeed:
    def __init__(self, raw_stream) -> None:
        self._raw_stream = raw_stream

    @staticmethod
    def normalize_bar(raw) -> Bar:
        return Bar(
            symbol=raw.symbol,
            ts=raw.timestamp,
            open=float(raw.open),
            high=float(raw.high),
            low=float(raw.low),
            close=float(raw.close),
            volume=float(raw.volume),
        )

    async def stream(self) -> AsyncIterator[Bar]:
        async for raw in self._raw_stream:
            yield self.normalize_bar(raw)
