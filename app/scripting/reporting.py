from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from app.scripting.models import TopicBrief
from app.storage import write_text_atomic


def render_script_report(
    output_path: Path,
    *,
    brief_set_id: str,
    generated_at: datetime,
    status: str,
    topics: tuple[TopicBrief, ...],
    packages: dict[str, Any] | None,
    codex_error: str | None = None,
    candidate_report_href: str | None = None,
) -> None:
    templates = Path(__file__).parent / "templates"
    environment = Environment(
        loader=FileSystemLoader(templates),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = environment.get_template("script_report.html.j2")
    html = template.render(
        brief_set_id=brief_set_id,
        generated_at=generated_at,
        status=status,
        topics=topics,
        topics_by_id={topic.topic_id: topic for topic in topics},
        scripts=(packages or {}).get("scripts", []),
        codex_error=codex_error,
        candidate_report_href=candidate_report_href,
    )
    write_text_atomic(output_path, html)
