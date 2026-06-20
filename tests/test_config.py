from traderbot.config import Config


def test_default_config_has_spec_defaults():
    c = Config.default()
    assert c.allocator.tau == 0.5
    assert c.allocator.floor == 0.05
    assert c.allocator.cap == 0.50
    assert c.allocator.ewma_half_life_hours == 4.0
    assert c.risk.max_gross_leverage == 1.5
    assert c.risk.max_total_open_risk_frac == 0.10
    assert c.execution.participation_cap == 0.05
    assert c.execution.revalidate_on_carry is True


def test_config_is_mutable_for_tuning():
    c = Config.default()
    c.allocator.tau = 0.2
    assert c.allocator.tau == 0.2
