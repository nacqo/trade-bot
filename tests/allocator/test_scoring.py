from traderbot.allocator.scoring import BotScorer


def _cfg(**kw):
    base = dict(half_life_hours=4.0, drawdown_penalty=0.5, min_obs=30, eps=1e-8, interval_minutes=15)
    base.update(kw)
    return BotScorer(**base)


def test_cold_start_is_neutral():
    s = _cfg()
    for _ in range(29):  # below min_obs=30
        s.update("b1", 0.002)
    assert s.score("b1") == 0.0


def test_steady_positive_scores_positive():
    s = _cfg()
    for _ in range(60):
        s.update("b1", 0.002)
    assert s.score("b1") > 0.0


def test_volatile_scores_below_steady():
    s = _cfg()
    sign = 1.0
    for _ in range(60):
        s.update("vol", 0.02 * sign)
        sign *= -1
        s.update("steady", 0.002)
    assert s.score("vol") < s.score("steady")


def test_unknown_bot_is_neutral():
    assert _cfg().score("nope") == 0.0
