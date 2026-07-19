from __future__ import annotations

from datetime import datetime

from app.models import KST
from app.reporting import build_fallback_candidates, render_report
from tests.helpers import candidate_result


def test_codex_report_escapes_external_text(tmp_path, sample_posts) -> None:
    candidates = candidate_result(sample_posts)["candidates"]
    candidates[0]["title"] = "<script>alert(1)</script>"
    path = tmp_path / "report.html"

    render_report(
        path,
        run_id="120000",
        generated_at=datetime(2026, 7, 19, 12, tzinfo=KST),
        status="success",
        candidates=candidates,
        collection_count=20,
        prefiltered_count=20,
    )

    html = path.read_text(encoding="utf-8")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "noopener noreferrer" in html


def test_fallback_report_is_clearly_labeled(tmp_path, sample_posts) -> None:
    candidates = build_fallback_candidates(sample_posts)
    path = tmp_path / "report.html"

    render_report(
        path,
        run_id="120000",
        generated_at=datetime(2026, 7, 19, 12, tzinfo=KST),
        status="codex_fallback",
        candidates=candidates,
        collection_count=20,
        prefiltered_count=20,
        codex_error="사용량 제한",
    )

    html = path.read_text(encoding="utf-8")
    assert "Codex 평가가 실패하여 규칙 기반 임시 후보" in html
    assert "사용량 제한" in html
    assert "종합" not in html
