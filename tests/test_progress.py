from __future__ import annotations

import logging

from app.progress import ProgressBar


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_progress_bar_reports_counts_elapsed_time_and_eta(caplog) -> None:
    clock = FakeClock()
    logger = logging.getLogger("progress-test")
    progress = ProgressBar("본문 수집", 20, logger, clock=clock, width=10)

    with caplog.at_level(logging.INFO, logger="progress-test"):
        progress.start()
        clock.now = 2
        progress.advance(success=True)
        clock.now = 4
        progress.advance(success=False)

    messages = [record.message for record in caplog.records]
    assert "0/20" in messages[0]
    assert "[#---------]" in messages[1]
    assert "성공 1, 실패 0" in messages[1]
    assert "남은 약 00:38" in messages[1]
    assert "성공 1, 실패 1" in messages[2]
