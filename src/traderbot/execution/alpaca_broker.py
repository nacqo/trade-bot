"""Alpaca broker adapter (implements the `Broker` interface).

Depends on a *minimal* client interface (submit_order / get_all_positions / get_account) so it
is unit-testable with a mock and decoupled from alpaca-py's exact request objects. A thin shim
adapts the real `alpaca.trading.TradingClient` to this interface in the live phase; `paper=True`
just points that client at the paper endpoint.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable

from traderbot.types import Fill, OrderIntent, Position


class AlpacaBroker:
    def __init__(
        self,
        client,
        poll_fills: bool = True,
        max_polls: int = 10,
        poll_interval: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.poll_fills = poll_fills
        self.max_polls = max_polls
        self.poll_interval = poll_interval
        self._sleep = sleep

    def submit(self, intent: OrderIntent) -> Fill:
        side = "buy" if intent.target_qty > 0 else "sell"
        order = self.client.submit_order(
            symbol=intent.symbol, qty=abs(intent.target_qty), side=side, type="market"
        )
        # market orders aren't filled the instant submit returns → poll until filled
        polls = 0
        while self.poll_fills and not order.filled_qty and polls < self.max_polls:
            self._sleep(self.poll_interval)
            order = self.client.get_order_by_id(order.id)
            polls += 1
        sign = 1.0 if intent.target_qty > 0 else -1.0
        filled = float(order.filled_qty or 0.0) * sign
        price = float(order.filled_avg_price or 0.0)
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

    def gross(self) -> float:
        account = self.client.get_account()
        long_mv = float(getattr(account, "long_market_value", 0.0) or 0.0)
        short_mv = float(getattr(account, "short_market_value", 0.0) or 0.0)
        return long_mv + abs(short_mv)
