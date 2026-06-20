"""Risk overlay — the always-on guard. Authority to veto orders and halt the system.

Two-layer model (spec §9): leverage governs *exposure* (via the buying-power guard, which
already encodes `max_gross_leverage`), while **mandatory stops + a portfolio-heat cap** govern
*loss*. The solvency invariant keeps `total_open_risk ≤ equity − maintenance_buffer`, so even if
every stop triggers at once the account stays solvent (no margin call).
"""

from __future__ import annotations

from dataclasses import dataclass

from traderbot.config import RiskCfg
from traderbot.types import OrderIntent, Position


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    clipped_qty: float


class RiskManager:
    def __init__(self, cfg: RiskCfg) -> None:
        self.cfg = cfg
        self._halted = False

    # --- caps -------------------------------------------------------------
    def effective_open_risk_cap(self, equity: float) -> float:
        frac = min(self.cfg.max_total_open_risk_frac, 1.0 - self.cfg.maintenance_buffer_frac)
        return equity * frac

    def total_open_risk(self, positions: dict[str, Position], stops: dict[str, float]) -> float:
        total = 0.0
        for symbol, pos in positions.items():
            stop = stops.get(symbol)
            if stop is None:
                continue
            total += abs(pos.qty) * abs(pos.avg_price - stop)
        return total

    def gross(self, positions: dict[str, Position], prices: dict[str, float]) -> float:
        return sum(abs(p.qty * prices.get(s, p.avg_price)) for s, p in positions.items())

    def net(self, positions: dict[str, Position], prices: dict[str, float]) -> float:
        return sum(p.qty * prices.get(s, p.avg_price) for s, p in positions.items())

    # --- order gate -------------------------------------------------------
    def check_order(
        self,
        intent: OrderIntent,
        *,
        equity: float,
        positions: dict[str, Position] | None = None,
        buying_power: float,
        open_risk: float,
        price: float | None = None,
    ) -> RiskDecision:
        qty = intent.target_qty
        if qty == 0:
            return RiskDecision(True, "flat/reduce", 0.0)
        if intent.stop_price is None:
            return RiskDecision(False, "missing stop_price", 0.0)
        if price is None:
            return RiskDecision(False, "no price for sizing", 0.0)

        notional = abs(qty) * price
        if notional > buying_power + 1e-9:
            return RiskDecision(False, "insufficient buying power", 0.0)

        new_risk = abs(qty) * abs(price - intent.stop_price)
        if open_risk + new_risk > self.effective_open_risk_cap(equity) + 1e-9:
            return RiskDecision(False, "open risk exceeds heat cap", 0.0)

        return RiskDecision(True, "ok", qty)

    # --- de-gross / halt --------------------------------------------------
    def degross_factor(self, *, margin_util: float, drawdown: float) -> float:
        factor = 1.0
        buffer = self.cfg.maintenance_buffer_frac
        if margin_util > 1.0 - buffer:
            factor = min(factor, max(0.0, (1.0 - margin_util) / buffer)) if buffer > 0 else 0.0
        if drawdown >= self.cfg.total_dd_halt:
            return 0.0
        if drawdown > 0:
            factor *= max(0.0, 1.0 - drawdown / self.cfg.total_dd_halt)
        return max(0.0, min(1.0, factor))

    def per_bot_drawdown_breach(self, equity_curve: list[float]) -> bool:
        """True if a bot drew down ≥ per_bot_dd_kill from its running peak → flatten + suspend."""
        if not equity_curve:
            return False
        peak = equity_curve[0]
        for value in equity_curve:
            peak = max(peak, value)
        if peak <= 0:
            return False
        drawdown = (peak - equity_curve[-1]) / peak
        return drawdown >= self.cfg.per_bot_dd_kill

    def should_halt(
        self, *, drawdown: float = 0.0, margin_util: float = 0.0, watchdog_tripped: bool = False
    ) -> bool:
        return (
            self._halted
            or drawdown >= self.cfg.total_dd_halt
            or margin_util >= 1.0
            or watchdog_tripped
        )

    def halt(self) -> None:
        self._halted = True

    def resume(self) -> None:
        self._halted = False

    @property
    def halted(self) -> bool:
        return self._halted
