"""Live paper/real runner. Reuses the exact engine + OMS as the backtest — only the broker and
data source differ (real AlpacaBroker + live feed instead of FakeBroker + replay).

The OMS's fill model acts as a real participation-cap order-sizer live (≤5% of the bar's volume),
and the real broker provides actual fills/prices via AlpacaBroker's fill-poll.
"""

from __future__ import annotations

from traderbot.config import Config
from traderbot.engine.engine import Engine
from traderbot.execution.fills import SimulatedFillModel
from traderbot.execution.oms import OMS
from traderbot.risk.risk_manager import RiskManager
from traderbot.state.store import StateStore
from traderbot.strategies.base import Strategy


async def run_paper(
    config: Config,
    broker,
    source,
    bots: list[Strategy],
    store_path: str = "traderbot.sqlite",
) -> Engine:
    store = StateStore(store_path)
    await store.init()
    fill_model = SimulatedFillModel(
        config.execution.participation_cap,
        config.execution.slippage_bps,
        config.execution.revalidate_on_carry,
    )
    risk = RiskManager(config.risk)
    oms = OMS(fill_model, risk, broker)
    engine = Engine(config, source, bots, broker, store, risk_manager=risk, oms=oms)
    await engine.run()  # live source runs until stopped; replay/finite source ends naturally
    await store.close()
    return engine
