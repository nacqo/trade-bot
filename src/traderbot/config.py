"""Typed configuration (spec §12 defaults). Nothing in logic is hard-coded — it reads here."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AllocatorCfg(BaseModel):
    tau: float = 0.5  # softmax temperature: →0 winner-take-most, large → equal
    floor: float = 0.05
    cap: float = 0.50
    max_step: float = 0.10  # Δ: max weight change per rebalance (anti-whipsaw)
    ewma_half_life_hours: float = 4.0
    drawdown_penalty: float = 0.5  # λ
    min_obs: int = 30  # cold-start: below this → neutral score
    eps: float = 1e-8
    aggr_min: float = 0.5
    aggr_max: float = 2.0
    aggr_slope: float = 0.5  # k
    rebalance_minutes: int = 15


class RiskCfg(BaseModel):
    per_bot_dd_kill: float = 0.02  # flatten+suspend bot at −2% of sleeve
    max_gross_leverage: float = 1.5  # exposure cap (leverage allowed; loss bounded by stops)
    max_net_frac: float = 0.30  # |net| ≤ 30% equity (roughly neutral)
    per_trade_risk_frac: float = 0.01  # stop-distance position sizing target
    max_total_open_risk_frac: float = 0.10  # portfolio-heat cap
    maintenance_buffer_frac: float = 0.25  # solvency ceiling = equity*(1−this)
    total_dd_halt: float = 0.05  # flatten-all at −5% equity
    max_order_notional_frac: float = 0.05


class ExecutionCfg(BaseModel):
    participation_cap: float = 0.05  # ≤5% of candle volume per fill ("speed limit")
    revalidate_on_carry: bool = True  # re-check entry signal before each carried slice
    slippage_bps: float = 1.0


class DataCfg(BaseModel):
    deploy_fraction: float = 1.0  # fraction of equity deployable (<1 holds a cash buffer)
    feed: str = "iex"  # IEX (free) v1; SIP later
    bar_minutes: int = 1


class Config(BaseModel):
    allocator: AllocatorCfg = Field(default_factory=AllocatorCfg)
    risk: RiskCfg = Field(default_factory=RiskCfg)
    execution: ExecutionCfg = Field(default_factory=ExecutionCfg)
    data: DataCfg = Field(default_factory=DataCfg)
    starting_equity: float = 100_000.0

    @classmethod
    def default(cls) -> "Config":
        return cls()
