# Multi-Bot Stock Trading System — Design Spec

- **Date:** 2026-06-19
- **Status:** Approved design (pre-implementation)
- **Market:** US equities (stocks only)
- **Execution target:** Paper trading first, live-ready architecture (Alpaca)

---

## 1. Overview

A single program that runs **five independent trading bots**, each using a different
strategy, over US stocks. In v1, **four bots are active**; **bot 5 (futures-exclusive) ships
dormant** and activates only once futures support is built (see §16). A **meta-allocator** continuously measures each bot's recent
risk-adjusted performance and dynamically gives the better-performing bots **more capital
and a looser leash to trade** (lower signal threshold + larger size), while throttling the
laggards — subject to an always-on risk overlay. The whole system runs against Alpaca's
paper account first, with an architecture that flips to live with a config change.

The novel core is the **meta-allocator**: "whichever bot has earned the most recently
controls the most money." Everything else (data, strategies, execution, risk) exists to
serve and constrain that idea.

---

## 2. Goals & non-goals

### Goals (v1)
- Run **4 active** decorrelated strategy bots on Alpaca paper; a 5th (futures-only) bot is
  registered but **dormant** until futures support lands.
- A meta-allocator that ranks bots on rolling risk-adjusted PnL and sets per-bot
  `capital_weight` + `aggressiveness_multiplier`.
- Always-on risk overlay (per-bot + portfolio + order-level + kill-switch).
- Deterministic backtest harness reusing the same strategy/allocator/risk code.
- Clean per-bot PnL attribution.
- Live-ready: switching paper→live is a config flag, not a rewrite.

### Non-goals (v1)
- No live real-money trading yet (architecture ready, not switched on).
- No futures broker in v1 → **bot 5 stays dormant** (it trades futures exclusively).
- No web UI (structured logs + a `status` CLI command only).
- No deep L2 / full order-book strategies (top-of-book only; Polygon upgrade later).
- No multi-process / service-per-bot isolation (monolith now, splittable later).
- No ML/factor models in v1 (PCA/GARCH/Kalman are documented as later upgrades).

---

## 3. Decisions log (resolved, with rationale)

| Decision | Choice | Why |
|---|---|---|
| Execution mode | **Paper first, live-ready** | Validate end-to-end with zero capital at risk; live = config flip later. |
| Broker + data | **Alpaca** (`alpaca-py`) | Free paper + live US stocks, simple REST+websocket, shorting on easy-to-borrow names, market data included. |
| Allocator shape | **Softmax(score/τ) + floor + cap + max-step smoothing** | One temperature knob `τ` spans winner-take-most ↔ proportional ↔ equal, so the aggressiveness choice becomes a tunable, not a hard commitment. Floor lets a cold bot recover; cap prevents blow-up concentration; smoothing kills whipsaw. |
| Performance metric | **Risk-adjusted (rolling Sharpe-like), drawdown-penalized** — not raw PnL | Raw PnL rewards a lucky high-variance bot; user requirement is "always calculating risk." |
| Lookback | **EWMA with configurable half-life (default ~4h, tunable to 3h)** | User flagged a hard 3h window as "too aggressive." EWMA is smoother and leakier than a hard cutoff. |
| Number of bots | **5 (max regime diversity)** | Bots 1–4 span mean-reversion / trend / reversion / microstructure; bot 5 adds a session/liquidity (ICT) model on a different cadence. Something is usually working for the allocator to shift toward. |
| Bot 5 instruments | **Futures-exclusive (MES/MNQ micros); DORMANT until futures support** | Bot 5 trades **only** index futures (the authentic ICT instrument; SMT = ES vs NQ). Alpaca has no futures, so bot 5 ships **registered but inactive** and activates only when a futures broker (IBKR/Tradovate) + futures data are integrated (Phase F). Micros (MES/MNQ) because full ES/NQ ≈ $280k/$400k won't fit a sliced account. |
| Architecture | **Monolithic async (Approach A)** | Right-sized for retail paper; the custom meta-allocator gains little from a framework and would fight its assumptions; clean interfaces keep units testable and the live↔backtest swap trivial. |
| PnL attribution | **Virtual per-bot books + netted real execution** | Broker holds only the net account, so virtual books are required for clean per-bot scoring; netting before sending orders avoids wasteful offsetting trades. |
| Language | **Python** | Quant default; `alpaca-py`, `statsmodels`, `pandas-ta` ecosystem. |

---

## 4. Architecture (Approach A — monolithic async)

Single Python process, one async event loop, clean internal interfaces so each unit is
testable in isolation and the data source can be swapped (live Alpaca ↔ historical replay)
behind the same boundary.

### Modules

- **`data/`** — Feed manager: Alpaca websocket (bars, quotes, trades) + historical loader.
  Normalizes everything into one **MarketData bus** interface. The backtest replay source
  implements the *same* interface. **Applies corporate-actions adjustment** (splits/divs)
  so price series are continuous. Uses a **trading calendar** to gate session state.
- **`strategies/`** — `Strategy` base class + 4 implementations. Each consumes market data
  and emits **target positions** (`symbol → desired qty`) plus a **signal strength**
  (normalized confidence). No direct broker access — pure and unit-testable.
- **`allocator/`** — The meta-controller. Maintains each bot's virtual-book equity curve,
  computes rolling risk-adjusted scores, and emits `capital_weight` + `aggressiveness_multiplier`
  per bot every `T_rebal`.
- **`execution/`** — OMS. Scales each bot's targets by its sleeve (`capital_weight`) ×
  `aggressiveness`, **nets across bots** into a net desired position per symbol, diffs vs
  the broker position, submits orders to Alpaca, records fills, and updates virtual books
  with per-bot attribution.
- **`risk/`** — Pre-trade checks + continuous monitors + kill-switches. Authority to veto
  orders, flatten a bot, or halt the whole system.
- **`state/`** — SQLite persistence: fills, positions (virtual books), per-bot equity,
  allocator decisions, orders, risk events, config snapshots. Enables attribution and
  crash recovery.
- **`engine/`** — Async event loop wiring all of the above; lifecycle, market-hours +
  rebalance scheduling, graceful shutdown, per-bot exception isolation.
- **`backtest/`** — Historical replay harness; runs the full engine over history with a
  simulated fill model; emits equity curves + metrics.
- **`config`** — One typed config object (pydantic): keys, universe/pairs, allocator
  params, risk limits, capital.
- **`cli`** — Entry points + structured logging + a `status` command (weights, positions,
  per-bot PnL).

### Strategy interface (conceptual)
```
class Strategy:
    id: str
    def on_market_data(self, md) -> None: ...        # update internal state
    def target_positions(self) -> dict[str, float]:  # symbol -> desired qty (signed)
    def signal_strength(self) -> float:              # 0..1 normalized confidence
```
`aggressiveness_multiplier` is applied by the engine/execution layer (it lowers each bot's
effective entry threshold and scales its target size), so a bot stays unaware of allocation.

---

## 5. Data flow (one loop)

1. Feed manager streams Alpaca data → MarketData bus (corporate-action-adjusted, calendar-gated).
2. Each bot consumes relevant data → emits target positions + signal strength.
3. **Allocator** (every `T_rebal`, default 15 min) updates `capital_weight` +
   `aggressiveness` per bot from rolling risk-adjusted virtual-book PnL.
4. **Execution** scales each bot's targets by sleeve × aggressiveness, nets across bots →
   net target per symbol → order diff → Alpaca.
5. Fills update broker positions and **per-bot virtual books** (attribution) in state.
6. **Risk** monitors run continuously; any breach → throttle / flatten bot / global halt.
7. Repeat.

---

## 6. Allocator design (the core)

Computed per bot *i*, updated every `T_rebal`.

### Score (risk-adjusted, rolling)
- `r_i(t)` = return of bot *i*'s **virtual book** over the interval.
- EWMA mean `μ_i` and EWMA variance `σ²_i` with **half-life `H`** (config; default ~4h).
- **Score:** `s_i = μ_i / (σ_i + ε) − λ · drawdown_i`
  - `μ_i / (σ_i + ε)` = rolling Sharpe-like ratio.
  - `λ · drawdown_i` = penalty on the bot's recent peak-to-trough drawdown.
- **Cold start:** if a bot has `< N` observations, assign a neutral (median) score so it
  receives the **floor** weight, never zero — it can earn its way up.

### Weights (softmax + floor/cap + smoothing)
- `w_raw = softmax(s / τ)` over the bots.
  - **`τ` = temperature** — the single aggressiveness dial: `τ→0` ⇒ winner-take-most;
    mid ⇒ proportional; large ⇒ near-equal.
- Apply **floor `f`** and **cap `c`** via iterative water-filling (clamp out-of-bound
  weights, renormalize the rest, repeat) so `Σw = 1` while respecting both bounds.
- **Smooth:** `w_t = w_{t-1} + clip(w_target − w_{t-1}, −Δ, +Δ)`, with `Δ` = max weight
  change per rebalance → anti-whipsaw, limits churn/cost.

### Two outputs per bot
- `capital_weight_i = w_i × deployable_capital` — the bot's sleeve. `deployable_capital` =
  account equity × `deploy_fraction` (config, default 1.0; a value < 1.0 holds cash back as
  a portfolio-level buffer).
- `aggressiveness_i = clip(1 + k · z(s_i), a_min, a_max)` — hot bot gets a lower effective
  entry threshold + larger size; cold bot gets stricter + smaller. (`z(s_i)` = cross-bot
  standardized score.) **This is the "more lenient to make trades" behavior.**

### Cadence
Recompute every `T_rebal` (default 15 min). Between rebalances, bots trade within their
current sleeve and aggressiveness. Rebalancing on a timer (not per-tick) avoids churn.

### Safeguards (pre-mortem hardening)
- **Sleeve shrink ≠ forced liquidation.** A reduced `capital_weight` first caps **new**
  exposure and draws the sleeve down from **free cash / unused room**; existing positions are
  trimmed only if they exceed the new sleeve, and gradually (within `Δ`) — the allocator never
  dumps a bot's live thesis at a loss mid-setup.
- **Score guards.** Require `min_trades` / `min_obs` before a bot may exceed floor weight;
  **winsorize/clip** scores and apply a **variance floor** so a barely-traded bot can't post a
  near-infinite Sharpe and hog capital (the `σ→0` case, beyond `ε`).
- **Mean-reversion fairness.** Mean-reverting bots (stat-arb, bot 5) take adverse excursion
  *before* paying off, so a short window can defund them right before they revert. Scoring uses
  **closed-trade realized PnL** as the primary signal (open marks secondary), and each bot may
  set a **per-bot `score_half_life`** (longer for MR bots) overriding the global `H`.
- **Risk-off de-gross.** If the aggregate score is negative (all bots cold) or the portfolio is
  in drawdown, the allocator scales **`deploy_fraction` down toward cash** instead of merely
  reshuffling capital among losers — the system is allowed to *not* trade. It also de-grosses
  when **margin utilization** nears the maintenance buffer, or when `total_open_risk` approaches
  `max_total_open_risk` (the portfolio-heat cap) — de-risking before any margin call (§9).
- **Aggressiveness is bounded by hard risk caps.** `aggressiveness_multiplier` lowers thresholds
  and scales size **only within** the §9 limits; it can never push a bot past its per-bot or
  portfolio caps (no capital × aggressiveness compounding past the hard bounds).
- **Equal-weight is the null hypothesis.** The dynamic allocator must **beat an equal-weight
  baseline** out-of-sample (§10); if it doesn't, it defaults to equal-weight (`τ` large).
- **Dormant bots are excluded from allocation.** A disabled/inactive bot (e.g. bot 5 before
  futures support) receives **zero** weight — not the floor — and softmax/floor/cap run over the
  **active** set only (weights renormalize to active bots). Activating a bot adds it to the pool.

---

## 7. The four strategies

All emit target positions + signal strength; all operate on Alpaca data; defaults in §12.

### Bot 1 — Statistical arbitrage, pairs (mean-reversion, market-neutral) — required
- **Universe:** configurable candidate same-sector pairs (e.g. KO/PEP, V/MA, XOM/CVX,
  GOOGL/GOOG).
- **Periodic (daily refit):** Engle–Granger cointegration test over a rolling lookback;
  keep pairs with `p < p_thresh`; estimate hedge ratio `β` via OLS (Kalman dynamic β is a
  later upgrade).
- **Live:** `spread = P_A − β·P_B` → rolling z-score. Enter when `|z| > z_in` (dollar-neutral
  legs: short the rich leg, long the cheap leg). Exit when `|z| < z_out`. Stop when
  `|z| > z_stop` (cointegration breaking) or max-hold time elapsed.
- **Corporate actions matter most here:** unadjusted splits/divs create false spread jumps;
  the data layer must feed adjusted prices.
- **Signal strength:** normalized `|z|`.

### Bot 2 — Opening Range Breakout / intraday momentum (trend)
- **Opening range:** high/low of the first `N` minutes of the session per watchlist symbol.
- **Entry:** break above OR-high → long; below OR-low → short; optional volume confirmation.
- **Exit:** opposite side of range or ATR-based stop; trailing/target; **flat by EOD**.
- **Signal strength:** breakout magnitude / ATR.

### Bot 3 — VWAP / Bollinger reversion (single-name reversion)
- **Indicators:** session VWAP + Bollinger bands (e.g. 20-bar, 2σ) per watchlist symbol.
- **Entry:** price ≥ upper band **and** far above VWAP → short (fade); ≤ lower band **and**
  far below VWAP → long.
- **Exit:** revert to VWAP / mid-band, or stop beyond band + buffer, or time stop.
- **Signal strength:** deviation in σ units.

### Bot 4 — Order-flow imbalance (microstructure)
- **Inputs:** Alpaca **top-of-book quotes + trade tape** (NOT full L2 depth).
- **Signal:** rolling `imbalance = (bidSize − askSize)/(bidSize + askSize)` + signed
  trade-flow (tick-rule / quote classification) over a short window (seconds–minutes).
- **Entry:** strong positive imbalance + buying pressure → brief long; strong negative →
  short. Very short holding; tiny target / tight stop / time exit.
- **⚠️ Limitation:** top-of-book only on Alpaca's free feed — this is a light order-flow
  proxy, not institutional depth. Backtest fidelity is limited (see §10); validate mainly
  in paper. True L2 = Polygon upgrade (later).
- **Signal strength:** `|imbalance| × flow`.

### Bot 5 — "General trading" (ICT session / liquidity model; discretionary → mechanized)

A multi-confluence ICT-style model: map higher-timeframe liquidity + bias, wait for a key
level to be hit, confirm a lower-timeframe reversal, enter on a continuation pattern, and
manage with a take-profit ladder. Trades **only** the **New York AM session**.

- **Trading window (hard constraint):** bot 5 opens positions **only** during the NY-AM
  window (09:30–11:00 ET, config). Asia/London/HTF levels are **analysis inputs only** — they
  shape bias and targets but never trigger entries outside NY-AM. Positions go **flat at NY-AM
  session close** (`flat_at_session_close`, default true; set false to let already-entered
  trades run to TP/stop past the window).
- **Status: DORMANT until futures support.** Bot 5 trades **futures exclusively** and Alpaca has
  no futures, so it ships **registered but inactive** (emits no orders, gets zero allocation)
  until a futures broker + data are integrated (Phase F, §16). No ETF version — it does **not**
  trade SPY/QQQ.
- **Instruments (when active):** **MES / MNQ** micro futures (Micro E-mini S&P 500 / Nasdaq-100)
  on a futures broker (IBKR/Tradovate). Micros because full ES/NQ (≈$280k/$400k) won't fit a
  sliced account. SMT divergence pair = **ES vs NQ** (MES vs MNQ).

**Step 1 — HTF bias & liquidity map (1h / 4h / daily):**
- **Session highs/lows:** Asia + London prior-session extremes (windows in ET, config).
- **1h & 4h swing highs/lows.**
- **1h & 4h Fair Value Gaps (FVG):** 3-bar imbalance (bullish: bar1.high < bar3.low; bearish:
  inverse), tracked filled/unfilled.
- **Draw on liquidity (DOL) / daily bias — mechanized:** identify external liquidity (prior
  session highs/lows, relative equal highs/lows, untested HTF FVGs); bias = direction toward
  the nearest *unmitigated* opposing pool given where price sits in the dealing range. (The
  hardest concept to mechanize — v1 is a rule-based approximation of discretionary bias.)

**Step 2 — wait for a key level to be hit:**
- Monitor price reaching any Step-1 level. If none are hit, drop to **15m / 5m** levels.
- **Invalidation:** if London already swept an Asia-session level, that Asia level is marked
  taken and ignored.

**Step 3 — LTF reversal confirmation (5m / 1m):** require one or more of —
- **Inverse FVG (IFVG):** a prior FVG price closes through, flipping its polarity.
- **Break of Structure / market-structure shift:** break of the most recent LTF swing in the
  new direction.
- **0.79 Fibonacci (OTE):** the 79% retracement of the LTF leg as the confluence zone.
- **SMT divergence:** ES vs NQ (MES vs MNQ) disagree at the level (one makes the new high/low,
  the other fails).

**Step 4 — entry on LTF continuation (5m / 1m):** enter (limit) at a fresh —
- **FVG**, **equilibrium** (50% of the dealing range), **breaker block** (failed OB that
  flips), or **order block** (last opposing candle before the impulse).

**Step 5 — management:**
- **TP ladder:** multiple take-profits at Step-1 key levels + unfilled 15m / 1h / 4h FVGs.
- **Break-even stop:** when the first TP fills, move the stop to entry.
- **Stop:** beyond the invalidating OB / structure / swing.

**Signal strength:** count of confirming confluences (Steps 3 + 4), normalized.

**⚠️ Bot-5 notes:** (a) **Dormant in v1** — activates only with futures support (Phase F, §16).
(b) ICT is discretionary — the mechanization is an approximation, bias/DOL especially. (c) On
**futures**, Asia/London are *real* liquid sessions (futures trade ~23h), so the thin-equity
extended-hours problem disappears — a reason ICT fits futures better than ETFs. (d) It is **the
most complex bot** and the only one needing **scaled-exit + breakeven-stop order choreography**
(§8) plus **futures contract / rollover / margin** handling — so it lands in the futures phase.

**Why these five:** bots 1–4 (active in v1) span mean-reversion (1), trend (2), reversion (3),
and microstructure (4); bot 5 (dormant until futures) adds a session-based multi-confluence /
liquidity model on futures, on a different cadence (a few high-quality NY-AM setups per day).
Decorrelated enough that different regimes favor different bots — which is what gives the
allocator something meaningful to shift toward once bot 5 is live.

---

## 8. Virtual books + netted execution (attribution)

The Alpaca account holds only the **net** position. Therefore:

- Each bot keeps a **virtual book**: its own intended positions, marked to market
  independently. The allocator scores these virtual books → clean per-bot attribution.
- **Execution nets** all bots' scaled targets into a single net desired position per symbol
  before sending orders → avoids sending offsetting trades (e.g. bot A wants +100 AAPL while
  bot B wants −100 AAPL nets to 0 real shares, but both virtual books still record their
  intent for scoring).
- Reconciliation each cycle: sum of virtual books should reconcile to the broker net
  position; drift triggers an alert + reconcile.

This keeps scoring correct (virtual) while keeping real order flow cheap (netted).

**Exit choreography (required by bot 5):** entries follow the net-target model above, but a
bot may also emit an **exit plan** — a take-profit ladder + a stop, with rules like
move-stop-to-breakeven on first TP fill. Execution manages these as **bracket / OCO orders**
at Alpaca (supported) on a per-bot basis. The net-target model governs *position level*; the
exit plan governs *scale-out choreography*. Bots 1–4 use simple targets; bot 5 uses the full
exit plan (built in the futures phase, with bot 5).

**Participation cap + partial fills (live & backtest).** Execution never sends (or simulates) a
fill larger than `participation_cap` of available volume; oversized orders fill partially and the
**remainder carries to the next interval and re-checks the cap**, iterating until filled or
expired (`participation_ttl`). Partial fills are attributed **pro-rata** across the bots whose
targets formed the net order. Live, this is a participation / POV-style guard against moving the
market (and taking bad fills); in backtest it is the fill-realism model of §10. One shared
`participation_cap` config governs both. Every order — and every carried remainder — also passes
the **buying-power guard** (§9): if free capital is exhausted it is rejected, never funded with
borrowed money. Carried **entry** remainders are **re-validated** by the bot before each
next-interval slice — if the edge is gone (price moved past where risk is justified) the leftover
is cancelled rather than chased; exit remainders always complete.

---

## 9. Risk overlay (always on; all values are config defaults)

- **Per-bot:** gross ≤ its `capital_weight` sleeve; max per-symbol % of sleeve; intraday
  drawdown kill (e.g. −2% of sleeve → flatten the bot + suspend it until next session).
- **Portfolio — exposure vs. loss are two separate caps:**
  - **Exposure:** **`max_gross_leverage` default `1.5×`** equity — leverage *is* allowed, because
    actual loss is bounded by stops (below), not by notional; `|net|` ≤ `0.3×` equity (roughly
    neutral).
  - **Loss / "portfolio heat":** **every open position has a hard stop**, and the sum of all
    per-position risk-to-stop — `total_open_risk = Σ(size × |entry − stop|)` — is capped at
    **`max_total_open_risk`**. No order may open or increase a position that would push
    `total_open_risk` over the cap (admission control).
  - **Solvency invariant:** `max_total_open_risk ≤ equity − maintenance_buffer`. So even if
    **every stop triggers at once**, the **wallet never falls below `equity − Σ stop-losses`,
    and that floor stays ≥ the maintenance buffer → no margin call.**
  - ⚠️ **Gap caveat:** stops are not guaranteed at their level — gaps / fast markets (overnight,
    futures) can fill worse, so the invariant is Reg-T-strong, not absolute; the buffer +
    flat-by-EOD mitigate, overnight/futures gap risk is residual.
  - total intraday drawdown halt (−5% equity → flatten everything, stop).
- **Hard buying-power guard (no over-spend):** every new or exposure-*increasing* order is
  pre-checked against **available buying power**; if free capital is exhausted the order is
  **rejected — no new trades**. The system never borrows past `max_gross_leverage` to enter.
  Exposure-*reducing* orders (exits, trims) are always allowed — they free capital.
- **Margin-call avoidance:** a monitor tracks margin utilization vs the broker maintenance
  requirement; as equity nears the **`maintenance_margin_buffer`** the allocator de-grosses
  toward cash (§6), and on breach it **halts + flattens** — de-risking *before* a margin call,
  not after.
- **Order-level:** max order notional; **limit orders with a price collar** (never naked
  market orders that can run away); **shortability check** (skip/flag non-shortable
  symbols); no new entries in the last `X` minutes; flat by EOD in v1; **bracket / OCO +
  breakeven-stop** support for bot 5's TP-ladder exits (added in the futures phase);
  **participation cap** — never exceed `participation_cap` (≈5%) of candle / recent volume,
  carrying any remainder to the next interval.
- **Kill-switch:** a global `halt` flag (cancel all + flatten + stop) trippable by a monitor
  or manually via CLI.
- **PDT note:** pattern-day-trader rule is flagged for the live phase; paper ignores it.

The risk layer has veto authority over execution and runs independently of allocation, so
"always calculating risk" holds regardless of which bot is hot.

---

## 10. Backtest harness

- Replays Alpaca historical bars (and quotes where available) through the **same MarketData
  interface** used live → strategies/allocator/risk code is identical in both modes.
- **Simulated fills (volume-aware):** fill at next-bar open with a slippage model
  (bps + half-spread); commission configurable (Alpaca stock commission = $0).
- **Participation cap ("speed limit"):** a fill may never exceed **`participation_cap`**
  (default **5%**, tweakable) of the **actual traded volume** of the candle it fills in. No
  infinite-liquidity fills at the candle price.
- **Partial fills + iterative carry ("leftovers"):** if an order exceeds the cap, only the
  capped quantity fills; the **remainder carries to the next candle and re-runs the same cap
  check**, repeating candle-by-candle until filled or **expired** (`participation_ttl`, default
  end-of-session → cancel remainder). E.g. a 20%-of-volume order fills 5% + 5% + 5% + 5% across
  four candles, never 5% then 15%. The model never reports a fill it couldn't have gotten.
- **Re-validate between carry steps (entries):** before filling each next-candle slice of a
  carried **entry**, the originating bot **re-checks its signal** — if price has moved past where
  the risk is justified (the entry edge is gone), the **remaining leftover is cancelled**, not
  chased (e.g. enter at €100, a fill at 101 is still fine, but at 102 the edge is gone → stop).
  Exposure-*reducing* carries (exits) always complete — getting flat isn't signal-dependent.
  Config `revalidate_on_carry` (default on).
- **Double-check (invariant):** every simulated fill asserts `filled ≤ participation_cap ×
  candle_volume`; a property test enforces it (§15). Partial fills are attributed back to bots
  **pro-rata** to their share of the netted order.
- **No lookahead:** the signal is decided on prior closed bars; the cap uses the volume of the
  candle the fill actually occurs in, never a future candle.
- **Output:** per-bot + portfolio equity curves, allocator weight history, and metrics
  (Sharpe, max drawdown, turnover, hit rate) via `quantstats`/`empyrical`.
- **Deterministic** (seeded), same interfaces as live.
- **⚠️ Bot 4 caveat:** historical top-of-book/trade granularity from Alpaca is limited, so
  the order-flow bot's backtest is lower-fidelity — validate it primarily in paper.

### Validity rules (pre-mortem hardening)
- **Walk-forward / out-of-sample only.** Cointegration selection and all parameter tuning happen
  on a **train** window; performance is measured on a **later test** window (rolling
  walk-forward). In-sample results are never trusted.
- **No lookahead.** Signals computed on **closed bars only**; fills on the **next** bar. No
  same-bar close-decide-and-fill.
- **Survivorship-aware universe.** Include delisted/changed symbols where possible; a
  current-symbols-only universe overstates stat-arb and cross-sectional results.
- **Multiple-testing control.** Pair selection scans many candidates → spurious cointegration;
  require same-sector rationale **and** an FDR/Bonferroni-style correction.
- **Allocator value test.** Report the dynamic allocator vs an **equal-weight baseline** and vs
  each bot standalone; it must add risk-adjusted value out-of-sample or default to equal-weight.
- **Inter-bot correlation is measured, not assumed.** Report realized return correlation across
  the active bots; if two collapse together, the diversity premise (and allocator usefulness)
  weakens.

---

## 11. State schema (SQLite)

| Table | Purpose |
|---|---|
| `fills` | ts, bot_id, symbol, side, qty, price, order_id |
| `positions` | virtual-book snapshots: bot_id, symbol, qty, avg_price, ts |
| `bot_equity` | ts, bot_id, realized, unrealized, equity — feeds rolling scoring |
| `allocations` | ts, bot_id, score, weight, capital, aggressiveness — decision log |
| `orders` | ts, order_id, bot_id(s), symbol, type, qty, status |
| `risk_events` | ts, type, detail |
| `config_snapshots` | ts, json — reproducibility |

Enables PnL attribution and crash recovery (rebuild virtual books on restart).

---

## 12. Configuration (defaults)

Single typed (pydantic) config. Defaults — all tunable:

**Account / data**
- `capital`: Alpaca paper default (~$100k); `deploy_fraction`: 1.0 (cash buffer if <1.0);
  `feed`: IEX (free) v1, SIP later; `bar`: 1 min.

**Allocator**
- `H` (EWMA half-life): 4h · `τ` (temperature): 0.5 · `f` (floor): 0.05 · `c` (cap): 0.50 ·
  `Δ` (max step/rebalance): 0.10 · `T_rebal`: 15 min · `λ` (drawdown penalty): 0.5 ·
  `N` (cold-start obs): 30 · `a_min/a_max`: 0.5 / 2.0 · `k` (aggressiveness slope): 0.5 · `ε`: 1e-8.

**Risk**
- per-bot DD kill: −2% sleeve · **`max_gross_leverage`: 1.5× (leverage allowed; loss bounded by
  stops)** · `|net|` cap: 0.3× · **`per_trade_risk`: 1% equity** (stop-distance position sizing) ·
  **`max_total_open_risk`: 10% equity** (portfolio-heat cap; hard ceiling = equity −
  `maintenance_margin_buffer`) · **mandatory stop on every position** · total DD halt: −5% · max
  order notional: 5% equity · no-entry window: last 15 min · flat EOD · `maintenance_margin_buffer`.

**Execution / fills**
- `participation_cap`: 0.05 (5% of candle / available volume — **tweakable**) ·
  `participation_ttl`: end-of-session (then cancel remainder) · partial-fill attribution:
  **pro-rata** across contributing bots · slippage: bps + half-spread · **buying-power guard: ON**
  (reject new/increasing orders beyond available buying power; carried remainders re-check it) ·
  `revalidate_on_carry`: on (re-check the entry signal before each carried slice; cancel the
  leftover if the edge is gone; exits always complete).

**Bot 1 (stat-arb):** cointegration lookback 60d · `p_thresh` 0.05 · `z_in` 2.0 · `z_out` 0.5 ·
`z_stop` 3.5 · max-hold 1 day · refit daily.
**Bot 2 (ORB):** opening range `N` 30 min · ATR stop · flat EOD.
**Bot 3 (VWAP/BB):** 20-bar, 2σ · entry σ threshold tunable.
**Bot 4 (order-flow):** imbalance window 30s–2min · `|imbalance|` threshold 0.3 · tight stop / tiny target.
**Bot 5 (general/ICT) — DORMANT until futures (`enabled: false`):** instruments **MES/MNQ micro
futures only** (SMT = ES vs NQ) · **trades only NY-AM 09:30–11:00 ET (entries gated; Asia
18:00–00:00 & London 02:00–05:00 are analysis inputs only)** · `flat_at_session_close` true ·
HTF {1h,4h,daily} · LTF {1m,5m,15m} · FVG 3-bar · OTE 0.79 · TP ladder + unfilled FVGs · BE
stop on first TP fill. Activates only when a futures broker + data are integrated (Phase F).

---

## 13. Dependencies

**v1 core**
- `alpaca-py` — broker + market data (REST + websocket).
- `statsmodels` — cointegration (Engle–Granger/Johansen), OLS hedge ratio.
- `pandas-ta` — VWAP, Bollinger, ATR, RSI (pure-python; no TA-Lib C build).
- `pandas_market_calendars` — NYSE hours / holidays / half-days (engine session gating).
- `quantstats` / `empyrical` — backtest performance metrics.
- `pandas`, `numpy`, `scipy` — data + math.
- `pydantic` — typed config.
- `aiosqlite` (or `sqlite3`) — state store.
- `structlog` — structured logging.

**Dev only**
- `yfinance` — free historical for offline pair/universe selection + research (not in live path).
- `pytest`, `pytest-asyncio`, `hypothesis` — tests (incl. property tests).

**Later (documented, not v1)**
- `filterpy` — Kalman dynamic hedge ratio β (stat-arb upgrade).
- `arch` — GARCH volatility for sharper risk-adjusted scoring.
- `scikit-learn` — PCA for factor-residual stat-arb variant.
- **Polygon.io** — true L2 depth (real order-flow) + richer history.
- **Alpaca News API** (Benzinga) — enables a future sentiment bot (#5).
- **FRED** — macro series for a regime filter (risk-off → cut gross exposure).

---

## 14. Error handling / resilience

- **Feed disconnect:** auto-reconnect with backoff; stale feed beyond threshold → pause new
  entries (hold/flatten per policy).
- **Broker API errors:** idempotent retry using client order IDs; persistent failure → risk halt.
- **Partial fills:** reconcile virtual books vs broker positions each cycle; drift → alert + reconcile.
- **Crash recovery:** on restart, reload positions from broker + state store, rebuild virtual
  books (best-effort attribution), resume.
- **Market state:** trade only during RTH (calendar-driven); skip halted/auction symbols.
- **Per-bot isolation:** a bot raising an exception is caught and isolated — it never crashes
  the engine or the other bots.
- **Exact crash recovery:** rebuild virtual books from the **persisted `positions` table** (not
  best-effort); reconcile any broker-vs-virtual drift as an explicit logged adjustment.
- **Heavy compute off the loop:** cointegration refits and FVG/structure scans run in a worker
  (executor), never blocking the feed / risk / event loop.
- **Watchdog / dead-man switch:** a heartbeat monitors the loop + feed; on hang or feed loss
  beyond threshold → cancel working orders and (configurable) flatten, so positions are never
  left unmanaged.
- All exceptions logged structured.

---

## 15. Testing strategy (TDD throughout)

- **Unit:** each strategy on synthetic data → deterministic signals; allocator math
  (softmax / floor-cap water-fill / smoothing / score) with known inputs; each risk check
  against crafted breaches; carried-leftover **re-validation** cancels the remainder when the
  entry signal is invalidated mid-carry (and completes carried exits regardless).
- **Property:** `Σ weights = 1` and within `[f, c]`; portfolio net within caps; virtual-book
  attribution sums reconcile to broker net; **no fill exceeds `participation_cap × candle_volume`**
  (the volume-cap invariant), and a carried remainder re-enters the cap check without ever
  over-filling; **every open position has a stop** and `total_open_risk ≤ max_total_open_risk ≤
  equity − buffer` holds after every order (the solvency invariant).
- **Integration:** full engine over a small historical slice via backtest → no crashes, sane
  outputs, attribution correct.
- **Paper soak:** run live paper for days, monitor logs + metrics.

---

## 16. Build phases

- **P0 — Skeleton:** config, MarketData interface + Alpaca feed (corporate-action adjustment +
  trading calendar), state store, engine loop, **a dormant bot-5 stub** (registered, inactive),
  one trivial bot, a paper order round-trip.
- **P1 — Allocator:** scoring → weights → aggressiveness (with **dormant-bot exclusion**),
  running with 2 bots.
- **P2 — Bots 1–4** (stat-arb, ORB, VWAP/Bollinger, order-flow) — the **active v1 set**.
- **P3 — Risk hardening:** full overlay + kill-switches + reconciliation + watchdog.
- **P4 — Backtest harness + metrics.**
- **P5 — Paper soak + tuning** (`τ`, `H`, floor/cap, per-bot thresholds) — 4 active bots.
- **Phase F — Futures + Bot 5 activation:** futures broker (IBKR/Tradovate) + futures data +
  contract / rollover / margin / micros + **bracket / scaled-exit + BE-stop** choreography +
  bot 5 ICT logic (session/liquidity mapping, FVG/OB/breaker/IFVG/SMT/OTE, TP ladder) →
  **activate bot 5** (NY-AM, MES/MNQ). Most complex bot; gated on all of the above.
- **Later:** Polygon L2 for true order-flow; **dynamic market-impact slippage ("heavy
  footprint")** — a price penalty that scales with participation (tiny order → mid price; near
  the `participation_cap` → extra slippage, modeling how a large order pushes price);
  **confidence-gated minimum order size** — if a bot's intended order is ≤ a tiny fraction of
  volume (e.g. ≤0.1%), optionally bump it up to a minimum (e.g. 1% of volume) **only when the
  bot's confidence exceeds a threshold** (heuristic TBD), so bots that intentionally want small
  size aren't overridden; news/sentiment **bot #6**; Kalman/GARCH/PCA upgrades; FRED regime
  filter; flip to live money.

---

## 17. Open risks & cautions

- **Allocator can chase noise:** rewarding the recently-hottest bot risks piling into a
  strategy right before it mean-reverts. Mitigations baked in: risk-adjusted (not raw) score,
  EWMA half-life (not a hard 3h window), temperature `τ`, weight floor/cap, and max-step
  smoothing. Tuning these in paper (P5) is essential before any live consideration.
- **Stat-arb blow-up:** a diverging spread is the classic failure mode → `z_stop`,
  max-hold, cointegration-break monitor, and the per-bot drawdown kill all guard it.
- **Order-flow fidelity:** top-of-book proxy + weak backtest → treat bot 4's paper results
  as the real validation, not its backtest.
- **Corporate actions:** unadjusted splits/divs silently corrupt stat-arb spreads — the data
  layer must adjust prices (called out as a v1 requirement).
- **Live money is out of scope** until paper soak + tuning prove the system; switching it on
  is a deliberate later decision, not a config afterthought.
- **Bot 5 futures-exclusive + dormant (chosen):** bot 5 trades **only** futures (MES/MNQ micros;
  SMT = ES vs NQ) and ships **inactive** until a futures broker (IBKR/Tradovate) + data are
  integrated (Phase F). v1 runs **4 active bots**. Full-size ES/NQ (≈$280k/$400k) won't fit a
  sliced ~$100k account, so micros are mandatory. Net effect: a smaller, lower-risk v1.
- **Bot 5 mechanization:** ICT is discretionary; encoding bias / draw-on-liquidity as fixed
  rules is an approximation and the riskiest part of bot 5 — validate heavily in paper.
- **Bot 5 is low-frequency:** a few NY-AM setups/day means sparse PnL, so its allocator score
  updates slowly and it will mostly sit near the floor weight until it proves out (a per-bot
  scoring half-life is a possible later refinement).
- **Session data for bot 5 (Phase F):** Asia/London/NY-AM levels come from **futures** data
  (genuine ~23h sessions), not thin equity pre-market — so the dependency is the futures data
  feed, not Alpaca SIP. (The thin extended-hours concern only applies if any *equity* bot ever
  needs pre/post-market data.)
- **Allocator reflexivity (the central bet):** funding the recently-hottest bot assumes
  short-horizon persistence of strategy returns; if strategy PnL mean-reverts, the allocator
  buys high / sells low on strategies. This is the project's core hypothesis — prove it against
  equal-weight out-of-sample (§10, §18) before trusting it, and start `τ` high (near equal),
  tightening only as evidence accrues.
- **Leverage & margin (live phase):** `max_gross_leverage` default **1.5×** — leverage *is*
  allowed because **actual loss is bounded by mandatory stops + the `max_total_open_risk` heat
  cap**, not by notional. ⚠️ Stops aren't guaranteed at level — **gaps / fast markets can fill
  worse** (overnight / futures gap risk) — so the solvency guarantee is Reg-T-strong, not
  absolute; the maintenance buffer + flat-by-EOD reduce it. Plus HTB fees/locates on shorts,
  PDT / GFV rules, and market impact on concentrated orders.
  The §10 **participation cap** now handles the *quantity* side (no infinite-liquidity fills);
  the *price* side — extra slippage as participation rises — is the deferred **"heavy footprint"**
  model (Later).

---

## 18. Acceptance criteria (definition of done — v1)

v1 counts as "working" only when **all** hold (v1 = the **4 active** bots; **bot 5 is dormant**
and out of v1 scope — its activation has its own criteria below):
- **Runs unattended** through full paper sessions for **≥ 5 trading days** with no crash and no
  unhandled exception escaping a bot.
- **Attribution reconciles:** Σ per-bot virtual books = broker net every cycle (within
  tolerance); `bot_equity` ties to account equity.
- **Risk limits never breached** (per-bot caps; gross ≤ `max_gross_leverage` (default 1.5×);
  |net| ≤ 0.3×; DD halts fire correctly when deliberately tested).
- **Every position has a stop; loss is bounded:** `total_open_risk ≤ max_total_open_risk ≤
  equity − maintenance buffer` holds at all times → worst-case (all stops hit) stays solvent, no
  margin call (subject to the gap-fill caveat).
- **Never exceeds buying power; no margin call:** the buying-power guard blocks over-spend (no
  new trades when capital is exhausted), and margin utilization stays under the maintenance
  buffer through the soak (de-gross fires before any breach).
- **Allocator beats equal-weight** (risk-adjusted) in walk-forward backtest, *or* it defaults to
  equal-weight — either way the choice is evidence-based.
- **Backtest is out-of-sample** (walk-forward, survivorship-aware, no lookahead) and reports
  per-bot + portfolio Sharpe, maxDD, turnover, hit rate, and inter-bot correlation.
- **No fill exceeds the participation cap** in any backtest run (the volume-cap invariant holds;
  carried remainders never over-fill).
- **Kill-switch + watchdog verified:** manual halt and dead-man flatten both demonstrably
  flatten and stop.
- **Recovery verified:** kill the process mid-session, restart, books rebuild from state and
  reconcile.

Live money stays out of scope until all the above pass **and** a tuning period completes.

**Bot 5 activation (Phase F) — its own definition of done:** futures broker + data integrated;
contract rollover + micros handled; bracket / scaled-exit + BE-stop verified; bot 5 backtested
out-of-sample on futures **and** paper-soaked over NY-AM sessions before it is added to the
allocation pool.
