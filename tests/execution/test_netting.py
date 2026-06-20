from traderbot.execution.netting import net_targets


def test_offsetting_bots_net_and_attribute():
    orders = net_targets({"A": {"AAPL": 600.0}, "B": {"AAPL": -100.0}})
    no = orders["AAPL"]
    assert no.qty == 500.0
    assert no.contributors == {"A": 600.0, "B": -100.0}

    attributed = no.attribute(400.0)  # 80% fill
    assert attributed["A"] == 480.0
    assert attributed["B"] == -80.0
    assert abs(sum(attributed.values()) - 400.0) < 1e-9  # attribution sums to fill


def test_multiple_symbols():
    orders = net_targets({"A": {"AAPL": 10.0, "MSFT": -5.0}, "B": {"AAPL": -3.0}})
    assert orders["AAPL"].qty == 7.0
    assert orders["MSFT"].qty == -5.0


def test_full_offset_zero_net_no_real_trade():
    orders = net_targets({"A": {"AAPL": 100.0}, "B": {"AAPL": -100.0}})
    assert orders["AAPL"].qty == 0.0
    assert orders["AAPL"].attribute(0.0) == {"A": 0.0, "B": 0.0}
