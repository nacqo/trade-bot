"""EWMA risk-adjusted scoring per bot.

score = ewma_mean / (ewma_std + eps) − λ · drawdown, computed on the bot's interval returns.
Below `min_obs` observations a bot scores neutral (0.0) so it sits at the allocator floor
(cold-start), never zero-by-accident and never an outlier from one lucky tick.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class _BotState:
    n: int = 0
    mean: float = 0.0
    sq: float = 0.0  # EWMA of x^2
    cum: float = 0.0  # cumulative return
    peak: float = 0.0  # running peak of cumulative return


class BotScorer:
    def __init__(
        self,
        half_life_hours: float,
        drawdown_penalty: float,
        min_obs: int,
        eps: float,
        interval_minutes: int,
    ) -> None:
        self.lam = drawdown_penalty
        self.min_obs = min_obs
        self.eps = eps
        half_life_intervals = max(1e-9, half_life_hours * 60.0 / interval_minutes)
        self.alpha = 1.0 - 0.5 ** (1.0 / half_life_intervals)
        self._state: dict[str, _BotState] = {}

    def update(self, bot_id: str, interval_return: float) -> None:
        st = self._state.setdefault(bot_id, _BotState())
        a = self.alpha
        if st.n == 0:
            st.mean = interval_return
            st.sq = interval_return * interval_return
        else:
            st.mean = (1 - a) * st.mean + a * interval_return
            st.sq = (1 - a) * st.sq + a * interval_return * interval_return
        st.n += 1
        st.cum += interval_return
        st.peak = max(st.peak, st.cum)

    def score(self, bot_id: str) -> float:
        st = self._state.get(bot_id)
        if st is None or st.n < self.min_obs:
            return 0.0
        var = max(0.0, st.sq - st.mean * st.mean)
        std = math.sqrt(var)
        drawdown = st.peak - st.cum  # ≥ 0
        return st.mean / (std + self.eps) - self.lam * drawdown
