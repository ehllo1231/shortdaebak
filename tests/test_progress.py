from __future__ import annotations

import logging
from io import StringIO

from app.progress import ProgressBar, ProgressStreamHandler


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


def test_progress_bar_updates_at_roughly_two_percent(caplog) -> None:
    logger = logging.getLogger("progress-frequency-test")
    progress = ProgressBar("본문 수집", 100, logger)

    with caplog.at_level(logging.INFO, logger="progress-frequency-test"):
        progress.start()
        progress.advance(success=True)
        progress.advance(success=True)

    assert len(caplog.records) == 2
    assert "2/100" in caplog.records[-1].message


def test_progress_stream_handler_rewrites_line_until_complete() -> None:
    stream = StringIO()
    handler = ProgressStreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger = logging.Logger("progress-stream-test")
    logger.addHandler(handler)
    progress = ProgressBar("본문 수집", 2, logger, width=4)

    progress.start()
    progress.advance(success=True)
    progress.advance(success=True)

    output = stream.getvalue()
    assert output.count("\r") == 3
    assert output.count("\n") == 1
    assert "0/2" in output
    assert "2/2" in output
