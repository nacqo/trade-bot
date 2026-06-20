from datetime import datetime, timezone
from unittest.mock import MagicMock

from alpaca.trading.enums import OrderSide

from traderbot.integrations.alpaca import (
    TradingClientShim,
    bars_from_barset,
    fetch_historical_bars,
)


def test_shim_builds_market_order_request():
    client = MagicMock()
    shim = TradingClientShim(client)

    shim.submit_order("AAPL", 5, "buy")
    req = client.submit_order.call_args.kwargs["order_data"]
    assert req.symbol == "AAPL"
    assert float(req.qty) == 5
    assert req.side == OrderSide.BUY

    shim.submit_order("AAPL", 3, "sell")
    assert client.submit_order.call_args.kwargs["order_data"].side == OrderSide.SELL


def test_shim_passes_through_positions_and_account():
    client = MagicMock()
    shim = TradingClientShim(client)
    shim.get_all_positions()
    shim.get_account()
    assert client.get_all_positions.called and client.get_account.called


def test_fetch_historical_normalizes_to_bars():
    raw = MagicMock(
        timestamp=datetime(2026, 6, 20, 14, 0, tzinfo=timezone.utc),
        open=1, high=2, low=0.5, close=1.5, volume=1000,
    )
    barset = MagicMock()
    barset.data = {"AAPL": [raw]}
    client = MagicMock()
    client.get_stock_bars.return_value = barset

    bars = fetch_historical_bars(
        client, ["AAPL"], datetime(2026, 6, 1, tzinfo=timezone.utc),
        datetime(2026, 6, 20, tzinfo=timezone.utc),
    )
    assert bars["AAPL"][0].close == 1.5
    assert bars["AAPL"][0].volume == 1000
    # corporate-action adjustment requested
    assert client.get_stock_bars.call_args[0][0].adjustment.value == "all"
