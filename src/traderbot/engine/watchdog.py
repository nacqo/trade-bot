"""Dead-man switch. If the loop/feed stops calling beat() within timeout, it trips → the engine
cancels working orders and (configurably) flattens, so positions are never left unmanaged.
"""

from __future__ import annotations

import time
from typing import Callable


class Watchdog:
    def __init__(self, timeout_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.timeout_s = timeout_s
        self._clock = clock
        self._last = clock()

    def beat(self) -> None:
        self._last = self._clock()

    def tripped(self) -> bool:
        return (self._clock() - self._last) > self.timeout_s
