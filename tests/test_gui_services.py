from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.gui.services import (
    GuiInputError,
    find_recent_reports,
    load_candidate_report,
    parse_gallery_input,
)
from tests.helpers import candidate_result


def _write_report_run(
    path: Path, sample_posts, *, started_at: str, status: str = "success"
) -> None:
    path.mkdir(parents=True)
    run_id = path.name
    (path / "report.html").write_text("<html>report</html>", encoding="utf-8")
    (path / "run.json").write_text(
        json.dumps({"run_id": run_id, "started_at": started_at, "status": status}),
        encoding="utf-8",
    )
    (path / "candidates.json").write_text(
        json.dumps(candidate_result(sample_posts, run_date=started_at[:10]), ensure_ascii=False),
        encoding="utf-8",
    )
    (path / "raw_posts.json").write_text(
        json.dumps(
            {"run_id": run_id, "posts": [post.to_dict() for post in sample_posts]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("value", "selected_type", "expected"),
    [
        ("story", "major", ("story", "major")),
        (
            "https://gall.dcinside.com/board/lists/?id=baseball_new11",
            "minor",
            ("baseball_new11", "major"),
        ),
        (
            "https://gall.dcinside.com/mgallery/board/lists/?id=projectmx",
            "major",
            ("projectmx", "minor"),
        ),
    ],
)
def test_parse_gallery_input_supports_id_and_known_urls(value, selected_type, expected) -> None:
    assert parse_gallery_input(value, selected_type) == expected


def test_parse_gallery_input_rejects_mini_or_external_urls() -> None:
    with pytest.raises(GuiInputError, match="미니"):
        parse_gallery_input("https://gall.dcinside.com/mini/board/lists/?id=small", "major")
    with pytest.raises(GuiInputError, match="DCInside"):
        parse_gallery_input("https://example.com/board/lists/?id=story", "major")


def test_load_candidate_report_validates_siblings_and_returns_choices(
    tmp_path, sample_posts
) -> None:
    run = tmp_path / "output" / "2026-07-19" / "120000"
    _write_report_run(run, sample_posts, started_at="2026-07-19T12:00:00+09:00")

    report = load_candidate_report(run / "report.html")

    assert report.run_id == "120000"
    assert len(report.candidates) == 5
    assert report.candidates[0].title == sample_posts[0].title
    assert "후보 5개" in report.display_name


def test_find_recent_reports_sorts_successful_valid_runs_and_applies_limit(
    tmp_path, sample_posts
) -> None:
    base = tmp_path / "output"
    _write_report_run(
        base / "2026-07-19" / "120000",
        sample_posts,
        started_at="2026-07-19T12:00:00+09:00",
    )
    _write_report_run(
        base / "2026-07-20" / "130000",
        sample_posts,
        started_at="2026-07-20T13:00:00+09:00",
    )
    _write_report_run(
        base / "2026-07-21" / "140000",
        sample_posts,
        started_at="2026-07-21T14:00:00+09:00",
        status="codex_fallback",
    )

    reports = find_recent_reports(base, limit=1)

    assert len(reports) == 1
    assert reports[0].run_id == "130000"


def test_load_candidate_report_rejects_unrelated_html(tmp_path) -> None:
    path = tmp_path / "report.html"
    path.write_text("<html></html>", encoding="utf-8")

    with pytest.raises(GuiInputError, match="후보 결과"):
        load_candidate_report(path)
