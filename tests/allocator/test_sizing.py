from traderbot.allocator.allocator import sleeve_scale


def test_sleeve_scale_sizes_to_capital():
    # weight 0.5 of $100k = $50k sleeve; raw gross $1000 → scale 50× → $50k gross
    assert sleeve_scale(0.5, 1.0, 100_000, 1000) == 50.0


def test_aggressiveness_scales_size():
    assert sleeve_scale(0.5, 2.0, 100_000, 1000) == 100.0


def test_zero_desired_gross_is_flat():
    assert sleeve_scale(0.5, 1.0, 100_000, 0.0) == 0.0


def test_higher_weight_deploys_more():
    assert sleeve_scale(0.8, 1.0, 100_000, 1000) > sleeve_scale(0.2, 1.0, 100_000, 1000)
