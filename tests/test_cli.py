import asyncio
from datetime import datetime, timezone

from traderbot.cli import main
from traderbot.state.store import StateStore


def test_backtest_command_runs(capsys):
    rc = main(["backtest"])
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "sharpe" in out and "backtest complete" in out


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
