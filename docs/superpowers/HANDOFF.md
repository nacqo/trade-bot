# Traderbot — Session Handoff (2026-06-20)

Detailed handoff so a fresh session can continue without re-deriving context. Read this, then
the spec (`specs/2026-06-19-multi-bot-trading-system-design.md`), pre-mortem (same dir), and plan
(`plans/2026-06-20-traderbot-v1.md`).

## What this project is

A single async Python program running multiple stock-trading bots under a **meta-allocator**:
whichever bot earned the most (risk-adjusted) recently gets more capital **and** a looser leash
(lower signal threshold + bigger size), with an always-on risk overlay. Paper-first on Alpaca,
architecture live-ready. The user (Nacho) drove the design over many iterations; Jaime is a
collaborator referenced in chat logs.

## Status: v1 complete + backtested on real data. System sound, no strategy edge. 99 tests green.

Backtested on real Alpaca data (2 pairs, 3 months): risk controls hold every regime, allocator
behaves correctly, but baseline strategies show no reliable edge — tuning further = overfitting.
See `docs/superpowers/BACKTEST_FINDINGS.md`. Verdict: ready as sound infrastructure, NOT a profit
engine; do not deploy expecting profit. Real-data harness: `scripts/eval.py` (caches to data/).

Branch `build/v1` (not merged). Python **3.14** in `.venv`. Run tests: `.venv/bin/python -m pytest -q`.
Direct CLI run needs `PYTHONPATH=src` (pytest sets it via pyproject).

### Done
- **P0–P5 (26 plan tasks):** config, types, NYSE calendar, SQLite state, Strategy base + **dormant
  bot 5**, fake broker + engine, virtual books, EWMA scoring, **meta-allocator** (softmax/τ +
  floor/cap water-fill + smoothing + aggressiveness + dormant exclusion; property-tested),
  **4 active bots** (stat-arb pairs, ORB, VWAP/Bollinger, order-flow), **risk manager** (mandatory
  stops, portfolio-heat cap + solvency invariant, leverage/buying-power guard, per-bot DD,
  kill-switch, watchdog; property-tested), netting + pro-rata attribution, **participation-capped
  fills + iterative carry + re-validation**, OMS, crash recovery + reconciliation, replay source,
  backtest runner, metrics + equal-weight benchmark + inter-bot correlation, Alpaca adapters, CLI,
  **acceptance harness** (7 §18 gates).
- **Reality bridge:** real `alpaca-py` (0.43.4, imports on 3.14) shim — `integrations/alpaca.py`:
  `TradingClientShim`, `build_alpaca_broker`, `fetch_historical_bars` (Adjustment.ALL),
  `build_historical_source`. CLI `backtest --symbols A,B --start --end` pulls **real adjusted bars**
  when `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` set; `paper` connects the real broker + prints account.
- **Condition 1:** kill-switch + per-bot DD suspension wired into the engine loop (portfolio DD ≥
  `total_dd_halt` → halt + flatten all; per-bot PnL drawdown ≥ `per_bot_dd_kill`×equity → flatten +
  suspend that bot). `_risk_checks/_flatten_all/_flatten_bot` in `engine.py`.
- **Condition 2:** carried entry remainders re-validate in the loop (cancel leftover if bots no
  longer want the symbol).
- **Cointegration gate (statsmodels):** `StatArbBot._refit_cointegration` Engle–Granger-gates which
  pairs trade (p < threshold, refit every N evals). statsmodels installed, works on 3.14.
- **Capital sleeve sizing:** `allocator.sleeve_scale` sizes each bot's gross to `weight × deployable`
  × aggressiveness (faithful; risk caps clamp). Wired in `engine._act_via_oms`.
- **Live-streaming loop:** `market_data/alpaca_live.LiveAlpacaSource` (websocket→async stream),
  `AlpacaBroker` fill-polling (`get_order_by_id` until filled), `live.run_paper` reuses engine+OMS
  with the real broker+feed (OMS fill model = live participation-cap order-sizer). `paper --symbols`
  starts it. Pieces DI-tested with mocks.

### NOT done / known seams (in priority order)
1. **Validate live + real data with CREDS (ONLY real blocker — user has no Alpaca key yet).** The
   live loop, real historical backtest, AND the OOS/walk-forward harness (`backtest/validation.py`
   `oos_report`, wired into `cli backtest`) are all BUILT + tested on synthetic data. What remains is
   running them against a real Alpaca account: real OOS backtest + paper soak (spec §18 DoD),
   including the **A1 reflexivity test** (allocator vs equal-weight on real returns — the #1 risk,
   pre-mortem A1). Commands ready: `traderbot backtest --symbols ... --start ... --end ...`,
   `traderbot paper --symbols ...`.
2. **Deferred features (per spec, intentional):** Phase F (futures broker + activate bot 5 on
   MES/MNQ), heavy-footprint dynamic slippage, confidence-gated minimum-order rule.

(Done since first handoff: cointegration gate, sleeve sizing, live loop, **live partial-fill
reconciliation** — OMS now attributes the broker's actual fill qty + carries shortfall — and the
**OOS validation harness**. Package is now `pip install -e .`; `traderbot` runs without PYTHONPATH.)

## Key design decisions + WHY (don't relitigate)

- **Meta-allocator shape = softmax(score/τ) + floor + cap + max-step smoothing.** One temperature
  knob τ spans winner-take-most ↔ proportional ↔ equal, so the user didn't have to pick. Floor lets
  a cold bot recover; cap prevents over-concentration; smoothing kills whipsaw. Config in
  `AllocatorCfg`. **Water-fill must clamp ONE violation per iteration (cap first)** — fixing floor+cap
  together strands budget (property test caught this; see `allocator.py:_waterfill`).
- **Score = risk-adjusted (EWMA mean/std, drawdown-penalized), not raw PnL.** EWMA half-life (default
  4h) replaced the user's original hard 3h window ("too aggressive"). Cold-start (<min_obs) → neutral
  0 → floor weight.
- **Two allocator outputs:** capital weight AND aggressiveness multiplier ("more lenient to trade").
- **Virtual books + netted execution.** Broker holds only net; each bot keeps a virtual book for
  clean PnL attribution; OMS nets deltas before sending real orders; partial fills attributed
  pro-rata (sums exactly). `Σ virtual books == broker net` is an invariant (reconcile() == []).
- **Stop-bounded 1.5× leverage (user's refinement).** Leverage allowed for *exposure*; *loss* bounded
  by mandatory per-position stops + a portfolio-heat cap `total_open_risk = Σ|qty·(entry−stop)| ≤
  max_total_open_risk ≤ equity − maintenance_buffer` → **solvency invariant** (wallet never below
  `equity − Σ stops`; no margin call). ⚠️ Gap caveat: stops can slip (pre-mortem C4).
- **Participation cap (user's "speed limit").** Fill ≤ 5% of candle volume (tweakable
  `participation_cap`); leftovers carry candle-by-candle ("1000 → 400/400/200"); carried entries
  re-validate. Lives in both backtest fills and as a live guard.
- **Bot 5 = futures-EXCLUSIVE (MES/MNQ), ships DORMANT** (zero allocation) until Phase F. v1 = 4
  active bots. Alpaca has no futures; futures give real ~23h Asia/London sessions for the ICT model.
- **Architecture A (monolith async).** Custom allocator gains nothing from a framework; clean
  Strategy/Allocator/Execution/Risk interfaces give a trivial live↔backtest swap.

## Architecture / file map (`src/traderbot/`)

`config.py` (pydantic, all §12 defaults) · `types.py` (Bar/Quote/TradeTick/Position/OrderIntent/Fill)
· `market_data/{calendar,source,alpaca_feed}.py` · `strategies/{base,dormant,fixed_target,orb,
vwap_reversion,stat_arb,order_flow}.py` · `allocator/{scoring,allocator}.py` ·
`execution/{broker,virtual_book,netting,fills,oms,recovery,alpaca_broker}.py` ·
`risk/risk_manager.py` · `engine/{engine,watchdog}.py` · `backtest/{runner,metrics}.py` ·
`integrations/alpaca.py` · `cli.py`. Tests mirror under `tests/`.

Data flow: source → engine marks books → (rebalance timer) scorer+allocator → risk admission
(stop + heat) + capital/aggr scaling → OMS (net → buying-power guard → participation fill → attribute
→ carry) → broker. Risk checks each bar (halt/flatten/suspend).

## How to run

```
.venv/bin/python -m pytest -q                 # 88 tests
PYTHONPATH=src .venv/bin/python -m traderbot.cli backtest        # synthetic demo
# real data (needs creds):
export ALPACA_API_KEY=... ALPACA_SECRET_KEY=...
PYTHONPATH=src .venv/bin/python -m traderbot.cli backtest --symbols AAPL,MSFT --start 2026-01-02 --end 2026-01-09
PYTHONPATH=src .venv/bin/python -m traderbot.cli paper          # connects paper broker, prints account
```
Deps installed in `.venv`: core (pydantic, numpy, pandas, aiosqlite, structlog, pandas_market_calendars,
hypothesis, pytest) + **alpaca-py** + **statsmodels** (cointegration; pulls scipy). NOT installed:
pandas-ta (unused — VWAP/BB hand-rolled), quantstats/empyrical (metrics hand-rolled).

## Recommended next steps

1. **Get creds + run a real OOS/walk-forward backtest** on liquid names; compute allocator-vs-equal-
   weight (tests A1). 2. **Wire the live streaming loop + fill confirmation** for real paper. 3. Then
   paper soak (§18). Hold Phase F / heavy-footprint / min-order until v1 survives real data.

## User working preferences (this project)
- Caveman mode for chat (see global CLAUDE.md); code/commits/specs written normal.
- **Wants an extremely detailed handoff file at ~90% usage — all reasoning is valuable** (this file).
- Decisive, iterates fast, cares about real-money safety (margin calls, stops, honest fills).
- Commit per task with the Co-Authored-By + Claude-Session trailers.
