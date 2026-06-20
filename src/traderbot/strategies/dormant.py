"""Dormant bot stub (bot 5). Registered but inactive until futures support (Phase F).

Emits nothing and is excluded from allocation (the allocator gives non-active bots zero
weight). Keeps the engine/allocator/config wired for N bots so activation is additive.
"""

from __future__ import annotations

from traderbot.strategies.base import BotOutput, Strategy


class DormantBot(Strategy):
    def __init__(self, id: str, instrument_note: str = "") -> None:
        super().__init__(id)
        self.enabled = False
        self.instrument_note = instrument_note

    def evaluate(self) -> BotOutput:
        return BotOutput(targets=[], signal_strength=0.0, enabled=False)
