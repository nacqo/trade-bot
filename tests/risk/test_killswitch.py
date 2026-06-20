from traderbot.config import RiskCfg
from traderbot.engine.watchdog import Watchdog
from traderbot.risk.risk_manager import RiskManager


def test_per_bot_drawdown_breach():
    rm = RiskManager(RiskCfg(per_bot_dd_kill=0.02))
    assert rm.per_bot_drawdown_breach([100, 102, 99])      # ~2.9% off peak → breach
    assert not rm.per_bot_drawdown_breach([100, 101, 100.5])  # ~0.5% → fine


def test_should_halt_conditions():
    rm = RiskManager(RiskCfg(total_dd_halt=0.05))
    assert not rm.should_halt()
    assert rm.should_halt(drawdown=0.05)
    assert rm.should_halt(margin_util=1.0)
    assert rm.should_halt(watchdog_tripped=True)


def test_manual_halt_latches():
    rm = RiskManager(RiskCfg())
    assert not rm.halted
    rm.halt()
    assert rm.halted
    assert rm.should_halt()


def test_watchdog_trips_without_beat():
    now = {"t": 0.0}
    wd = Watchdog(timeout_s=5.0, clock=lambda: now["t"])
    wd.beat()
    now["t"] = 3.0
    assert not wd.tripped()
    now["t"] = 10.0
    assert wd.tripped()
    wd.beat()
    assert not wd.tripped()
