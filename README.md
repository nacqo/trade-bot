# traderbot

A multi-strategy US-stock trading system with a **risk-adjusted meta-allocator**: several bots
trade different strategies side by side, and a controller continuously shifts capital — and
trading aggressiveness — toward whichever bots have performed best (risk-adjusted) recently, under
an always-on risk overlay. Paper-trading first on [Alpaca](https://alpaca.markets); the
architecture flips to live with a config change.

> ⚠️ **Risk disclaimer.** This is software for algorithmic trading research. Algorithmic trading
> can lose real money quickly. Nothing here is financial advice. Run it on a **paper account**
> until you fully understand it, and never deploy capital you can't afford to lose. The core bet
> (allocating to recent winners) is **unvalidated on real data** — see *Status*.

---

## What it does

The deployable product is a **blended daily-factor core** — three validated, decorrelated edges run
through one meta-allocator, rebalanced once per trading day (`traderbot core`):

1. **Cross-sectional momentum** — long recent winners / short losers across large-caps (vol-scaled
   12-1). Sharpe ≈ +0.9.
2. **Residual (idiosyncratic) momentum** — momentum on *market-residual* returns; market-neutral,
   the highest-rated single edge. Sharpe ≈ +1.0.
3. **Time-series trend** — managed-futures-style own-asset trend across a diversified ETF basket
   (equities / bonds / gold / commodities); the crisis-hedge diversifier.

Blended they reach **Sharpe ≈ +0.8 at < 7% drawdown** — lower drawdown than any single edge
(diversification). The earlier intraday strategies (stat-arb, ORB, VWAP, order-flow) were researched
and dropped: their per-trade edge is smaller than retail transaction costs. The lesson — **edge must
beat cost → low frequency wins** (`docs/superpowers/BACKTEST_FINDINGS.md`).

**The meta-allocator** scores each bot on rolling **risk-adjusted** PnL (EWMA Sharpe-like, drawdown
penalized), then sets two things per bot via a softmax-with-temperature (one knob spanning
winner-take-most ↔ proportional ↔ equal), with a weight **floor** (a cold bot can recover), **cap**
(no over-concentration), and **smoothing** (anti-whipsaw):

- **capital weight** — how much of the deployable capital the bot controls, and
- **aggressiveness** — a hot bot gets a looser trade gate and larger size; a cold bot gets stricter.

**Risk overlay (always on):** every position carries a mandatory stop; total open risk
(`Σ |qty·(entry−stop)|`) is capped so that even if **every stop triggers at once the account stays
solvent** (no margin call); 1.5× gross leverage is allowed for *exposure* but loss is bounded by
stops; a buying-power guard blocks over-spend; per-bot drawdown suspends a losing bot; a portfolio
drawdown halt + watchdog flatten everything.

**Honest execution:** fills are capped at **5% of a bar's real volume** (you can't pretend to buy
more than the market traded); oversized orders fill partially and the remainder carries to the next
bar and re-validates (cancel if the edge is gone). Bots keep virtual books for clean per-bot PnL
attribution; real orders are netted across bots.

**Backtest & live:** a deterministic backtest runner reuses the exact live code paths over
historical replay, with out-of-sample / walk-forward validation that pits the allocator against an
equal-weight benchmark. A live loop streams Alpaca bars and routes orders through the same engine.

---

## Requirements

- **Python 3.11+** (developed/tested on 3.14).
- An **Alpaca account** (free) for real data / paper trading — [alpaca.markets](https://alpaca.markets).
  Not required for the synthetic demo or the test suite.
- Dependencies (installed via `pip`): `alpaca-py`, `statsmodels`, `pandas`, `numpy`, `scipy`,
  `pandas-market-calendars`, `pydantic`, `aiosqlite`, `structlog`.

---

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"            # installs the package + test deps

pytest -q                          # run the test suite (~98 tests)
traderbot backtest                 # synthetic demo backtest (no account needed)
```

The demo prints metrics (Sharpe, max drawdown, turnover) and the **out-of-sample allocator vs
equal-weight** comparison — the key question of whether the allocator adds value.

### Real data & paper trading (needs an Alpaca key)

Put your keys in a gitignored `.env` (auto-loaded) or export them:

```bash
export ALPACA_API_KEY=your_paper_key
export ALPACA_SECRET_KEY=your_paper_secret

# THE PRODUCT — blended daily-factor core, one rebalance/day (run via cron after the close):
traderbot core               # paper account (default)
traderbot core --live        # LIVE account, conservative sizing (deploy 0.6, leverage 1.2)

# monitor the account (equity / gross / net / positions + alerts):
traderbot monitor            # add --live for the live account

# individual factor rebalances (for research):
traderbot momentum           # cross-sectional momentum
traderbot residmom           # residual momentum
traderbot trend              # time-series trend (ETF basket)

# cancel all open orders / inspect a run:
traderbot cancel
traderbot status --db traderbot.sqlite

# real historical backtest + rank/rate every strategy:
traderbot backtest --symbols KO,PEP --start 2025-01-02 --end 2025-03-01
python scripts/evaluate.py   # the `evaluation` skill: ranking + ratings + 2-month sim
```

Use **paper** keys first (Alpaca gives separate paper credentials). Start with a paper soak
(`traderbot core` daily) before going `--live` — see the go-live plan in
[`docs/superpowers/GO_LIVE.md`](docs/superpowers/GO_LIVE.md).

---

## Configuration

All knobs live in `src/traderbot/config.py` (pydantic, spec defaults). The most important:

| Knob | Default | Meaning |
|---|---|---|
| `allocator.tau` | 0.5 | concentration: →0 winner-take-most, large → equal |
| `allocator.ewma_half_life_hours` | 4.0 | how fast the allocator forgets old performance |
| `allocator.floor` / `cap` | 0.05 / 0.50 | min/max capital weight per bot |
| `risk.max_gross_leverage` | 1.5 | exposure cap (loss is bounded by stops, not this) |
| `risk.max_total_open_risk_frac` | 0.10 | portfolio "heat": Σ risk-to-stop ≤ this × equity |
| `risk.per_bot_dd_kill` | 0.02 | per-bot drawdown that suspends a bot |
| `risk.total_dd_halt` | 0.05 | portfolio drawdown that halts + flattens everything |
| `execution.participation_cap` | 0.05 | max fraction of a bar's volume any fill may take |

---

## Architecture

Single async engine (`src/traderbot/`): data source → bots (`strategies/`) emit target positions →
allocator (`allocator/`) sets capital + aggressiveness → risk admission (`risk/`) → OMS
(`execution/`: netting, participation-capped fills, attribution) → broker. State in SQLite
(`state/`). Backtest (`backtest/`) and live (`live.py`, `integrations/alpaca.py`,
`market_data/alpaca_live.py`) reuse the same engine — only the broker and data source differ.

---

## Status

On branch `build/v1`, **99 tests passing**. The engine, meta-allocator, full risk overlay, honest
volume-capped fills, backtest + OOS harness, real Alpaca data, and the live runners are complete.

**Research journey (honest):** many strategies were built and rigorously backtested. The intraday
ones (stat-arb, ORB, VWAP, order-flow) have **no retail edge** — per-trade edge < transaction cost —
and were dropped. Cross-sectional research found the real, OOS-stable edges: **momentum**, **residual
momentum**, and **time-series trend**. Blended through one allocator (`traderbot core`): **Sharpe
≈ +0.8 at < 7% drawdown**, market-neutral-ish, low turnover. Write-up:
[`BACKTEST_FINDINGS.md`](docs/superpowers/BACKTEST_FINDINGS.md). Re-rank anytime with the `evaluation`
skill (`python scripts/evaluate.py`).

**Path to live capital:** paper-soak → small live → scale, with readiness gates —
[`GO_LIVE.md`](docs/superpowers/GO_LIVE.md). Honest expectation: ~8–12%/yr at < 7% drawdown *if the
edges hold* — steady and diversified, not a moonshot.

Deeper docs: `docs/superpowers/` (HANDOFF, specs, pre-mortem, plan, findings, go-live).

---

## Disclaimer

For research and educational use. No warranty. Not financial advice. You are responsible for any
orders this software places and any losses incurred. Test on paper.
