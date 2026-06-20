---
name: evaluation
description: Rank and rate every implemented trading strategy in this repo /100 with fresh real-data backtests, run the standard 2-month outcome simulation for each, and give improve/drop guidance. Use when the user asks to evaluate, rank, rate, score, or compare the strategies/bots, or asks which bot to drop.
---

# Strategy Evaluation

Produce a data-backed ranking of all currently-implemented strategies, each rated **/100**, proven
by a fresh backtest, plus the same 2-month outcome simulation used in `scripts/project.py`, plus
concrete guidance on improving each strategy or dropping one.

## How to run

1. Ensure `.env` has `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` (used only on first run to fetch +
   cache real bars into `data/`; later runs are offline).
2. Run the evaluation engine:

   ```bash
   .venv/bin/python scripts/evaluate.py
   ```

   It backtests **each** strategy on its appropriate real data through the full system
   (stops, sizing, risk, participation-capped fills, slippage):
   - `momentum` (cross-sectional) — 44 large-caps, daily, ~5y
   - `trend` (time-series) — 18 diversified ETFs, daily, ~6y
   - `stat-arb`, `orb`, `vwap` (intraday) — KO/PEP/XOM/CVX, 1-minute, ~3mo

## The rating rubric (/100) — keep transparent

- **Sharpe — 50 pts:** `clip(daily Sharpe, 0, 2) / 2 × 50` (Sharpe 2.0 → 50, 1.0 → 25, ≤0 → 0).
- **Drawdown control — 20 pts:** `20 × (1 − min(maxDD/25%, 1))`.
- **Cost / turnover — 15 pts:** `15 × (1 − min(turnover/80×, 1))` (low churn rewarded).
- **2-month positivity — 15 pts:** `15 × share of 2-month windows that were positive`.

## What to present to the user

1. **Ranking table** — strategy, rating/100, Sharpe, maxDD, turnover, fills.
2. **2-month simulation** — median / 10th–90th-pct $ change on $100k, and % of windows positive.
3. **Guidance** — per strategy: keep / improve (how) / drop. Call out the **recommended drop**
   (lowest rated) explicitly.
4. Note caveats: backtest ≠ future; ratings are relative; momentum/trend are daily factors;
   intraday ratings use a short (~3mo) window.

## Maintenance

When a strategy is added/removed, update the `configs` list and `GUIDANCE` dict in
`scripts/evaluate.py` so the evaluation stays complete.
