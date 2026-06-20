# Pre-Mortem — Multi-Bot Stock Trading System (design risk review)

- **Date:** 2026-06-19
- **Companion to:** `2026-06-19-multi-bot-trading-system-design.md`
- **Method:** Assume v1 shipped and lost money / failed. Work backward to the likely causes.
  Nothing is built yet, so this reviews the *design*. Each finding has a severity and a
  disposition: **Fixed** (spec changed, section noted), **Accepted** (known risk, documented),
  or **Deferred** (later phase).

Severity: **H** = could sink the project / lose real money · **M** = degrades results /
reliability · **L** = minor.

---

## A. The allocator (the novel core — highest concentration of risk)

**A1 — Reflexivity / performance-chasing (H).** Funding the recently-hottest bot is a momentum
bet on *strategy* returns. Short-horizon strategy PnL is often mean-reverting, so the allocator
can systematically buy high / sell low on strategies. This is the project's central, unproven
hypothesis.
→ **Fixed:** equal-weight is the null hypothesis; allocator must beat it out-of-sample (§6
Safeguards, §10, §18). Start `τ` high (near equal), tighten only on evidence (§17).

**A2 — Mean-reversion bots get defunded right before they pay (H).** Stat-arb and bot 5 take
adverse excursion *before* reverting. A short scoring window + drawdown penalty defunds them at
the worst moment.
→ **Fixed:** score on **closed-trade realized PnL** primarily; per-bot `score_half_life`
override (longer for MR bots) (§6 Safeguards).

**A3 — Sleeve shrink force-liquidates live theses (H).** If a bot's `capital_weight` drops, naive
implementation dumps its open positions mid-setup, realizing losses and breaking the strategy.
→ **Fixed:** sleeve shrink caps **new** exposure and draws from free cash first; existing
positions trimmed only if over the new cap, gradually via `Δ` (§6 Safeguards).

**A4 — `σ→0` score blow-up (M).** A barely-traded bot with tiny consistent gains posts a
near-infinite Sharpe and hogs capital.
→ **Fixed:** `min_trades`/`min_obs` gate, score winsorize/clip, variance floor (§6 Safeguards).

**A5 — All-negative regime keeps system fully deployed into losers (H).** Softmax always
allocates 100% somewhere, even when every bot is bleeding.
→ **Fixed:** risk-off de-gross — scale `deploy_fraction` toward cash when aggregate score < 0
or portfolio in drawdown; the system may choose *not* to trade (§6 Safeguards, §9).

**A6 — Aggressiveness × capital double-counts risk (M).** Hot bot gets more capital **and** lower
threshold **and** bigger size — compounding can over-lever it fast.
→ **Fixed:** aggressiveness operates strictly **within** hard §9 risk caps; no compounding past
bounds (§6 Safeguards).

**A7 — Reallocation churn cost (M).** Reshuffling every 15 min costs spread/slippage (and tax
live).
→ **Accepted/Mitigated:** `Δ` smoothing + no force-liquidation + free-cash-first (§6, §17).

---

## B. Backtest validity (where false confidence comes from)

**B1 — In-sample overfit (H).** Cointegration selection + parameter tuning on the same data you
report on guarantees inflated results.
→ **Fixed:** walk-forward, train/test split, OOS only (§10).

**B2 — Survivorship bias (M).** Current-symbols-only universe overstates stat-arb / cross-sectional
results (delisted losers excluded).
→ **Fixed:** survivorship-aware universe requirement (§10).

**B3 — Lookahead (H).** Deciding on a bar's close and filling at that same close is a silent
lookahead that fabricates edge.
→ **Fixed:** signals on **closed bars only**, fills on **next** bar (§10).

**B4 — Multiple-testing false cointegration (M).** Scanning many candidate pairs yields spurious
"cointegrated" pairs by chance.
→ **Fixed:** same-sector economic rationale + FDR/Bonferroni correction (§10).

**B5 — Decorrelation assumed, not measured (M).** ORB / VWAP / order-flow may all just react to the
same intraday moves, collapsing the diversity premise the allocator depends on.
→ **Fixed:** measure + report realized inter-bot correlation (§10).

**B6 — Bots 4 & 5 backtest low-fidelity (M).** Top-of-book history is thin; ICT micro-timing is
hard to replay.
→ **Accepted:** validate both primarily in **paper**, not backtest (§7, §10).

---

## C. Execution & market realism

**C1 — Slippage/impact model too simple (M).** `bps + half-spread` ignores impact when a bot holds
up to the 50% cap → large orders move price.
→ **Partially fixed:** §10 **participation cap (5%, tweakable) + partial fills + iterative carry**
model the *liquidity/quantity* limit (no infinite-liquidity fills, the #1 backtest lie). The
*price-impact* penalty ("heavy footprint") is **deferred** to Later.

**C2 — Short-sale realism (M).** Borrow availability, locate, hard-to-borrow fees; paper may permit
shorts live wouldn't.
→ **Fixed (v1 check) + Documented (live):** shortability check in §9; HTB/locate frictions in §17.

**C3 — Margin / leverage / margin call (M→H).** Naive leverage with no loss bound → margin-call
exposure (user-flagged).
→ **Fixed (loss-bounded leverage):** leverage allowed to **`max_gross_leverage` 1.5×** for
*exposure*, but **actual loss is capped** by **mandatory per-position stops** + a **portfolio-heat
cap** `total_open_risk = Σ(size × |entry − stop|) ≤ max_total_open_risk ≤ equity − maintenance
buffer` (the **solvency invariant**: the wallet never falls below `equity − Σ stops`, kept ≥ the
maintenance buffer → no margin call). Plus the hard **buying-power guard** (no new trades when
capital is exhausted; exits always allowed) and the **margin-utilization monitor** (§6, §9, §18).
PDT / GFV remain live-only notes (§17).

**C4 — Stops can slip / gap (M).** The solvency invariant assumes stops fill at their level; gaps
and fast markets (esp. overnight, and futures for bot 5) can fill worse, so realized loss can
exceed Σ stops.
→ **Accepted / Mitigated:** maintenance buffer below the heat ceiling, flat-by-EOD for equity
bots, and a conservative `max_total_open_risk` default (10%); residual overnight / futures gap risk
remains — sizing treats stops as approximate, not guaranteed.

---

## D. Operational / reliability

**D1 — Heavy compute stalls the async loop (H).** Daily cointegration refit and FVG/structure scans
can block the single event loop, starving the feed and risk monitors.
→ **Fixed:** run heavy compute in an executor, off the loop (§14).

**D2 — Crash attribution is hand-wavy (H).** "Best-effort" rebuild of per-bot books after a crash
corrupts scoring if the broker net can't be split back to bots.
→ **Fixed:** rebuild **exactly** from the persisted `positions` table; reconcile drift as a
logged adjustment (§14).

**D3 — No watchdog / dead-man switch (H).** If the engine hangs, positions sit unmanaged — the
classic algo-trading blow-up.
→ **Fixed:** heartbeat watchdog; on hang/feed-loss → cancel + (configurable) flatten (§14).

**D4 — Timezone/DST handling (M).** Sessions (Asia/London/NY-AM) and EWMA decay need consistent ET
+ DST handling or windows drift.
→ **Accepted/Documented:** all session math in ET via the trading calendar (§4, §12); called out
here as an implementation must-test.

---

## E. Strategy-specific

**E1 — Stat-arb spread blow-up (H).** Diverging spread is the classic stat-arb death.
→ **Fixed (already):** `z_stop`, max-hold, cointegration-break monitor, per-bot DD kill (§7, §9).

**E2 — Bot 5 may be under-specified (M).** "Daily bias / what you want price to do" is discretionary;
the mechanization is an approximation and could become a vague, unprofitable bot.
→ **Accepted/Documented:** explicit mechanical rules + heavy paper validation; riskiest bot,
its own phase (§7, §16).

**E3 — Bot 5 ultra-low frequency (M).** NY-AM-only → ~1.5h/day → sparse PnL → noisy allocator score.
→ **Accepted/Mitigated:** floor weight + cold-start neutral + per-bot `score_half_life` (§6, §17).

---

## F. Scope & process (will it ever ship?)

**F1 — Scope is large (H).** 5 bots + a novel allocator + backtest + live-ready infra is a lot;
projects like this stall in half-built complexity.
→ **Fixed (process):** strict phasing P0→P6; **validate the allocator with 2 bots (P1) before**
building all 5; expansion gated on the allocator beating equal-weight (§16, §18).

**F2 — No definition of done (M).** Without acceptance criteria, "working" is subjective and live
money creeps in prematurely.
→ **Fixed:** acceptance criteria / definition-of-done added (§18).

---

## Disposition summary

- **Fixed in spec:** A1, A2, A3, A4, A5, A6, B1, B2, B3, B4, B5, C2 (check), C3, D1, D2, D3, F1, F2.
- **Partially fixed:** C1 (quantity side via participation cap; price-impact deferred).
- **Accepted / documented:** A7, B6, C2 (live), C4, D4, E2, E3.
- **Already covered:** E1.
- **Deferred (later phases):** true L2 (bot 4), micro futures (bot 5), FRED regime filter,
  Kalman/GARCH/PCA — unchanged from the spec's Later list.

**Single biggest risk:** **A1 (allocator reflexivity).** The whole premise — "recent winner keeps
winning over the next interval" — may be false. Everything else is hygiene; this is the bet. The
fix is non-negotiable: prove it beats equal-weight out-of-sample before trusting it, and keep `τ`
near equal-weight until it does.

---

## Update (2026-06-19): Bot 5 deferred to a futures phase

Decision: **bot 5 is now futures-exclusive and ships dormant** (registered, inactive, zero
allocation) until a futures broker + data are integrated (Phase F). This **further reduces v1
scope** — v1 runs **4 active bots** — directly mitigating **F1 (scope)**. It also softens
**E2/E3** (bot 5's mechanization risk and ultra-low frequency are out of the v1 critical path)
and **removes the thin-equity extended-hours data concern** for bot 5, since index futures have
genuine ~23h Asia/London sessions. New allocator rule: **dormant bots get zero weight and are
excluded from renormalization** (design §6 Safeguards).
