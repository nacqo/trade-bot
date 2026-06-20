"""SQLite state store (spec §11) — fills, positions, equity, allocations, risk events.

Backs PnL attribution and exact crash recovery.
"""

from __future__ import annotations

from datetime import datetime

import aiosqlite

from traderbot.types import Fill

_SCHEMA = """
CREATE TABLE IF NOT EXISTS fills (
  ts TEXT, bot_id TEXT, symbol TEXT, qty REAL, price REAL
);
CREATE TABLE IF NOT EXISTS positions (
  ts TEXT, bot_id TEXT, symbol TEXT, qty REAL, avg_price REAL
);
CREATE TABLE IF NOT EXISTS bot_equity (
  ts TEXT, bot_id TEXT, realized REAL, unrealized REAL, equity REAL
);
CREATE TABLE IF NOT EXISTS allocations (
  ts TEXT, bot_id TEXT, score REAL, weight REAL, capital REAL, aggressiveness REAL
);
CREATE TABLE IF NOT EXISTS orders (
  ts TEXT, order_id TEXT, bot_id TEXT, symbol TEXT, qty REAL, status TEXT
);
CREATE TABLE IF NOT EXISTS risk_events (
  ts TEXT, type TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS config_snapshots (
  ts TEXT, json TEXT
);
"""


class StateStore:
    def __init__(self, path: str) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("StateStore.init() not called")
        return self._db

    async def record_fill(self, fill: Fill) -> None:
        await self.db.execute(
            "INSERT INTO fills (ts, bot_id, symbol, qty, price) VALUES (?,?,?,?,?)",
            (fill.ts.isoformat(), fill.bot_id, fill.symbol, fill.qty, fill.price),
        )
        await self.db.commit()

    async def record_position(
        self, ts: datetime, bot_id: str, symbol: str, qty: float, avg_price: float
    ) -> None:
        await self.db.execute(
            "INSERT INTO positions (ts, bot_id, symbol, qty, avg_price) VALUES (?,?,?,?,?)",
            (ts.isoformat(), bot_id, symbol, qty, avg_price),
        )
        await self.db.commit()

    async def record_allocation(
        self, ts: datetime, bot_id: str, score: float, weight: float, capital: float, aggr: float
    ) -> None:
        await self.db.execute(
            "INSERT INTO allocations (ts, bot_id, score, weight, capital, aggressiveness) "
            "VALUES (?,?,?,?,?,?)",
            (ts.isoformat(), bot_id, score, weight, capital, aggr),
        )
        await self.db.commit()

    async def record_bot_equity(
        self, ts: datetime, bot_id: str, realized: float, unrealized: float, equity: float
    ) -> None:
        await self.db.execute(
            "INSERT INTO bot_equity (ts, bot_id, realized, unrealized, equity) VALUES (?,?,?,?,?)",
            (ts.isoformat(), bot_id, realized, unrealized, equity),
        )
        await self.db.commit()

    async def record_risk_event(self, ts: datetime, type_: str, detail: str) -> None:
        await self.db.execute(
            "INSERT INTO risk_events (ts, type, detail) VALUES (?,?,?)",
            (ts.isoformat(), type_, detail),
        )
        await self.db.commit()

    async def load_fills(self) -> list[dict]:
        async with self.db.execute("SELECT * FROM fills ORDER BY ts") as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def load_positions(self) -> list[dict]:
        async with self.db.execute("SELECT * FROM positions ORDER BY ts") as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def count(self, table: str) -> int:
        async with self.db.execute(f"SELECT COUNT(*) AS n FROM {table}") as cur:
            row = await cur.fetchone()
            return int(row["n"])

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None
