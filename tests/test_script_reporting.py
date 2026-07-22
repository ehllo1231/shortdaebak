from __future__ import annotations

from datetime import datetime

from app.models import KST
from app.scripting.reporting import render_script_report
from tests.helpers import script_result, topic_brief


def test_script_report_escapes_generated_and_source_text(tmp_path, sample_posts) -> None:
    topic = topic_brief(sample_posts[0])
    packages = script_result((topic,))
    packages["scripts"][0]["script_title"] = "<script>alert(1)</script>"
    packages["scripts"][0]["segments"][0]["narration"] = "<img src=x onerror=alert(1)>"
    output_path = tmp_path / "script_report.html"

    render_script_report(
        output_path,
        brief_set_id="120000",
        generated_at=datetime(2026, 7, 19, 15, tzinfo=KST),
        status="success",
        topics=(topic,),
        packages=packages,
        candidate_report_href="../../report.html",
    )

    html = output_path.read_text(encoding="utf-8")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "noopener noreferrer" in html
    assert html.count("<br><br>") == 4
