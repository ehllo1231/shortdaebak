from __future__ import annotations

from typing import Protocol

from app.models import Post


class Collector(Protocol):
    def collect(self) -> list[Post]: ...
