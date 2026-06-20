"""Meta-allocator. Turns per-bot scores into capital weights + aggressiveness.

weight = waterfill( softmax(score/τ) , floor, cap ), then max-step smoothed vs prev.
aggressiveness = clip(1 + k·z(score), aggr_min, aggr_max).

Dormant bots (not in `active`) are excluded entirely — zero weight, and the floor/cap/softmax
run over the active set only. Hard bounds (floor/cap, sum=1) always hold; max_step smoothing is
best-effort (a cap redistribution can move a bot more than one step).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from traderbot.config import AllocatorCfg


@dataclass(frozen=True)
class AllocResult:
    weight: float
    aggressiveness: float


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _waterfill(weights: dict[str, float], floor: float, cap: float) -> dict[str, float]:
    keys = list(weights)
    n = len(keys)
    eff_floor = floor if n * floor <= 1.0 else 1.0 / n
    eff_cap = cap if n * cap >= 1.0 else 1.0
    w = {k: max(weights[k], 0.0) for k in keys}
    if sum(w.values()) <= 0:
        w = {k: 1.0 for k in keys}

    fixed: dict[str, float] = {}
    for _ in range(2 * n + 2):
        remaining = 1.0 - sum(fixed.values())
        unfixed = [k for k in keys if k not in fixed]
        if not unfixed:
            break
        tot = sum(w[k] for k in unfixed)
        if tot <= 0:
            for k in unfixed:
                w[k] = remaining / len(unfixed)
        else:
            for k in unfixed:
                w[k] = remaining * w[k] / tot
        # Fix ONE violation per iteration (cap first), so a floored bot can still rise
        # to absorb budget freed by capping another bot.
        over = [k for k in unfixed if w[k] > eff_cap + 1e-12]
        under = [k for k in unfixed if w[k] < eff_floor - 1e-12]
        if over:
            k = max(over, key=lambda key: w[key])
            w[k] = eff_cap
            fixed[k] = eff_cap
        elif under:
            k = min(under, key=lambda key: w[key])
            w[k] = eff_floor
            fixed[k] = eff_floor
        else:
            break
    return w


class Allocator:
    def __init__(self, cfg: AllocatorCfg) -> None:
        self.cfg = cfg

    def allocate(
        self,
        scores: dict[str, float],
        active: set[str],
        prev_weights: dict[str, float],
    ) -> dict[str, AllocResult]:
        cfg = self.cfg
        ids = [b for b in scores if b in active]
        if not ids:
            return {}
        scs = {b: scores[b] for b in ids}

        # softmax over active scores
        vals = {b: scs[b] / cfg.tau for b in ids}
        m = max(vals.values())
        exps = {b: math.exp(vals[b] - m) for b in ids}
        z = sum(exps.values())
        soft = {b: exps[b] / z for b in ids}

        target = _waterfill(soft, cfg.floor, cfg.cap)

        if prev_weights:
            smoothed = {}
            for b in ids:
                p = prev_weights.get(b, 0.0)
                smoothed[b] = p + _clip(target[b] - p, -cfg.max_step, cfg.max_step)
            weights = _waterfill(smoothed, cfg.floor, cfg.cap)
        else:
            weights = target

        # aggressiveness from cross-sectional z-score of raw scores
        arr = [scs[b] for b in ids]
        mean = sum(arr) / len(arr)
        var = sum((x - mean) ** 2 for x in arr) / len(arr)
        std = math.sqrt(var)

        result: dict[str, AllocResult] = {}
        for b in ids:
            zsc = (scs[b] - mean) / (std + cfg.eps)
            aggr = _clip(1.0 + cfg.aggr_slope * zsc, cfg.aggr_min, cfg.aggr_max)
            result[b] = AllocResult(weight=weights[b], aggressiveness=aggr)
        return result
