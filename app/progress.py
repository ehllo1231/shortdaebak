from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable


def _duration(seconds: float | None) -> str:
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        return "--:--"
    rounded = int(seconds)
    hours, remainder = divmod(rounded, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class ProgressBar:
    """Log a compact progress bar at roughly five-percent intervals."""

    def __init__(
        self,
        label: str,
        total: int,
        logger: logging.Logger,
        *,
        clock: Callable[[], float] = time.monotonic,
        width: int = 24,
    ) -> None:
        self.label = label
        self.total = max(0, total)
        self.logger = logger
        self.clock = clock
        self.width = width
        self.completed = 0
        self.succeeded = 0
        self.failed = 0
        self.started_at = clock()
        self.update_interval = max(1, math.ceil(self.total / 20))

    def start(self) -> None:
        self._render()

    def advance(self, *, success: bool) -> None:
        self.completed = min(self.total, self.completed + 1)
        if success:
            self.succeeded += 1
        else:
            self.failed += 1
        if self.completed == self.total or self.completed % self.update_interval == 0:
            self._render()

    def _render(self) -> None:
        elapsed = max(0.0, self.clock() - self.started_at)
        ratio = self.completed / self.total if self.total else 1.0
        filled = min(self.width, round(self.width * ratio))
        if self.completed > 0 and filled == 0:
            filled = 1
        bar = "#" * filled + "-" * (self.width - filled)
        remaining = None
        if self.completed > 0:
            remaining = elapsed / self.completed * (self.total - self.completed)
        self.logger.info(
            "%s [%s] %d/%d (%5.1f%%) | 성공 %d, 실패 %d | 경과 %s, 남은 약 %s",
            self.label,
            bar,
            self.completed,
            self.total,
            ratio * 100,
            self.succeeded,
            self.failed,
            _duration(elapsed),
            _duration(remaining),
        )
