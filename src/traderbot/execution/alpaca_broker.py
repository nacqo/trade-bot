"""Alpaca broker adapter (implements the `Broker` interface).

Depends on a *minimal* client interface (submit_order / get_all_positions / get_account) so it
is unit-testable with a mock and decoupled from alpaca-py's exact request objects. A thin shim
adapts the real `alpaca.trading.TradingClient` to this interface in the live phase; `paper=True`
just points that client at the paper endpoint.
"""

from __future__ import annotations

from datetime import datetime, timezone

from traderbot.types import Fill, OrderIntent, Position


class AlpacaBroker:
    def __init__(self, client) -> None:
        self.client = client

    def submit(self, intent: OrderIntent) -> Fill:
        side = "buy" if intent.target_qty > 0 else "sell"
        order = self.client.submit_order(
            symbol=intent.symbol, qty=abs(intent.target_qty), side=side, type="market"
        )
        sign = 1.0 if intent.target_qty > 0 else -1.0
        filled = float(order.filled_qty) * sign
        price = float(order.filled_avg_price)
        return Fill(intent.bot_id, intent.symbol, filled, price, datetime.now(timezone.utc))

    def positions(self) -> dict[str, Position]:
        out: dict[str, Position] = {}
        for p in self.client.get_all_positions():
            out[p.symbol] = Position(p.symbol, float(p.qty), float(p.avg_entry_price))
        return out

    def equity(self) -> float:
        return float(self.client.get_account().equity)

    def buying_power(self) -> float:
        return float(self.client.get_account().buying_power)
