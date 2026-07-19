from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any

KST = timezone(timedelta(hours=9), name="KST")


@dataclass(slots=True)
class Post:
    id: str
    title: str
    body: str
    url: str
    gallery_id: str
    gallery_name: str
    gallery_type: str
    created_at: datetime
    views: int
    recommendations: int
    comments: int
    source_page: int = 1
    rule_score: float | None = None
    score_components: dict[str, float] = field(default_factory=dict)

    def with_score(self, score: float, components: dict[str, float]) -> Post:
        return replace(self, rule_score=score, score_components=components)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["created_at"] = self.created_at.isoformat()
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Post:
        data = dict(value)
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        return cls(**data)


@dataclass(frozen=True, slots=True)
class HistoryIndex:
    urls: frozenset[str] = frozenset()
    post_keys: frozenset[str] = frozenset()

    @staticmethod
    def key(gallery_id: str, post_id: str) -> str:
        return f"{gallery_id}:{post_id}"
