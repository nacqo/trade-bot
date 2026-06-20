"""Backtest runner — wires the full engine (allocator + risk + OMS + participation fills) over a
historical replay source. Deterministic; reuses the exact live code paths.
"""

from __future__ import annotations

from dataclasses import dataclass

from traderbot.config import Config
from traderbot.engine.engine import Engine
from traderbot.execution.broker import FakeBroker
from traderbot.execution.fills import SimulatedFillModel
from traderbot.execution.oms import OMS
from traderbot.execution.virtual_book import VirtualBook
from traderbot.risk.risk_manager import RiskManager
from traderbot.state.store import StateStore
from traderbot.strategies.base import Strategy
from traderbot.types import Position


@dataclass
class BacktestResult:
    equity_curve: list[float]
    per_bot_equity: dict[str, list[float]]
    weights_history: list[dict[str, float]]
    fills: list[dict]
    books: dict[str, VirtualBook]
    broker_positions: dict[str, Position]


async def run_backtest(config: Config, source: object, bots: list[Strategy]) -> BacktestResult:
    store = StateStore(":memory:")
    await store.init()
    broker = FakeBroker(config.starting_equity, max_leverage=config.risk.max_gross_leverage)
    fill_model = SimulatedFillModel(
        config.execution.participation_cap,
        config.execution.slippage_bps,
        config.execution.revalidate_on_carry,
    )
    risk = RiskManager(config.risk)
    oms = OMS(fill_model, risk, broker)
    engine = Engine(config, source, bots, broker, store, risk_manager=risk, oms=oms)

    await engine.run()

    fills = await store.load_fills()
    await store.close()
    return BacktestResult(
        equity_curve=engine.equity_curve,
        per_bot_equity=engine.per_bot_equity,
        weights_history=engine.weights_history,
        fills=fills,
        books=engine.books,
        broker_positions=broker.positions(),
    )
