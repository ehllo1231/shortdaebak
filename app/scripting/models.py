from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

TOPIC_BRIEF_SCHEMA_VERSION = "1.0"
SCRIPT_PACKAGE_SCHEMA_VERSION = "1.0"
SCRIPT_STYLE_ID = "immersive_story_question"
TARGET_DURATION_MIN_SECONDS = 45
TARGET_DURATION_MAX_SECONDS = 60
MAX_SOURCE_MATERIAL_CHARACTERS = 6_000


@dataclass(frozen=True, slots=True)
class SourceReference:
    id: str
    source_type: str
    title: str
    url: str
    verification_status: str = "unverified_community_post"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TopicProvenance:
    source_run_id: str
    candidate_rank: int
    post_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TopicBrief:
    topic_id: str
    origin: str
    title: str
    summary: str
    source_material: str
    source_material_original_length: int
    source_material_truncated: bool
    desired_angle: str
    audience: str
    hook_candidates: tuple[str, ...]
    source_references: tuple[SourceReference, ...]
    risk_level: str
    risk_notes: tuple[str, ...]
    uncertainties: tuple[str, ...]
    provenance: TopicProvenance | None
    schema_version: str = TOPIC_BRIEF_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "topic_id": self.topic_id,
            "origin": self.origin,
            "title": self.title,
            "summary": self.summary,
            "source_material": self.source_material,
            "source_material_original_length": self.source_material_original_length,
            "source_material_truncated": self.source_material_truncated,
            "desired_angle": self.desired_angle,
            "audience": self.audience,
            "hook_candidates": list(self.hook_candidates),
            "source_references": [reference.to_dict() for reference in self.source_references],
            "risk_level": self.risk_level,
            "risk_notes": list(self.risk_notes),
            "uncertainties": list(self.uncertainties),
            "provenance": self.provenance.to_dict() if self.provenance is not None else None,
        }


def topic_briefs_payload(brief_set_id: str, topics: tuple[TopicBrief, ...]) -> dict[str, Any]:
    return {
        "schema_version": TOPIC_BRIEF_SCHEMA_VERSION,
        "brief_set_id": brief_set_id,
        "count": len(topics),
        "topics": [topic.to_dict() for topic in topics],
    }
