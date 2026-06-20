# Backtest Findings — v1 (2026-06-20)

Iterative real-data backtesting of all bar-tradable strategies, to decide whether the system is
"ready as a whole." **Verdict: ready as sound, safe infrastructure — not as a profitable strategy.**

## Setup

- Real Alpaca IEX 1-minute bars, corporate-action adjusted. 4 symbols = 2 stat-arb pairs
  (KO/PEP, XOM/CVX), **102,554 bars**, ~3 months (2026-03-02 → 2026-06-13). Default config.
- Order-flow bot excluded from backtests — it needs quote/L2 data (not in historical bars); it is a
  **paper-only** validation (documented limitation).
- Harness: `scripts/eval.py` (fetch once → cache in `data/` → re-run offline).

## Results

| Config | fills | Sharpe* | max DD | turnover | allocator weights |
|---|---|---|---|---|---|
| solo statarb (2 pairs) | 265 | −1.35 | 2.5% | 21.8× | — |
| solo orb | 8 | −0.85 | 2.1% | 2.8× | — |
| solo vwap | 29 | −0.60 | 2.0% | 4.1× | — |
| combined | 887 | −0.22 | 3.9% | 73.5× | ~0.33 each |
| — third 1 | — | −0.38 | 3.9% | 73× | ~0.33 each |
| — third 2 | — | −1.04 | 3.9% | 47× | ~0.33 each |
| — third 3 | — | +0.36 | 2.5% | 75× | statarb **0.45** / orb 0.27 / vwap 0.27 |

\* annualized from minute returns — magnitudes are inflated; read signs/relatives, not absolutes.

Note: on a single pair (KO/PEP alone) combined Sharpe was **+2.3** — but that did **not** survive
adding a second pair (→ −0.22). The single-pair result was regime/luck, not edge.

## Findings

1. **No robust edge.** Single-pair positive Sharpe collapsed when a second pair was added; across
   pairs and sub-periods Sharpe spans −1.04 … +0.36. This is expected — these are textbook baseline
   strategies with default parameters, not researched alpha.
2. **The system is sound across every regime.** Drawdown stayed 2.0–3.9% (never tripped the 5%
   halt); leverage stayed within the 1.5× cap; every position carried a stop; attribution
   reconciled; runs are deterministic; all 99 unit tests pass. The risk machinery works.
3. **The allocator behaves correctly.** Under noisy/equal performance it defaults to ≈equal-weight
   — it does **not** chase noise into losers (exactly the A1-prescribed safe behavior). When a clear
   performer emerged (sub-period 3), it **did** differentiate (stat-arb → 0.45). So it is functional,
   not frozen; it simply has no real edge to exploit here.
4. **Turnover is high for stat-arb** (20–44×) — inherent to minute-bar pairs trading — and ~47–75×
   combined. Bounded (no blow-ups), but slippage is the dominant cost. A **rebalance deadband**
   (`execution.rebalance_deadband`, default 0.10) was added to stop per-bar micro-churn from
   equity-driven sleeve re-sizing.

## What was deliberately NOT done

**No parameter tuning to maximize backtest Sharpe.** That is precisely the in-sample overfitting the
pre-mortem forbids (B1) and the reflexivity trap (A1). Making these numbers "look good" by fitting
thresholds to KO/PEP would produce a fragile, dishonest result that fails live.

## Conclusion & recommendation

v1 is **ready as infrastructure**: a sound, safe, tested, deterministic multi-strategy engine with a
working meta-allocator and real risk controls. It is **not** a money-making strategy and must not be
deployed expecting profit.

Real next steps are **research, not more backtest tuning**:
- Better signals / features / strategy design (the actual source of edge).
- A **paper soak** to validate live execution + microstructure (especially the order-flow bot, which
  can't be backtested on bars).
- Walk-forward across **many** names and **years** before trusting any allocator edge — keep `τ` high
  (near equal-weight) until an edge is demonstrably real out-of-sample.
