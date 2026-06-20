"""Real alpaca-py wiring: a thin shim adapting the SDK to our minimal interfaces.

- `TradingClientShim` adapts `TradingClient` (which takes an OrderRequest object) to the
  kwargs-style `submit_order(symbol, qty, side)` that `AlpacaBroker` expects.
- `fetch_historical_bars` pulls corporate-action-adjusted (`Adjustment.ALL`) bars and
  normalizes them to our `Bar`.

Both factories construct the real clients (no network until a call is made); the helpers take
an injected client so they're unit-testable with a mock.

⚠️ Live fill handling: market orders may not be filled the instant `submit_order` returns.
`AlpacaBroker.submit` reads `filled_qty/filled_avg_price`; for unfilled orders these are 0/None.
A live loop should confirm fills via the trade-updates stream (a documented seam, not wired in v1).
"""

from __future__ import annotations

from datetime import datetime

from alpaca.data.enums import Adjustment
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from traderbot.execution.alpaca_broker import AlpacaBroker
from traderbot.market_data.source import ReplaySource
from traderbot.types import Bar


class TradingClientShim:
    """Adapts alpaca-py TradingClient to the minimal client interface AlpacaBroker uses."""

    def __init__(self, client) -> None:
        self._client = client

    def submit_order(self, symbol: str, qty: float, side: str, type: str = "market"):
        request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        return self._client.submit_order(order_data=request)

    def get_all_positions(self):
        return self._client.get_all_positions()

    def get_account(self):
        return self._client.get_account()

    def get_order_by_id(self, order_id):
        return self._client.get_order_by_id(order_id)


def build_alpaca_broker(api_key: str, secret_key: str, paper: bool = True) -> AlpacaBroker:
    return AlpacaBroker(TradingClientShim(TradingClient(api_key, secret_key, paper=paper)))


def bars_from_barset(barset) -> dict[str, list[Bar]]:
    out: dict[str, list[Bar]] = {}
    for symbol, bars in barset.data.items():
        out[symbol] = [
            Bar(symbol, b.timestamp, float(b.open), float(b.high), float(b.low),
                float(b.close), float(b.volume))
            for b in bars
        ]
    return out


def fetch_historical_bars(
    data_client,
    symbols: list[str],
    start: datetime,
    end: datetime,
    timeframe=TimeFrame.Minute,
    feed: str = "iex",
) -> dict[str, list[Bar]]:
    request = StockBarsRequest(
        symbol_or_symbols=list(symbols),
        timeframe=timeframe,
        start=start,
        end=end,
        adjustment=Adjustment.ALL,
        feed=feed,
    )
    return bars_from_barset(data_client.get_stock_bars(request))


def build_historical_source(
    api_key: str, secret_key: str, symbols: list[str], start: datetime, end: datetime, **kwargs
) -> ReplaySource:
    client = StockHistoricalDataClient(api_key, secret_key)
    return ReplaySource(fetch_historical_bars(client, symbols, start, end, **kwargs))


def build_live_source(api_key: str, secret_key: str, symbols: list[str]):
    """Wire the real StockDataStream into a LiveAlpacaSource. ⚠️ Needs a live connection;
    validate against the paper account (not exercised by the test suite).
    """
    from alpaca.data.live import StockDataStream

    from traderbot.market_data.alpaca_live import LiveAlpacaSource

    stream = StockDataStream(api_key, secret_key)

    def subscribe(handler):
        stream.subscribe_bars(handler, *symbols)

    async def run():
        await stream._run_forever()

    return LiveAlpacaSource(subscribe, run)
