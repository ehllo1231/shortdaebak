from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from app.models import Post
from app.storage import write_text_atomic


def _excerpt(body: str, limit: int = 240) -> str:
    text = " ".join(body.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def build_fallback_candidates(posts: list[Post]) -> list[dict[str, Any]]:
    return [
        {
            "rank": index,
            "post_id": post.id,
            "title": post.title,
            "url": post.url,
            "excerpt": _excerpt(post.body),
            "rule_score": post.rule_score,
            "views": post.views,
            "recommendations": post.recommendations,
            "comments": post.comments,
            "gallery_name": post.gallery_name,
        }
        for index, post in enumerate(posts[:5], start=1)
    ]


def render_report(
    output_path: Path,
    *,
    run_id: str,
    generated_at: datetime,
    status: str,
    candidates: list[dict[str, Any]],
    collection_count: int,
    prefiltered_count: int,
    codex_error: str | None = None,
) -> None:
    templates = Path(__file__).parent / "templates"
    environment = Environment(
        loader=FileSystemLoader(templates),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = environment.get_template("report.html.j2")
    html = template.render(
        run_id=run_id,
        generated_at=generated_at,
        status=status,
        candidates=candidates,
        collection_count=collection_count,
        prefiltered_count=prefiltered_count,
        codex_error=codex_error,
    )
    write_text_atomic(output_path, html)
