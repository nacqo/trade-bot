from traderbot.execution.virtual_book import VirtualBook


def test_long_unrealized_then_realized():
    b = VirtualBook("b1")
    b.apply_fill("AAPL", 10, 100.0)
    b.mark({"AAPL": 110.0})
    assert b.unrealized == 100.0
    assert b.realized == 0.0
    assert b.equity == 100.0

    b.apply_fill("AAPL", -10, 110.0)
    assert b.realized == 100.0
    assert b.unrealized == 0.0
    assert "AAPL" not in b.positions


def test_short_pnl():
    b = VirtualBook("b1")
    b.apply_fill("AAPL", -10, 100.0)
    b.mark({"AAPL": 90.0})
    assert b.unrealized == 100.0  # short gains when price falls
    b.apply_fill("AAPL", 10, 90.0)
    assert b.realized == 100.0


def test_long_to_short_flip_realizes_then_reopens():
    b = VirtualBook("b1")
    b.apply_fill("AAPL", 10, 100.0)
    b.apply_fill("AAPL", -15, 110.0)  # close 10 (+100), open short 5 @110
    assert b.realized == 100.0
    pos = b.positions["AAPL"]
    assert pos.qty == -5
    assert pos.avg_price == 110.0


def test_add_to_position_weighted_avg():
    b = VirtualBook("b1")
    b.apply_fill("AAPL", 10, 100.0)
    b.apply_fill("AAPL", 10, 120.0)
    assert b.positions["AAPL"].avg_price == 110.0
