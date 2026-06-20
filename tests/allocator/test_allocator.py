from hypothesis import given, settings
from hypothesis import strategies as st

from traderbot.allocator.allocator import Allocator
from traderbot.config import AllocatorCfg


def test_weights_sum_to_one_and_within_bounds():
    cfg = AllocatorCfg()
    a = Allocator(cfg)
    res = a.allocate(
        {"b1": 2.0, "b2": 1.0, "b3": 0.0, "b4": -1.0},
        active={"b1", "b2", "b3", "b4"},
        prev_weights={},
    )
    w = {k: v.weight for k, v in res.items()}
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert all(cfg.floor - 1e-9 <= x <= cfg.cap + 1e-9 for x in w.values())
    # better score → not less capital than a worse score
    assert w["b1"] >= w["b4"]


def test_dormant_bot_gets_zero_and_excluded():
    a = Allocator(AllocatorCfg())
    res = a.allocate({"b1": 1.0, "b5": 5.0}, active={"b1"}, prev_weights={})
    assert "b5" not in res
    assert abs(res["b1"].weight - 1.0) < 1e-9


def test_smoothing_limits_step():
    cfg = AllocatorCfg(max_step=0.1)
    a = Allocator(cfg)
    # b1 strongly favored but started tiny → should move toward, not leap to, its target
    res = a.allocate(
        {"b1": 10.0, "b2": 0.0, "b3": 0.0},
        active={"b1", "b2", "b3"},
        prev_weights={"b1": 0.05, "b2": 0.05, "b3": 0.90},
    )
    assert 0.05 < res["b1"].weight < 0.30  # moved up, but not all the way to its 0.5 cap


def test_aggressiveness_tracks_score():
    a = Allocator(AllocatorCfg())
    res = a.allocate(
        {"b1": 3.0, "b2": -3.0}, active={"b1", "b2"}, prev_weights={}
    )
    assert res["b1"].aggressiveness > res["b2"].aggressiveness
    assert res["b1"].aggressiveness <= AllocatorCfg().aggr_max + 1e-9
    assert res["b2"].aggressiveness >= AllocatorCfg().aggr_min - 1e-9


@settings(max_examples=200)
@given(
    scores=st.dictionaries(
        st.sampled_from(["b1", "b2", "b3", "b4", "b5"]),
        st.floats(min_value=-20, max_value=20, allow_nan=False),
        min_size=1,
        max_size=5,
    )
)
def test_property_weights_valid(scores):
    cfg = AllocatorCfg()
    a = Allocator(cfg)
    active = set(scores)
    res = a.allocate(scores, active=active, prev_weights={})
    w = [r.weight for r in res.values()]
    assert abs(sum(w) - 1.0) < 1e-6
    assert all(0.0 <= x <= 1.0 + 1e-9 for x in w)
    n = len(active)
    if n * cfg.cap >= 1 and n * cfg.floor <= 1:  # bounds feasible
        assert all(cfg.floor - 1e-6 <= x <= cfg.cap + 1e-6 for x in w)
