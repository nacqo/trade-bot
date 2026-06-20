import asyncio
from datetime import datetime, timedelta, timezone

import traderbot.integrations.alpaca as alp
from traderbot.cli import main
from traderbot.market_data.source import ReplaySource
from traderbot.state.store import StateStore
from traderbot.types import Bar


def test_backtest_command_runs(capsys):
    rc = main(["backtest"])
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "sharpe" in out and "backtest complete" in out


def test_backtest_real_data_path(monkeypatch, capsys):
    def fake_source(key, secret, symbols, start, end, **kw):
        t0 = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)
        bars = {
            s: [Bar(s, t0 + timedelta(minutes=m), 100 + m, 100 + m, 100 + m, 100 + m, 100000)
                for m in range(70)]
            for s in symbols
        }
        return ReplaySource(bars)

    monkeypatch.setattr(alp, "build_historical_source", fake_source)
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
    rc = main(["backtest", "--symbols", "AAA,BBB", "--start", "2026-01-02", "--end", "2026-01-09"])
    assert rc == 0
    assert "Real Alpaca backtest" in capsys.readouterr().out


def test_status_command_prints_allocations(tmp_path, capsys):
    db = str(tmp_path / "s.db")

    async def seed():
        store = StateStore(db)
        await store.init()
        await store.record_allocation(
            datetime(2026, 6, 20, tzinfo=timezone.utc), "orb", 0.5, 0.6, 60000.0, 1.2
        )
        await store.close()

    asyncio.run(seed())
    rc = main(["status", "--db", db])
    assert rc == 0
    out = capsys.readouterr().out
    assert "orb" in out and "allocation decisions: 1" in out


def test_paper_without_creds_returns_nonzero(capsys, monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    assert main(["paper"]) == 2
