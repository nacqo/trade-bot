# Path to Live Capital — the efficient, real plan

The product is the **blended daily-factor core**: `momentum + residmom + trend`, one allocator, one
daily rebalance (`traderbot core`). Validated combined: **Sharpe +0.79, maxDD 6.9%** (lower drawdown
than any single strategy — diversification is the point), market-neutral-ish, 62 liquid symbols.

**Honest expectation:** ~8–12%/yr at <7% drawdown *if the edges hold* (Sharpe ~0.8) — steady, not
spectacular. A 2-month stretch: median ~+$100 on $100k, noise-dominated, ~37% chance of a small
loss. This is a survivable, diversified core — not a get-rich engine.

## Why this is the efficient choice
- **One daily rebalance** (cron after the close) → minimal ops + cost.
- **Daily factors** → low turnover → slippage negligible (the reason intraday bots failed).
- **Liquid universe** (large-caps + liquid ETFs) → tight spreads, easy short borrow.
- **Diversified + market-neutral-ish** → low drawdown → survives to compound.

## Phased path (gated — don't skip)

**Phase 0 — DONE.** Core built + combined-backtested + unit-tested. `traderbot core` produces the
allocator-weighted target portfolio and submits deltas to the paper account.

**Phase 1 — Paper soak (2–4 weeks).** Cron `traderbot core` daily on paper. Each day verify:
attribution reconciles (virtual books = broker), fills land near expected, **no risk breaches**,
and paper equity tracks the backtest within tolerance. Gate to live ONLY if all hold.

**Phase 2 — Go live, SMALL.** Flip the broker to live (`build_alpaca_broker(paper=False)`), start
with a **small slice** (e.g. 5–10% of intended capital). Live-friction checklist:
- Margin account (shorts need it); use only **easy-to-borrow** names (the core is large-caps/ETFs).
- **Conservative config:** `deploy_fraction` 0.5–0.7, `max_gross_leverage` 1.0–1.2 (below the 1.5 cap).
- Pay dividends on shorts + small borrow fees (modeled as drag).
- PDT: a once-daily rebalance is a handful of trades — keep ≥ $25k equity for margin, or stay under
  the day-trade count.
- Monitor daily; compare live PnL vs paper/backtest. Halt + investigate on divergence.

**Phase 3 — Scale.** As live tracks expectations over weeks, raise capital gradually.

**Phase 4 — Maintain.** Quarterly walk-forward re-validation (factors decay); run the `evaluation`
skill as the dashboard; widen the universe; add factors (needs paid fundamentals); drop decayed edges.

## Readiness gates before real money
- [ ] Paper soak ≥ 2–4 weeks; equity tracks backtest within tolerance.
- [ ] Reconciliation clean every cycle (virtual = broker net).
- [ ] Zero risk-limit breaches; kill-switch + watchdog verified.
- [ ] Monitoring + alerting on halt/breach/divergence.
- [ ] Conservative live config set; start-small plan written.

## Remaining engineering for live (small)
1. `--live` flag on the CLI to point the broker at the live endpoint (AlpacaBroker already supports `paper=False`).
2. A `monitor` command: daily PnL/positions report + alert on halt/breach/divergence.
3. Conservative live config profile.
4. Long-only fallback for any hard-to-borrow names.
