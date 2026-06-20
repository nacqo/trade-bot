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

**Five bots** (four active in v1, one dormant):

1. **Statistical arbitrage (pairs)** — market-neutral. Finds cointegrated pairs (statsmodels
   Engle–Granger gate), trades the z-score of the spread, mean-reverting.
2. **Opening Range Breakout (ORB)** — intraday momentum off the session's opening range.
3. **VWAP / Bollinger reversion** — fades stretched moves back toward VWAP.
4. **Order-flow imbalance** — microstructure signal from top-of-book size imbalance + trade flow.
5. **"General trading" (ICT)** — *dormant*. Futures-exclusive (MES/MNQ); activates only once a
   futures broker is wired (a later phase). Ships registered but inactive (zero allocation).

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

```bash
export ALPACA_API_KEY=your_key
export ALPACA_SECRET_KEY=your_secret

# real historical backtest (corporate-action-adjusted bars):
traderbot backtest --symbols KO,PEP --start 2025-01-02 --end 2025-03-01

# connect the paper account (prints equity / buying power / positions):
traderbot paper

# start the live paper loop on a watchlist:
traderbot paper --symbols KO,PEP

# inspect recorded allocations / fills from a run:
traderbot status --db traderbot.sqlite
```

Use **paper** keys first (Alpaca gives separate paper credentials). The first two symbols form the
stat-arb pair; all symbols feed the momentum/reversion bots.

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

v1 core + reality bridge are complete on branch `build/v1` (~98 tests passing): all four active
bots, the meta-allocator, the full risk overlay, honest volume-capped fills, the backtest +
out-of-sample harness, real Alpaca historical backtest, and a live streaming loop.

**Not yet done:**
- **Validation on real data.** The system has never run against a real Alpaca account. The central
  bet — does allocating to recent winners beat equal-weight *out-of-sample* — is untested on real
  returns. This is the most important next step (needs an API key).
- Deferred by design: futures + activating bot 5 (Phase F), dynamic market-impact slippage,
  confidence-gated minimum order sizing.

Deeper docs: `docs/superpowers/HANDOFF.md` (state + decisions + how-to), the design spec and
pre-mortem in `docs/superpowers/specs/`, and the implementation plan in `docs/superpowers/plans/`.

---

## Disclaimer

For research and educational use. No warranty. Not financial advice. You are responsible for any
orders this software places and any losses incurred. Test on paper.
