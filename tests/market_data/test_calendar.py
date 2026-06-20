from datetime import date, datetime
from zoneinfo import ZoneInfo

from traderbot.market_data.calendar import TradingCalendar

ET = ZoneInfo("America/New_York")


def test_regular_session_open():
    cal = TradingCalendar()
    # 2026-06-17 is a regular Wednesday (Juneteenth is the 19th)
    assert cal.is_open(datetime(2026, 6, 17, 14, 0, tzinfo=ET))


def test_pre_market_closed():
    cal = TradingCalendar()
    assert not cal.is_open(datetime(2026, 6, 17, 8, 0, tzinfo=ET))


def test_holiday_closed():
    cal = TradingCalendar()
    assert not cal.is_open(datetime(2026, 1, 1, 12, 0, tzinfo=ET))  # New Year's Day


def test_session_bounds_and_minutes():
    cal = TradingCalendar()
    bounds = cal.session_bounds(date(2026, 6, 17))
    assert bounds is not None
    assert cal.minutes_in_session(date(2026, 6, 17)) == 390  # 9:30–16:00 = 6.5h
    assert cal.minutes_in_session(date(2026, 1, 1)) == 0
