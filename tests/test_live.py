from datetime import datetime, timezone
from unittest.mock import MagicMock

from traderbot.config import Config
from traderbot.execution.broker import FakeBroker
from traderbot.live import run_paper
from traderbot.market_data.alpaca_live import LiveAlpacaSource
from traderbot.strategies.fixed_target import FixedTargetBot
from traderbot.types import Bar

from tests.helpers import ListSource


async def test_live_source_yields_normalized_bars():
    raws = [
        MagicMock(symbol="AAPL", timestamp=datetime(2026, 6, 20, 14, 0, tzinfo=timezone.utc),
                  open=1, high=2, low=0.5, close=1.5, volume=1000),
        MagicMock(symbol="MSFT", timestamp=datetime(2026, 6, 20, 14, 1, tzinfo=timezone.utc),
                  open=10, high=11, low=9, close=10.5, volume=500),
    ]
    holder = {}

    def subscribe(handler):
        holder["h"] = handler

    async def run():
        for r in raws:
            await holder["h"](r)

    src = LiveAlpacaSource(subscribe, run)
    out = [b async for b in src.stream()]
    assert [b.symbol for b in out] == ["AAPL", "MSFT"]
    assert out[0].close == 1.5


async def test_run_paper_runs_live_stack_with_fakes(tmp_path):
    broker = FakeBroker(100_000.0)
    broker.set_mark("AAA", 100.0)
    bot = FixedTargetBot("A", "AAA", qty=10, stop_price=95.0)
    source = ListSource([Bar("AAA", datetime(2026, 6, 20, 14, 0, tzinfo=timezone.utc),
                             100, 100, 100, 100, 1_000_000)])

    engine = await run_paper(Config.default(), broker, source, [bot], store_path=str(tmp_path / "p.db"))

    assert len(engine.equity_curve) > 0
    assert "AAA" in broker.positions()  # sleeve-sized order went through the live stack
