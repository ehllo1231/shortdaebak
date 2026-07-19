from __future__ import annotations

from typing import Any

from app.models import Post


def candidate_result(posts: list[Post], run_date: str = "2026-07-19") -> dict[str, Any]:
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
            for rank, post in enumerate(posts[:5], start=1)
        ],
    }
