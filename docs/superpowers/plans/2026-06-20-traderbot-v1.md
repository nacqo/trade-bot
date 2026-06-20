# Traderbot v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single async Python program that runs 4 active strategy bots over US stocks on Alpaca paper, with a risk-adjusted meta-allocator that dynamically sets each bot's capital and aggressiveness, a stop-bounded risk overlay, and a deterministic volume-aware backtest — all behind interfaces that swap live↔backtest by config.

**Architecture:** Monolithic async engine (spec Approach A). Clean interfaces: `MarketData` source → `Strategy` bots (emit target positions + signal) → `Allocator` (scores virtual books, sets capital_weight + aggressiveness) → `Execution`/OMS (nets, participation-caps fills, manages carry) → `Risk` (caps, stops, heat, buying power, kill-switch) → `StateStore` (SQLite). Backtest reuses every layer behind a replay `MarketData` + simulated fills.

**Tech Stack:** Python 3.11+, asyncio, `alpaca-py`, `statsmodels`, `pandas-ta`, `pandas_market_calendars`, `quantstats`/`empyrical`, `pandas`, `numpy`, `scipy`, `pydantic` v2, `aiosqlite`, `structlog`; dev: `pytest`, `pytest-asyncio`, `hypothesis`.

## Global Constraints

- Language: **Python 3.11+**, asyncio single event loop. Heavy compute (cointegration, scans) off-loop via `run_in_executor`.
- Broker/data behind a `Broker` + `MarketData` **interface**; tests use in-memory fakes, never the network.
- Paper-first; **live = config flag**. v1 = **4 active bots** (stat-arb pairs, ORB, VWAP/Bollinger, order-flow) + **dormant bot-5 stub** (futures-only, excluded from allocation).
- TDD always; **commit after every passing task**. Work on branch `build/v1`.
- Money math: use `float` for prices/qty in v1 (document); round share qty to whole shares (Alpaca supports fractional but v1 trades whole shares for determinism).
- **Invariants (property-tested):**
  - allocator weights over *active* bots sum to 1, each ∈ `[floor, cap]`; dormant bots get 0.
  - simulated fill ≤ `participation_cap × candle_volume` (default 0.05).
  - `total_open_risk = Σ(size × |entry − stop|) ≤ max_total_open_risk ≤ equity − maintenance_buffer`.
  - every open position has a stop; buying-power guard rejects orders beyond free buying power.
- Config: one pydantic `Config`; all spec defaults (§12) live there; nothing hard-coded in logic.

---

## File Structure

```
pyproject.toml
src/traderbot/
  __init__.py
  config.py                # pydantic Config + sub-models (spec §12 defaults)
  types.py                 # core dataclasses: Bar, Quote, TradeTick, Side, OrderIntent, Fill, Position
  market_data/
    source.py              # MarketDataSource protocol; ReplaySource (historical)
    calendar.py            # TradingCalendar wrapper (pandas_market_calendars)
  strategies/
    base.py                # Strategy ABC; TargetPosition, ExitPlan, BotOutput
    stat_arb.py            # Bot 1
    orb.py                 # Bot 2
    vwap_reversion.py      # Bot 3
    order_flow.py          # Bot 4
    dormant.py             # Bot 5 stub (enabled=False)
  allocator/
    scoring.py             # EWMA risk-adjusted score per bot
    allocator.py           # softmax/temperature + floor/cap water-fill + smoothing + aggressiveness; dormant exclusion
  execution/
    virtual_book.py        # per-bot virtual positions + mark-to-market PnL
    netting.py             # net bot targets → per-symbol net intent
    fills.py               # SimulatedFillModel: participation cap + partial + iterative carry + revalidation
    oms.py                 # OMS: orchestrates netting, fills, attribution, buying-power guard
  risk/
    risk_manager.py        # leverage, net, heat/solvency, per-bot DD, stops, buying power, kill-switch
  state/
    store.py               # SQLite StateStore (aiosqlite) + schema
  engine/
    engine.py              # async loop: data → bots → allocator → risk → execution → state; scheduling
  backtest/
    runner.py              # wires ReplaySource + SimulatedFillModel through the engine
    metrics.py             # Sharpe, maxDD, turnover, hit rate, inter-bot correlation, allocator-vs-equalweight
  cli.py                   # entry points: `status`, `backtest`, `paper`
tests/
  ... mirrors src/traderbot/ ...
```

---

## Phase P0 — Skeleton

### Task 1: Project scaffold + config

**Files:**
- Create: `pyproject.toml`, `src/traderbot/__init__.py`, `src/traderbot/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config` (pydantic `BaseModel`) with nested `AllocatorCfg`, `RiskCfg`, `ExecutionCfg`, `DataCfg`, and `Config.default() -> Config`.

- [ ] **Step 1: Write `pyproject.toml`** with deps + pytest config.

```toml
[project]
name = "traderbot"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "alpaca-py>=0.20", "statsmodels>=0.14", "pandas-ta>=0.3.14b",
  "pandas-market-calendars>=4.3", "quantstats>=0.0.62", "empyrical>=0.5",
  "pandas>=2.0", "numpy>=1.26", "scipy>=1.11", "pydantic>=2.5",
  "aiosqlite>=0.19", "structlog>=24.1",
]
[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "hypothesis>=6.100"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["src"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
```

- [ ] **Step 2: Write the failing test** `tests/test_config.py`

```python
from traderbot.config import Config

def test_default_config_has_spec_defaults():
    c = Config.default()
    assert c.allocator.tau == 0.5
    assert c.allocator.floor == 0.05
    assert c.allocator.cap == 0.50
    assert c.allocator.ewma_half_life_hours == 4.0
    assert c.risk.max_gross_leverage == 1.5
    assert c.risk.max_total_open_risk_frac == 0.10
    assert c.execution.participation_cap == 0.05
    assert c.execution.revalidate_on_carry is True
```

- [ ] **Step 3: Run test, verify FAIL** — `pytest tests/test_config.py -v` → ImportError.

- [ ] **Step 4: Implement `config.py`**

```python
from pydantic import BaseModel

class AllocatorCfg(BaseModel):
    tau: float = 0.5
    floor: float = 0.05
    cap: float = 0.50
    max_step: float = 0.10           # Δ per rebalance
    ewma_half_life_hours: float = 4.0
    drawdown_penalty: float = 0.5    # λ
    min_obs: int = 30
    eps: float = 1e-8
    aggr_min: float = 0.5
    aggr_max: float = 2.0
    aggr_slope: float = 0.5          # k
    rebalance_minutes: int = 15

class RiskCfg(BaseModel):
    per_bot_dd_kill: float = 0.02
    max_gross_leverage: float = 1.5
    max_net_frac: float = 0.30
    per_trade_risk_frac: float = 0.01
    max_total_open_risk_frac: float = 0.10
    maintenance_buffer_frac: float = 0.25
    total_dd_halt: float = 0.05
    max_order_notional_frac: float = 0.05

class ExecutionCfg(BaseModel):
    participation_cap: float = 0.05
    revalidate_on_carry: bool = True
    slippage_bps: float = 1.0

class DataCfg(BaseModel):
    deploy_fraction: float = 1.0
    feed: str = "iex"
    bar_minutes: int = 1

class Config(BaseModel):
    allocator: AllocatorCfg = AllocatorCfg()
    risk: RiskCfg = RiskCfg()
    execution: ExecutionCfg = ExecutionCfg()
    data: DataCfg = DataCfg()
    starting_equity: float = 100_000.0

    @classmethod
    def default(cls) -> "Config":
        return cls()
```

- [ ] **Step 5: Run test, verify PASS.**
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: project scaffold + pydantic config"`

---

### Task 2: Core types

**Files:** Create `src/traderbot/types.py`; Test `tests/test_types.py`

**Interfaces:**
- Produces: `Side(Enum BUY/SELL)`; frozen dataclasses `Bar(symbol, ts, open, high, low, close, volume)`, `Quote(symbol, ts, bid, ask, bid_size, ask_size)`, `TradeTick(symbol, ts, price, size)`, `Position(symbol, qty, avg_price)`, `OrderIntent(bot_id, symbol, target_qty, stop_price, exit_plan=None)`, `Fill(bot_id, symbol, qty, price, ts)`.

- [ ] **Step 1: Failing test**

```python
from traderbot.types import Bar, Position, Side
def test_position_signed_and_market_value():
    p = Position(symbol="AAPL", qty=-10, avg_price=100.0)
    assert p.is_short
    assert p.market_value(105.0) == -1050.0
def test_side_from_signed_qty():
    assert Side.from_qty(5) is Side.BUY
    assert Side.from_qty(-5) is Side.SELL
```

- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement** dataclasses + `Side` enum with `from_qty`, `Position.is_short`, `Position.market_value(price)=qty*price`.
- [ ] **Step 4: Run, verify PASS.**
- [ ] **Step 5: Commit** — `feat: core domain types`

---

### Task 3: Trading calendar wrapper

**Files:** Create `src/traderbot/market_data/calendar.py`, `src/traderbot/market_data/__init__.py`; Test `tests/market_data/test_calendar.py`

**Interfaces:**
- Produces: `TradingCalendar(name="XNYS")` with `is_open(ts) -> bool`, `session_bounds(date) -> (open_ts, close_ts)`, `minutes_in_session(date) -> int`.

- [ ] **Step 1: Failing test** — assert a known NYSE holiday (2026-01-01) `is_open` False; a regular Wednesday 14:00 ET True; pre-open 08:00 ET False.
- [ ] **Step 2: Run, FAIL.**
- [ ] **Step 3: Implement** wrapping `pandas_market_calendars.get_calendar("XNYS")`; convert ts to ET; check schedule.
- [ ] **Step 4: Run, PASS.**
- [ ] **Step 5: Commit** — `feat: NYSE trading calendar wrapper`

---

### Task 4: SQLite state store

**Files:** Create `src/traderbot/state/store.py`, `src/traderbot/state/__init__.py`; Test `tests/state/test_store.py`

**Interfaces:**
- Produces: `StateStore(path)` async: `await init()`, `record_fill(Fill)`, `record_allocation(ts, bot_id, score, weight, capital, aggr)`, `record_bot_equity(ts, bot_id, realized, unrealized, equity)`, `load_positions() -> list[Position-like rows]`, `record_risk_event(ts, type, detail)`. Tables per spec §11.

- [ ] **Step 1: Failing test** (async) — init in `:memory:` (or tmp file), `record_fill` then query row count == 1; round-trip a fill's fields.
- [ ] **Step 2: Run, FAIL.**
- [ ] **Step 3: Implement** with `aiosqlite`; `init()` runs `CREATE TABLE IF NOT EXISTS` for fills, positions, bot_equity, allocations, orders, risk_events, config_snapshots.
- [ ] **Step 4: Run, PASS.**
- [ ] **Step 5: Commit** — `feat: SQLite state store + schema`

---

### Task 5: Strategy base + dormant bot

**Files:** Create `src/traderbot/strategies/base.py`, `src/traderbot/strategies/dormant.py`, `src/traderbot/strategies/__init__.py`; Test `tests/strategies/test_base_dormant.py`

**Interfaces:**
- Produces: `@dataclass TargetPosition(symbol, qty, stop_price)`; `@dataclass BotOutput(targets: list[TargetPosition], signal_strength: float, enabled: bool=True)`; `class Strategy(ABC)` with `id: str`, `enabled: bool=True`, `on_bar(bar)`, `on_quote(quote)`, `on_trade(tick)` (no-op defaults), and abstract `evaluate() -> BotOutput`. `DormantBot(id, instrument_note)` with `enabled=False`, `evaluate()` returns empty `BotOutput(enabled=False)`.

- [ ] **Step 1: Failing test** — `DormantBot("bot5","futures").evaluate()` returns `BotOutput` with `enabled is False` and `targets == []`.
- [ ] **Step 2: Run, FAIL.**
- [ ] **Step 3: Implement** base ABC + dormant.
- [ ] **Step 4: Run, PASS.**
- [ ] **Step 5: Commit** — `feat: Strategy base interface + dormant bot stub`

---

### Task 6: Fake broker + trivial bot + paper round-trip (engine seed)

**Files:** Create `src/traderbot/execution/broker.py` (`Broker` protocol + `FakeBroker`), `src/traderbot/strategies/always_flat.py` (trivial bot), `src/traderbot/engine/engine.py` (minimal loop), `src/traderbot/engine/__init__.py`; Test `tests/engine/test_round_trip.py`

**Interfaces:**
- Produces: `Broker` protocol: `submit(OrderIntent) -> Fill`, `positions() -> dict[str, Position]`, `equity() -> float`, `buying_power() -> float`. `FakeBroker(start_equity)` fills instantly at a provided mark. `Engine(config, source, bots, broker, store)` with `await step()` running one cycle.
- Consumes: Task 1 `Config`, Task 2 types, Task 5 `Strategy`.

- [ ] **Step 1: Failing test** — engine with one bot that targets +1 share AAPL; after `step()`, `FakeBroker.positions()["AAPL"].qty == 1` and a fill is recorded in store.
- [ ] **Step 2: Run, FAIL.**
- [ ] **Step 3: Implement** minimal engine: pull bar → bots.evaluate() → (P0: pass targets straight to broker) → record fills. `FakeBroker` tracks positions/equity.
- [ ] **Step 4: Run, PASS.**
- [ ] **Step 5: Commit** — `feat: fake broker + minimal engine round-trip`

---

## Phase P1 — Allocator (the novel core)

### Task 7: Virtual book + mark-to-market PnL

**Files:** Create `src/traderbot/execution/virtual_book.py`; Test `tests/execution/test_virtual_book.py`

**Interfaces:**
- Produces: `VirtualBook(bot_id)` with `apply_fill(symbol, qty, price)`, `mark(prices: dict) -> None`, props `realized`, `unrealized`, `equity`, `positions -> dict[str,Position]`. Long/short avg-price accounting; realized PnL on reducing fills.

- [ ] **Step 1: Failing test** — buy 10 @100, mark @110 → unrealized 100; sell 10 @110 → realized 100, unrealized 0, flat.
- [ ] **Step 2: Run, FAIL.**
- [ ] **Step 3: Implement** average-price PnL accounting (handle flips: closing crosses zero realizes, remainder opens at new price).
- [ ] **Step 4: Run, PASS** — add a 2nd test for a long→short flip realizing correctly.
- [ ] **Step 5: Commit** — `feat: per-bot virtual book with realized/unrealized PnL`

---

### Task 8: EWMA risk-adjusted scoring

**Files:** Create `src/traderbot/allocator/scoring.py`, `src/traderbot/allocator/__init__.py`; Test `tests/allocator/test_scoring.py`

**Interfaces:**
- Produces: `BotScorer(half_life_hours, drawdown_penalty, min_obs, eps, interval_minutes)` with `update(bot_id, interval_return)`, `score(bot_id) -> float` = `ewma_mean/(ewma_std+eps) - λ*drawdown`; returns neutral (`0.0`) until `min_obs` observations; tracks per-bot peak/drawdown of cumulative return.

- [ ] **Step 1: Failing test** — feed a steady positive return stream → score > 0 after `min_obs`; feed `< min_obs` obs → score == 0.0 (neutral/cold-start). Volatile zero-mean stream → score near 0.
- [ ] **Step 2: Run, FAIL.**
- [ ] **Step 3: Implement** EWMA mean/var with `alpha = 1 - 0.5**(interval/half_life_in_intervals)`; Welford-style EWMA variance; drawdown from running cumulative-return peak.
- [ ] **Step 4: Run, PASS.**
- [ ] **Step 5: Commit** — `feat: EWMA risk-adjusted bot scoring with cold-start`

---

### Task 9: Allocator — softmax + floor/cap water-fill + smoothing + aggressiveness + dormant exclusion

**Files:** Create `src/traderbot/allocator/allocator.py`; Test `tests/allocator/test_allocator.py`

**Interfaces:**
- Produces: `Allocator(cfg: AllocatorCfg)` with `allocate(scores: dict[str,float], active: set[str], prev_weights: dict[str,float]) -> dict[str, AllocResult]` where `AllocResult(weight, aggressiveness)`. Dormant (not in `active`) → weight 0. `aggressiveness = clip(1 + k*zscore(score), aggr_min, aggr_max)`.

- [ ] **Step 1: Failing tests** (multiple asserts):

```python
def test_weights_sum_to_one_and_within_bounds():
    a = Allocator(AllocatorCfg())
    res = a.allocate({"b1":2.0,"b2":1.0,"b3":0.0,"b4":-1.0},
                     active={"b1","b2","b3","b4"}, prev_weights={})
    w = {k:v.weight for k,v in res.items()}
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert all(AllocatorCfg().floor-1e-9 <= x <= AllocatorCfg().cap+1e-9 for x in w.values())

def test_dormant_bot_gets_zero_and_excluded():
    a = Allocator(AllocatorCfg())
    res = a.allocate({"b1":1.0,"b5":5.0}, active={"b1"}, prev_weights={})
    assert "b5" not in res or res["b5"].weight == 0.0
    assert abs(res["b1"].weight - 1.0) < 1e-9

def test_smoothing_limits_step():
    cfg = AllocatorCfg(max_step=0.1)
    a = Allocator(cfg)
    res = a.allocate({"b1":10.0,"b2":-10.0}, active={"b1","b2"},
                     prev_weights={"b1":0.5,"b2":0.5})
    assert res["b1"].weight <= 0.5 + 0.1 + 1e-9
```

- [ ] **Step 2: Run, FAIL.**
- [ ] **Step 3: Implement**: softmax(score/τ) over active; iterative water-fill clamp to `[floor,cap]` then renormalize unclamped until stable; apply `max_step` smoothing vs prev_weights then renormalize; aggressiveness from cross-sectional z of scores.
- [ ] **Step 4: Run, PASS.**
- [ ] **Step 5: Property test** (hypothesis): random score vectors + active sets → sum==1, bounds hold, dormant==0. Commit — `feat: meta-allocator (softmax/floor-cap/smoothing/aggressiveness)`

---

### Task 10: Wire allocator into engine (2 bots)

**Files:** Modify `src/traderbot/engine/engine.py`; Test `tests/engine/test_engine_allocator.py`

**Interfaces:**
- Consumes: Tasks 7–9. Engine now: marks virtual books each bar → on rebalance tick, `scorer.update` from book interval returns → `allocator.allocate` → store `record_allocation` → scales bot targets by `weight*deployable` and `aggressiveness`.
- Produces: `Engine.weights -> dict`, `Engine.aggressiveness -> dict`.

- [ ] **Step 1: Failing test** — two bots, one fed winning marks; after several rebalances the winner's weight > loser's; weights recorded in store.
- [ ] **Step 2: Run, FAIL.** → **Step 3: Implement** rebalance scheduling (every `rebalance_minutes`), interval-return calc from virtual-book equity deltas. → **Step 4: PASS.** → **Step 5: Commit** — `feat: allocator wired into engine with 2 bots`

---

## Phase P2 — The 4 active bots

> Each bot consumes `Bar`/`Quote`/`TradeTick` and produces `BotOutput`. All have an explicit `stop_price` on every `TargetPosition` (risk requires it).

### Task 11: Bot 2 — Opening Range Breakout (simplest first)

**Files:** Create `src/traderbot/strategies/orb.py`; Test `tests/strategies/test_orb.py`

**Interfaces:** `ORBBot(id, symbols, opening_minutes=30, atr_period=14)` → on each session, build opening range from first N minutes; breakout above OR-high → long (stop = OR-low), below → short (stop = OR-high); `signal_strength = min(1, breakout_dist/ATR)`; flat by EOD.

- [ ] **Step 1: Failing test** — feed bars: opening range [100,101], then a bar to 102 → `BotOutput` has long target with stop≈100, signal>0.
- [ ] **Step 2: FAIL → Step 3: Implement → Step 4: PASS** (add a no-breakout test → empty targets).
- [ ] **Step 5: Commit** — `feat: ORB momentum bot`

### Task 12: Bot 3 — VWAP / Bollinger reversion

**Files:** Create `src/traderbot/strategies/vwap_reversion.py`; Test `tests/strategies/test_vwap_reversion.py`

**Interfaces:** `VWAPReversionBot(id, symbols, bb_period=20, bb_sigma=2.0)` → maintain session VWAP + rolling mean/std (use `pandas-ta` or manual); price ≥ upper band & above VWAP → short (stop above band), ≤ lower & below VWAP → long (stop below band); exit toward VWAP; `signal = deviation_in_sigma`.

- [ ] **Step 1: Failing test** — construct bars so last close sits ≥2σ above mean & above VWAP → short target with stop above entry.
- [ ] **Step 2–4: TDD** (add a within-band test → no target).
- [ ] **Step 5: Commit** — `feat: VWAP/Bollinger reversion bot`

### Task 13: Bot 1 — Statistical arbitrage pairs

**Files:** Create `src/traderbot/strategies/stat_arb.py`; Test `tests/strategies/test_stat_arb.py`

**Interfaces:** `StatArbBot(id, pairs: list[tuple[str,str]], z_in=2.0, z_out=0.5, z_stop=3.5, lookback=120)` → per pair maintain price windows; OLS hedge ratio β (offline refit hook, v1 rolling OLS each bar over lookback); `spread=Pa-β*Pb`; rolling z; `|z|>z_in` → short rich/long cheap dollar-neutral (stops at `z_stop` distance in price terms); exit `|z|<z_out`; `signal=min(1,|z|/z_stop)`. Cointegration test (`statsmodels.coint`) gates whether a pair is tradable (refit hook; run off-loop).

- [ ] **Step 1: Failing test** — synthetic cointegrated series (B = A + mean-reverting noise); push z above 2 → bot emits offsetting long/short targets with stops; both legs present.
- [ ] **Step 2: FAIL → Step 3: Implement** (β via `numpy.polyfit`/OLS; z from rolling mean/std). → **Step 4: PASS** (add z-revert exit test).
- [ ] **Step 5: Commit** — `feat: statistical arbitrage pairs bot`

### Task 14: Bot 4 — Order-flow imbalance

**Files:** Create `src/traderbot/strategies/order_flow.py`; Test `tests/strategies/test_order_flow.py`

**Interfaces:** `OrderFlowBot(id, symbols, window_secs=60, imb_threshold=0.3)` → from `Quote` (top-of-book) maintain rolling `imbalance=(bid_size-ask_size)/(bid_size+ask_size)` + signed trade-flow from `TradeTick`; strong + → brief long (tight stop = recent low), strong − → short; `signal=min(1,|imbalance|)`. (Top-of-book only — documented limitation.)

- [ ] **Step 1: Failing test** — feed quotes with bid_size≫ask_size sustained → long target with a tight stop; balanced book → no target.
- [ ] **Step 2–4: TDD.**
- [ ] **Step 5: Commit** — `feat: order-flow imbalance bot`

---

## Phase P3 — Risk overlay

### Task 15: Risk manager — stops, heat, solvency, leverage, net, buying power

**Files:** Create `src/traderbot/risk/risk_manager.py`, `src/traderbot/risk/__init__.py`; Test `tests/risk/test_risk_manager.py`

**Interfaces:**
- Produces: `RiskManager(cfg: RiskCfg)` with `check_order(intent, *, equity, positions, buying_power, open_risk) -> RiskDecision(approved: bool, reason, clipped_qty)`; `total_open_risk(positions, stops) -> float`; `gross(positions, prices)`, `net(positions, prices)`; `degross_factor(margin_util, open_risk, drawdown) -> float`; `should_halt(...) -> bool`. Enforces: gross ≤ `max_gross_leverage*equity`; |net| ≤ `max_net_frac*equity`; `open_risk + new_risk ≤ max_total_open_risk_frac*equity` and that cap ≤ `equity*(1-maintenance_buffer_frac)`; order notional ≤ free buying power (else reject/clip — never borrow past leverage); reject any intent with no `stop_price`.

- [ ] **Step 1: Failing tests:**

```python
def test_rejects_order_without_stop():
    rm = RiskManager(RiskCfg())
    d = rm.check_order(OrderIntent("b1","AAPL",10,stop_price=None),
                       equity=100_000, positions={}, buying_power=100_000, open_risk=0)
    assert not d.approved and "stop" in d.reason

def test_rejects_when_buying_power_exhausted():
    rm = RiskManager(RiskCfg())
    d = rm.check_order(OrderIntent("b1","AAPL",1000,stop_price=99.0),
                       equity=100_000, positions={}, buying_power=0.0, open_risk=0,
                       price=100.0)
    assert not d.approved

def test_blocks_when_heat_would_exceed_cap():
    rm = RiskManager(RiskCfg())  # max_total_open_risk_frac=0.10 → $10k
    # order risking $2/share * 6000 = $12k > $10k
    d = rm.check_order(OrderIntent("b1","AAPL",6000,stop_price=98.0),
                       equity=100_000, positions={}, buying_power=1e9, open_risk=0,
                       price=100.0)
    assert not d.approved and "risk" in d.reason

def test_solvency_invariant_ceiling():
    rm = RiskManager(RiskCfg(max_total_open_risk_frac=0.9, maintenance_buffer_frac=0.25))
    # effective cap must be min(0.9, 1-0.25)=0.75 of equity
    assert rm.effective_open_risk_cap(100_000) == 75_000
```

- [ ] **Step 2: Run, FAIL.**
- [ ] **Step 3: Implement** all checks; `effective_open_risk_cap = equity*min(max_total_open_risk_frac, 1-maintenance_buffer_frac)`.
- [ ] **Step 4: Run, PASS.**
- [ ] **Step 5: Property test** — random portfolios: approved orders never push gross/net/heat past caps. Commit — `feat: risk manager (stops, heat, solvency, leverage, buying power)`

### Task 16: Kill-switch + watchdog + per-bot DD suspension

**Files:** Modify `risk_manager.py`; Create `src/traderbot/engine/watchdog.py`; Test `tests/risk/test_killswitch.py`

**Interfaces:** `RiskManager.halt()` / `.halted`; `per_bot_drawdown_breach(bot_equity_curve) -> bool` (−`per_bot_dd_kill`); engine flattens+suspends a bot on breach, flattens all on total DD halt. `Watchdog(timeout_s)` trips halt if `beat()` not called within timeout.

- [ ] **Step 1: Failing test** — bot DD −2% → `per_bot_drawdown_breach` True; total DD −5% → `should_halt` True; watchdog with no beat → tripped.
- [ ] **Step 2–4: TDD.** → **Step 5: Commit** — `feat: kill-switch, watchdog, per-bot drawdown suspension`

---

## Phase P4 — Execution realism (participation fills + netting + carry)

### Task 17: Netting across bots

**Files:** Create `src/traderbot/execution/netting.py`; Test `tests/execution/test_netting.py`

**Interfaces:** `net_targets(bot_targets: dict[str, list[TargetPosition]], current_book: dict[str, dict[str,float]]) -> dict[str, float]` → per symbol, net desired delta = Σ bot desired − current real; returns per-symbol net order qty. Keeps a `contributors(symbol) -> dict[bot_id, share]` for pro-rata attribution.

- [ ] **Step 1: Failing test** — bot A wants +600 AAPL, bot B wants −100 AAPL, current 0 → net +500; contributors split recorded.
- [ ] **Step 2–4: TDD.** → **Step 5: Commit** — `feat: cross-bot order netting with attribution shares`

### Task 18: Simulated fill model — participation cap + partial + iterative carry + revalidation

**Files:** Create `src/traderbot/execution/fills.py`; Test `tests/execution/test_fills.py`

**Interfaces:**
- Produces: `SimulatedFillModel(participation_cap, slippage_bps, revalidate_on_carry)` with `fill(order: CarryOrder, candle: Bar, *, still_valid: Callable[[],bool]) -> FillResult(filled_qty, price, remainder, cancelled)`. Fill qty = `min(remaining, floor(participation_cap*candle.volume))`; price = candle.open ± slippage; remainder carries. On a carried slice, if `revalidate_on_carry` and `still_valid()` is False → cancel remainder (entries); reductions always continue.

- [ ] **Step 1: Failing tests:**

```python
def test_fill_capped_at_participation():
    m = SimulatedFillModel(0.05, 1.0, True)
    bar = Bar("AAPL", ts, 100,100,100,100, volume=8000)
    r = m.fill(CarryOrder("b1","AAPL",remaining=1000,is_entry=True), bar, still_valid=lambda: True)
    assert r.filled_qty == 400   # 5% of 8000
    assert r.remainder == 600

def test_iterative_carry_until_below_cap():
    # 1000 over candles of 8000 vol -> 400,400,200
    ...

def test_revalidation_cancels_entry_remainder():
    m = SimulatedFillModel(0.05, 1.0, True)
    bar = Bar("AAPL", ts, 100,100,100,100, volume=8000)
    r = m.fill(CarryOrder("b1","AAPL",remaining=600,is_entry=True), bar, still_valid=lambda: False)
    assert r.cancelled and r.filled_qty == 0

def test_exit_remainder_not_cancelled_on_invalidation():
    m = SimulatedFillModel(0.05, 1.0, True)
    bar = Bar("AAPL", ts, 100,100,100,100, volume=8000)
    r = m.fill(CarryOrder("b1","AAPL",remaining=600,is_entry=False), bar, still_valid=lambda: False)
    assert not r.cancelled and r.filled_qty == 400
```

- [ ] **Step 2: Run, FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, PASS.**
- [ ] **Step 5: Property test** — `filled_qty ≤ participation_cap*volume` for random volumes/orders (the volume-cap invariant). Commit — `feat: volume-aware simulated fills with iterative carry + revalidation`

### Task 19: OMS — orchestrate netting + fills + buying-power guard + attribution

**Files:** Create `src/traderbot/execution/oms.py`; Test `tests/execution/test_oms.py`

**Interfaces:** `OMS(fill_model, risk_manager, broker_or_sim)` with `await execute(bot_targets, candle, equity, books) -> list[Fill]` → net → per-symbol carry orders → risk `check_order` (buying power, heat, stop) → fill → attribute pro-rata into each bot's `VirtualBook` → carry remainders to a pending queue for next candle (with each contributing bot's `still_valid` from its current signal).

- [ ] **Step 1: Failing test** — two bots net to +500 AAPL, candle volume 8000 → 400 fill attributed 480/-80? (pro-rata of the +600/−100 contributors); remainder queued.
- [ ] **Step 2–4: TDD.** → **Step 5: Commit** — `feat: OMS with participation carry, buying-power guard, pro-rata attribution`

### Task 20: Crash recovery + reconciliation

**Files:** Modify `oms.py`, `engine.py`, `state/store.py`; Test `tests/execution/test_recovery.py`

**Interfaces:** `rebuild_books(store) -> dict[bot_id, VirtualBook]` from persisted fills/positions; `reconcile(books, broker_positions) -> list[adjustment]` logs drift.

- [ ] **Step 1: Failing test** — record fills, drop state, `rebuild_books` reproduces per-bot positions; inject broker drift → reconciliation adjustment logged.
- [ ] **Step 2–4: TDD.** → **Step 5: Commit** — `feat: exact crash recovery + virtual/broker reconciliation`

---

## Phase P5 — Backtest + metrics + paper wiring

### Task 21: Replay source

**Files:** Create `src/traderbot/market_data/source.py`; Test `tests/market_data/test_replay.py`

**Interfaces:** `MarketDataSource` protocol (`async stream() -> AsyncIterator[Bar|Quote|TradeTick]`); `ReplaySource(bars_by_symbol, quotes=None, trades=None)` yields events in ts order; **closed-bars only** (no lookahead).

- [ ] **Step 1: Failing test** — two symbols' bars interleave in strict ts order.
- [ ] **Step 2–4: TDD.** → **Step 5: Commit** — `feat: historical replay market-data source`

### Task 22: Backtest runner

**Files:** Create `src/traderbot/backtest/runner.py`, `src/traderbot/backtest/__init__.py`; Test `tests/backtest/test_runner.py`

**Interfaces:** `run_backtest(config, source, bots) -> BacktestResult(equity_curve, per_bot_equity, weights_history, fills)`. Wires `ReplaySource` + `SimulatedFillModel` + `OMS` + `Allocator` + `RiskManager` through `Engine`. Deterministic (seeded).

- [ ] **Step 1: Failing test** — tiny 2-symbol/2-bot fixture runs end-to-end, no crash; `equity_curve` non-empty; attribution sums reconcile; no fill exceeds participation cap.
- [ ] **Step 2–4: TDD.** → **Step 5: Commit** — `feat: backtest runner wiring full engine over replay`

### Task 23: Metrics + allocator-vs-equal-weight

**Files:** Create `src/traderbot/backtest/metrics.py`; Test `tests/backtest/test_metrics.py`

**Interfaces:** `metrics(result) -> dict` (Sharpe, max_drawdown, turnover, hit_rate via empyrical/quantstats); `inter_bot_correlation(per_bot_equity) -> DataFrame`; `equal_weight_benchmark(result) -> equity_curve`; `allocator_beats_equal_weight(result) -> bool`.

- [ ] **Step 1: Failing test** — known equity curve → Sharpe sign correct; equal-weight benchmark computed; correlation matrix shape == n_bots².
- [ ] **Step 2–4: TDD.** → **Step 5: Commit** — `feat: backtest metrics incl. equal-weight benchmark + correlation`

### Task 24: Alpaca adapters (live/paper) behind interfaces

**Files:** Create `src/traderbot/market_data/alpaca_feed.py`, `src/traderbot/execution/alpaca_broker.py`; Test `tests/test_alpaca_adapters.py` (mock the SDK; no network)

**Interfaces:** `AlpacaBroker(api_key, secret, paper=True)` implements `Broker`; `AlpacaFeed` implements `MarketDataSource` (websocket → normalize to types). Corporate-action-adjusted bars via Alpaca adjustment param.

- [ ] **Step 1: Failing test** — with a mocked alpaca client, `AlpacaBroker.submit` maps an `OrderIntent` to the SDK call and returns a normalized `Fill`; `positions()` normalizes SDK positions.
- [ ] **Step 2–4: TDD** (patch the SDK). → **Step 5: Commit** — `feat: Alpaca broker + feed adapters (paper) behind interfaces`

### Task 25: CLI — status / backtest / paper

**Files:** Create `src/traderbot/cli.py`; Modify `pyproject.toml` (`[project.scripts] traderbot = "traderbot.cli:main"`); Test `tests/test_cli.py`

**Interfaces:** `traderbot backtest --from --to`, `traderbot status` (weights, positions, per-bot PnL from store), `traderbot paper` (run engine live-paper). structlog setup.

- [ ] **Step 1: Failing test** — `status` against a seeded store prints weights/PnL (capture stdout); `backtest` on a fixture returns exit 0.
- [ ] **Step 2–4: TDD.** → **Step 5: Commit** — `feat: CLI (status / backtest / paper)`

### Task 26: v1 acceptance harness

**Files:** Create `tests/test_acceptance_v1.py`

**Interfaces:** integration test asserting the §18 DoD checks that are machine-checkable: attribution reconciles every cycle; no risk-limit breach; no fill exceeds participation cap; `total_open_risk ≤ effective cap`; every open position has a stop; allocator-vs-equal-weight reported; dormant bot 5 takes zero allocation.

- [ ] **Step 1: Write the acceptance test** over a multi-day synthetic fixture with all 4 bots + dormant bot 5.
- [ ] **Step 2: Run; fix any integration gaps surfaced.**
- [ ] **Step 3: Commit** — `test: v1 acceptance harness (spec §18 machine-checkable gates)`

---

## Self-Review

- **Spec coverage:** data/calendar/corp-actions (T3,T24) · state (T4) · strategies base+4 bots+dormant (T5,T11–14) · allocator scoring+weights+aggressiveness+dormant exclusion (T7–10) · virtual books + netting + participation fills + carry + revalidation + buying-power + attribution (T7,T17–19) · risk caps/stops/heat/solvency/leverage/kill-switch/watchdog (T15,T16) · recovery/reconcile (T20) · backtest replay+runner+metrics+equal-weight+correlation (T21–23) · Alpaca adapters (T24) · CLI (T25) · acceptance §18 (T26). Phase F (futures/bot 5 activation), heavy-footprint, confidence-gated min-order = explicitly **out of v1** (dormant stub only). Covered.
- **Placeholder scan:** all code-bearing steps carry real code or concrete test asserts; bot tasks state exact entry/exit/stop rules. No TBD.
- **Type consistency:** `BotOutput`/`TargetPosition` (T5) used by all bots + engine; `OrderIntent.stop_price` enforced in risk (T15) and produced by bots; `VirtualBook` (T7) consumed by allocator/OMS; `participation_cap` semantics identical in T18/T19/T22/T26.
