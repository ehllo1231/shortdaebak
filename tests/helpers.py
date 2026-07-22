from __future__ import annotations

from typing import Any

from app.models import Post
from app.scripting.models import SourceReference, TopicBrief, TopicProvenance


def candidate_result(
    posts: list[Post], run_date: str = "2026-07-19", count: int = 5
) -> dict[str, Any]:
    return {
        "run_date": run_date,
        "evaluation_status": "codex",
        "candidates": [
            {
                "rank": rank,
                "post_id": post.id,
                "title": post.title,
                "url": post.url,
                "summary": f"{post.title}의 핵심 내용을 요약한다.",
                "reason": "전개가 명확하고 시작 훅이 강하다.",
                "hook": "예상하지 못한 일이 벌어졌다.",
                "fun_score": 70 + rank,
                "twist_score": 65 + rank,
                "clarity_score": 80,
                "shorts_fit_score": 85,
                "total_score": 80 - rank,
                "risks": [],
                "risk_level": "low",
                "review_notes": "원문의 사실 관계를 추가로 확인해야 한다.",
            }
            for rank, post in enumerate(posts[:count], start=1)
        ],
    }


def topic_brief(
    post: Post,
    *,
    source_run_id: str = "120000",
    rank: int = 1,
    risk_level: str = "low",
) -> TopicBrief:
    return TopicBrief(
        topic_id=f"{source_run_id}:{post.gallery_id}:{post.id}",
        origin="community_candidate",
        title=post.title,
        summary=f"{post.title}의 핵심 내용을 요약한다.",
        source_material=post.body,
        source_material_original_length=len(post.body),
        source_material_truncated=False,
        desired_angle="전개가 명확하고 시작 훅이 강하다.",
        audience="YouTube Shorts 일반 시청자",
        hook_candidates=("예상하지 못한 일이 벌어졌다.",),
        source_references=(
            SourceReference(
                id="source_post",
                source_type="community_post",
                title=post.title,
                url=post.url,
            ),
        ),
        risk_level=risk_level,
        risk_notes=("원문의 사실 관계를 추가로 확인해야 한다.",),
        uncertainties=("커뮤니티 게시물의 주장은 사실 확인되지 않았습니다.",),
        provenance=TopicProvenance(source_run_id, rank, post.id),
    )


def script_result(
    topics: tuple[TopicBrief, ...],
    brief_set_id: str = "120000",
) -> dict[str, Any]:
    roles = ("hook", "setup", "development", "payoff", "closing")
    durations = (5, 10, 13, 13, 10)
    return {
        "schema_version": "1.0",
        "brief_set_id": brief_set_id,
        "generation_status": "codex",
        "scripts": [
            {
                "topic_id": topic.topic_id,
                "origin": topic.origin,
                "topic_title": topic.title,
                "script_title": f"{topic.title}의 반전",
                "style_id": "immersive_story_question",
                "estimated_duration_seconds": sum(durations),
                "segments": [
                    {
                        "order": order,
                        "role": role,
                        "narration": (
                            "예상하지 못한 일이 벌어졌습니다."
                            if role != "closing"
                            else "여러분이라면 어떻게 생각하실 건가요?"
                        ),
                        "on_screen_text": f"{role} 화면 자막",
                        "estimated_seconds": duration,
                        "source_basis": "원문에 설명된 사건 전개를 각색했다.",
                        "source_reference_ids": [topic.source_references[0].id],
                    }
                    for order, (role, duration) in enumerate(
                        zip(roles, durations, strict=True), start=1
                    )
                ],
                "source_references": [reference.to_dict() for reference in topic.source_references],
                "risk_level": topic.risk_level,
                "risk_notes": list(topic.risk_notes),
                "uncertainties": list(topic.uncertainties),
                "requires_human_review": True,
                "review_warnings": [*topic.risk_notes, *topic.uncertainties],
            }
            for topic in topics
        ],
    }
