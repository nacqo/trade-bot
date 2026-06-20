"""Order Management System. Per candle:

bot targets → per-bot deltas (vs each bot's virtual book) → net per symbol → buying-power guard
→ participation-capped fill → submit to broker → attribute the fill pro-rata into each bot's
virtual book → queue any remainder for the next candle (re-validated then).

Per-bot stop/heat admission lives in the engine/risk layer on the *targets*; the OMS owns
netting, the participation cap, the buying-power guard, and attribution.
"""

from __future__ import annotations

from typing import Callable

from traderbot.execution.broker import Broker
from traderbot.execution.fills import CarryOrder, SimulatedFillModel
from traderbot.execution.netting import NetOrder, net_targets
from traderbot.execution.virtual_book import VirtualBook
from traderbot.risk.risk_manager import RiskManager
from traderbot.strategies.base import TargetPosition
from traderbot.types import Bar, Fill, OrderIntent


class OMS:
    def __init__(self, fill_model: SimulatedFillModel, risk_manager: RiskManager, broker: Broker) -> None:
        self.fm = fill_model
        self.rm = risk_manager
        self.broker = broker
        self.pending: dict[str, NetOrder] = {}

    async def execute(
        self,
        bot_targets: dict[str, list[TargetPosition]],
        candle: Bar,
        equity: float,
        books: dict[str, VirtualBook],
        still_valid: dict[str, Callable[[], bool]] | None = None,
    ) -> list[Fill]:
        bot_deltas: dict[str, dict[str, float]] = {}
        for bot_id, targets in bot_targets.items():
            book = books[bot_id]
            for t in targets:
                if t.symbol != candle.symbol:
                    continue
                cur = book.positions.get(t.symbol)
                delta = t.qty - (cur.qty if cur else 0.0)
                if delta != 0:
                    bot_deltas.setdefault(bot_id, {})[t.symbol] = delta

        nets = net_targets(bot_deltas)
        # fold in any carried remainder for this symbol
        if candle.symbol in self.pending:
            nets[candle.symbol] = self._merge(nets.get(candle.symbol), self.pending.pop(candle.symbol))

        fills: list[Fill] = []
        for symbol, order in nets.items():
            if order.qty == 0 or symbol != candle.symbol:
                continue
            # Buying-power guard + independent gross-leverage cap. The broker's reported buying
            # power can far exceed our intended cap (e.g. Alpaca PDT shows 4× equity); clamp to
            # equity × max_gross_leverage − current gross so our 1.5× cap binds live too.
            lev_room = max(0.0, equity * self.rm.cfg.max_gross_leverage - self.broker.gross())
            effective_bp = min(self.broker.buying_power(), lev_room)
            if abs(order.qty) * candle.close > effective_bp + 1e-9:
                continue

            positions = self.broker.positions()
            cur_real = positions[symbol].qty if symbol in positions else 0.0
            is_entry = abs(cur_real + order.qty) >= abs(cur_real)
            sv = (still_valid or {}).get(symbol, lambda: True)

            result = self.fm.fill(
                CarryOrder("net", symbol, order.qty, is_entry=is_entry), candle, still_valid=sv
            )
            if result.cancelled:
                continue
            if result.filled_qty == 0:
                self.pending[symbol] = order  # nothing fillable this candle (e.g. cap → 0); carry
                continue

            fill = self.broker.submit(OrderIntent("net", symbol, result.filled_qty, None))
            fills.append(fill)
            actual = fill.qty  # broker's REAL fill — may be < requested live (partial fill)
            attributed = order.attribute(actual)
            for bot_id, qty in attributed.items():
                if qty != 0:
                    books[bot_id].apply_fill(symbol, qty, fill.price)

            # carry whatever still isn't filled: capped-out part + any live partial shortfall
            remainder = order.qty - actual
            if abs(remainder) > 1e-9:
                remainder_contrib = {
                    b: order.contributors[b] - attributed.get(b, 0.0) for b in order.contributors
                }
                self.pending[symbol] = NetOrder(symbol, remainder, remainder_contrib)
        return fills

    @staticmethod
    def _merge(a: NetOrder | None, b: NetOrder) -> NetOrder:
        if a is None:
            return b
        contrib = dict(a.contributors)
        for bot, delta in b.contributors.items():
            contrib[bot] = contrib.get(bot, 0.0) + delta
        return NetOrder(a.symbol, a.qty + b.qty, contrib)
