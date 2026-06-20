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

Real next steps are **research, not more backtest tuning** (done below):
- Better signals / features / strategy design (the actual source of edge).
- A **paper soak** to validate live execution + microstructure (especially the order-flow bot, which
  can't be backtested on bars).
- Walk-forward across **many** names and **years** before trusting any allocator edge — keep `τ` high
  (near equal-weight) until an edge is demonstrably real out-of-sample.

---

# Signal Research — a real edge found (2026-06-20)

Proper cross-sectional research: 44 liquid names, **daily** bars, 2021-06 → 2026-06 (1265 days).
For each candidate signal: rank Information Coefficient (signal vs forward return, daily
cross-section) with an in-sample/out-of-sample split, plus a long-top / short-bottom decile
backtest. Harness: `scripts/signals.py`. This is research (does X predict returns?), not tuning.

| signal | IC t-stat (h=5) | IS→OOS IC | L/S Sharpe (IS/OOS) | verdict |
|---|---|---|---|---|
| rev_1d, rev_5d | <1 | sign **flips** | negative | dead |
| mom_3_1 | ~1 | mixed | ~0 | dead |
| mom_6_1 | 1.9 | stable + | +0.31 (0.13/0.59) | weak-positive |
| **mom_12_1** | **3.7** | **+0.033 / +0.033** | **+0.49 (0.13/1.00)** | **real** |
| **mom_12_1 vol-scaled** | **4.3** | **+0.039 / +0.030** | **+0.75 (0.64/0.91)** | **best** |
| lowvol_21d | −2.0 | unstable magnitude | negative | no |

**Finding:** cross-sectional **momentum** (12-1, skip the last month) is the one price-based signal
that is statistically significant *and* out-of-sample stable. Short-term reversal and low-vol fail
OOS. **Vol-scaling** momentum (divide by trailing return volatility, so you don't overload high-vol
names) improves it materially — t=4.3, L/S Sharpe +0.75, IS≈OOS. (Other signal families — earnings
drift, options flow, news/sentiment — need data the bars API doesn't provide; out of scope here.)

**Implementation:** `strategies/momentum.py` `CrossSectionalMomentumBot` — vol-scaled 12-1 momentum,
long top quintile / short bottom quintile, **equal-dollar** legs, wide 15% stops, rotates names as
they leave the deciles. Run through the **full system** (stops + sleeve sizing + risk overlay +
participation-capped fills + slippage) over 5 years / 44 names:

```
system momentum bot: daily Sharpe +0.55   max_drawdown 1.3%   turnover 4.0×
```

It captures most of the gross factor (+0.75 → +0.55 after frictions; momentum is slow so costs are
small) with very controlled risk.

## Updated verdict

v1 now ships a **validated edge** (vol-scaled cross-sectional momentum, Sharpe ~+0.55 through the
full system, OOS-validated) **plus a reusable signal-research harness**. The intraday textbook bots
remain edgeless — keep them for diversification/execution testing, not profit. Before real capital:
paper-soak, and note the momentum bot is a **daily** factor (run it on daily bars, not the intraday
loop). It's now runnable live: `traderbot momentum` (once-per-day rebalance vs the paper account).

---

# Intraday signal research — why the intraday bots have no edge (2026-06-20)

Setup: 12 diverse names (large-cap + high-vol + ETFs), **minute** bars, 3 months, **294k**
observations. Tested whether intraday moves predict forward moves (reversal IC: +reversion /
−momentum), with a time split and a volatility split, then the **decisive** test — per-trade gross
edge vs transaction cost. Harness: `scripts/intraday_signals.py`.

| horizon | reversal IC (pooled) | OOS sign | per-trade gross edge | vs ~2–4 bps cost |
|---|---|---|---|---|
| 5 min | +0.010 | stable | +0.1 bps | dead |
| 15 min | **+0.033** | +0.019 (stable) | +1.8 bps | **< cost → net negative** |
| 30–60 min (hi-vol) | −0.029 (momentum) | −0.015 (stable) | **+5.2 bps** | **> cost → net positive** |

**The real reason the intraday bots have no edge:** their signals are statistically real (significant
IC, OOS-stable), but the **per-trade edge is smaller than transaction costs**. High-frequency
mean-reversion (the VWAP/Bollinger premise) has a genuine +1.8 bps/15-min edge that is simply eaten
by ~2–4 bps of slippage. Only **lower-frequency, longer-hold** signals clear costs.

**The one intraday pattern worth adjusting for:** **momentum/continuation over ~30–60 min in
high-volatility names** (NVDA, TSLA, AMD, META, …) — +5.2 bps gross beats cost. That's the ORB bot's
premise; it failed only because it was tested on low-vol names (KO/PEP).

## How to adjust each bot

1. **VWAP / Bollinger reversion (5–15 min):** edge < cost → **not tradable retail** (needs
   rebates / HFT-grade costs). Relegate to experimental; don't deploy for profit.
2. **ORB / intraday momentum:** the logic (breakout = continuation) is right — fix the **universe**:
   run it on **high-volatility** names with ~30–60 min+ holds, where +5.2 bps clears costs. No edge
   on low-vol large-caps.
3. **Stat-arb (pairs):** same edge-vs-cost trap unless a pair is genuinely cointegrated *and* the
   spread move exceeds costs — rare. Keep only strongly-cointegrated pairs (the statsmodels gate
   helps); expect thin pickings.
4. **Order-flow:** needs L2 (untested here); microstructure edge is real but latency/cost-sensitive
   and likely retail-infeasible.

**Meta-lesson:** *edge must beat cost.* For retail costs, **low frequency wins** — daily momentum
(turnover ~4×, costs negligible, Sharpe +0.55) is the robust core; intraday is marginal at best, and
only longer-hold high-vol momentum survives.
