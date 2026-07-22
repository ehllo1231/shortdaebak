from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PipelineEvent:
    level: str
    message: str
    progress_percent: float | None = None
    progress_complete: bool = False


EventCallback = Callable[[PipelineEvent], None]


class CallbackLogHandler(logging.Handler):
    def __init__(self, callback: EventCallback) -> None:
        super().__init__()
        self.callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        try:
            percent = getattr(record, "progress_percent", None)
            self.callback(
                PipelineEvent(
                    level=record.levelname,
                    message=self.format(record),
                    progress_percent=float(percent) if percent is not None else None,
                    progress_complete=bool(getattr(record, "progress_complete", False)),
                )
            )
        except Exception:
            self.handleError(record)
