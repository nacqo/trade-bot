from traderbot.backtest.metrics import (
    equal_weight_benchmark,
    hit_rate,
    inter_bot_correlation,
    max_drawdown,
    sharpe,
)


def test_sharpe_sign_and_drawdown():
    assert sharpe([100, 101, 102, 103]) > 0      # steadily up
    assert sharpe([103, 102, 101, 100]) < 0      # steadily down
    assert max_drawdown([100, 90, 100]) == 0.10  # 10% trough


def test_hit_rate():
    assert hit_rate([100, 101, 100]) == 0.5  # one up, one down


def test_inter_bot_correlation_shape():
    corr = inter_bot_correlation({"A": [100, 101, 102, 103], "B": [100, 99, 98, 97]})
    assert corr.shape == (2, 2)
    assert abs(corr.loc["A", "A"] - 1.0) < 1e-9


def test_equal_weight_benchmark_length():
    bench = equal_weight_benchmark({"A": [0, 1, 2], "B": [0, -1, -2]}, starting_equity=100.0)
    assert len(bench) == 3
    assert bench[0] == 100.0  # both start at 0 PnL → starting equity
