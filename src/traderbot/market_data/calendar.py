"""NYSE trading calendar — gates all session logic (RTH, holidays, half-days)."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pandas_market_calendars as mcal


class TradingCalendar:
    def __init__(self, name: str = "XNYS") -> None:
        self.cal = mcal.get_calendar(name)

    def _session(self, d: date) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        sched = self.cal.schedule(start_date=d, end_date=d)
        if sched.empty:
            return None
        return sched.iloc[0]["market_open"], sched.iloc[0]["market_close"]

    def is_open(self, ts: datetime) -> bool:
        t = pd.Timestamp(ts)
        t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
        et_date = t.tz_convert("America/New_York").date()
        session = self._session(et_date)
        if session is None:
            return False
        market_open, market_close = session
        return market_open <= t <= market_close

    def session_bounds(self, d: date) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        return self._session(d)

    def minutes_in_session(self, d: date) -> int:
        session = self._session(d)
        if session is None:
            return 0
        market_open, market_close = session
        return int((market_close - market_open).total_seconds() // 60)
