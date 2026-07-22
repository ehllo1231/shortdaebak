from __future__ import annotations

import logging

from app.events import CallbackLogHandler
from app.progress import ProgressBar


def test_callback_log_handler_forwards_structured_progress() -> None:
    events = []
    logger = logging.Logger("gui-progress-test")
    handler = CallbackLogHandler(events.append)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(handler)
    progress = ProgressBar("본문 수집", 2, logger, width=4)

    progress.start()
    progress.advance(success=True)
    progress.advance(success=True)

    assert events[0].progress_percent == 0
    assert events[-1].progress_percent == 100
    assert events[-1].progress_complete is True
    assert "본문 수집" in events[-1].message
