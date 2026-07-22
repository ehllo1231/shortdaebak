from __future__ import annotations

import threading

from app.events import PipelineEvent
from app.gui.tasks import BackgroundTaskRunner, TaskCompleted


def test_background_task_runner_forwards_events_and_prevents_overlap() -> None:
    runner = BackgroundTaskRunner()
    release = threading.Event()

    def work(callback):
        callback(PipelineEvent("INFO", "working", 50, False))
        release.wait(timeout=2)
        return "done"

    assert runner.start("candidate", work) is True
    assert runner.start("script", work) is False
    first = runner.events.get(timeout=2)
    release.set()
    second = runner.events.get(timeout=2)

    assert isinstance(first, PipelineEvent)
    assert isinstance(second, TaskCompleted)
    assert second.result == "done"
    assert second.error is None


def test_background_task_runner_reports_errors() -> None:
    runner = BackgroundTaskRunner()

    def fail(callback):
        raise ValueError("broken")

    assert runner.start("candidate", fail) is True
    completed = runner.events.get(timeout=2)

    assert isinstance(completed, TaskCompleted)
    assert isinstance(completed.error, ValueError)
