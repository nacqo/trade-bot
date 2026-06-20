from datetime import datetime, timezone
from unittest.mock import MagicMock

from traderbot.execution.alpaca_broker import AlpacaBroker
from traderbot.market_data.alpaca_feed import AlpacaFeed
from traderbot.types import OrderIntent


def test_submit_maps_order_to_signed_fill():
    client = MagicMock()
    client.submit_order.return_value = MagicMock(filled_qty="5", filled_avg_price="100.5")
    broker = AlpacaBroker(client)

    fill = broker.submit(OrderIntent("b1", "AAPL", 5, 99.0))
    assert fill.symbol == "AAPL" and fill.qty == 5 and fill.price == 100.5
    assert client.submit_order.call_args.kwargs["side"] == "buy"

    broker.submit(OrderIntent("b1", "AAPL", -3, 101.0))
    assert client.submit_order.call_args.kwargs["side"] == "sell"


def test_positions_and_account_normalized():
    client = MagicMock()
    client.get_all_positions.return_value = [
        MagicMock(symbol="AAPL", qty="10", avg_entry_price="100")
    ]
    client.get_account.return_value = MagicMock(equity="100000", buying_power="150000")
    broker = AlpacaBroker(client)

    assert broker.positions()["AAPL"].qty == 10
    assert broker.equity() == 100000
    assert broker.buying_power() == 150000


async def test_feed_normalizes_bars():
    async def raw_stream():
        yield MagicMock(symbol="AAPL", timestamp=datetime(2026, 6, 20, tzinfo=timezone.utc),
                        open="1", high="2", low="0.5", close="1.5", volume="1000")

    out = [b async for b in AlpacaFeed(raw_stream()).stream()]
    assert out[0].symbol == "AAPL" and out[0].close == 1.5 and out[0].volume == 1000
