"""Live Alpaca websocket feed → MarketDataSource.

Alpaca's StockDataStream is callback-based; this bridges it to our async `stream()` via a queue.
`subscribe(handler)` registers the bar handler and `run()` drives the underlying stream — both
injected so the bridge is unit-testable with fakes (the real wiring lives in
`integrations.alpaca.build_live_source`).
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Awaitable, Callable

from traderbot.market_data.alpaca_feed import AlpacaFeed
from traderbot.types import Bar


class LiveAlpacaSource:
    def __init__(
        self,
        subscribe: Callable[[Callable], None],
        run: Callable[[], Awaitable[None]],
        normalize=AlpacaFeed.normalize_bar,
    ) -> None:
        self._subscribe = subscribe
        self._run = run
        self._normalize = normalize
        self._queue: asyncio.Queue | None = None

    async def _handler(self, raw) -> None:
        await self._queue.put(self._normalize(raw))

    async def stream(self) -> AsyncIterator[Bar]:
        self._queue = asyncio.Queue()
        self._subscribe(self._handler)
        runner = asyncio.create_task(self._run())
        try:
            while not (runner.done() and self._queue.empty()):
                try:
                    item = await asyncio.wait_for(self._queue.get(), timeout=0.05)
                except asyncio.TimeoutError:
                    continue
                yield item
        finally:
            if not runner.done():
                runner.cancel()
        if runner.done() and runner.exception() is not None:
            raise runner.exception()
