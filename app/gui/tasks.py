from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.events import EventCallback, PipelineEvent


@dataclass(frozen=True, slots=True)
class TaskCompleted:
    name: str
    result: Any | None = None
    error: Exception | None = None


GuiEvent = PipelineEvent | TaskCompleted
TaskWork = Callable[[EventCallback], Any]


class BackgroundTaskRunner:
    def __init__(self) -> None:
        self.events: queue.Queue[GuiEvent] = queue.Queue()
        self._lock = threading.Lock()
        self._busy = False

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    def start(self, name: str, work: TaskWork) -> bool:
        with self._lock:
            if self._busy:
                return False
            self._busy = True

        def run() -> None:
            try:
                result = work(self.events.put)
                completed = TaskCompleted(name=name, result=result)
            except Exception as exc:
                completed = TaskCompleted(name=name, error=exc)
            with self._lock:
                self._busy = False
            self.events.put(completed)

        threading.Thread(target=run, name=f"shorts-{name}", daemon=False).start()
        return True

    def drain(self) -> tuple[GuiEvent, ...]:
        items: list[GuiEvent] = []
        while True:
            try:
                items.append(self.events.get_nowait())
            except queue.Empty:
                return tuple(items)
