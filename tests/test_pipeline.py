from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime

from app.codex_runner import CodexError
from app.models import KST
from app.pipeline import run_pipeline
from tests.helpers import candidate_result


class FakeCrawler:
    posts = []

    def __init__(self, config, logger=None):
        self.config = config

    def collect(self):
        return list(self.posts)


class SuccessfulRunner:
    posts = []

    def __init__(self, config, schema_path, prompt_path, logger=None):
        self.config = config

    def preflight(self):
        return "codex-cli test"

    def evaluate(self, posts, run_date, stderr_path):
        stderr_path.write_text("", encoding="utf-8")
        return candidate_result(posts, run_date, self.config.final_candidate_count)


class FailedPreflightRunner(SuccessfulRunner):
    def preflight(self):
        raise CodexError("ChatGPT 로그인이 필요합니다.", code="login_required")


def test_pipeline_success_creates_timestamped_artifacts(app_config, sample_posts) -> None:
    FakeCrawler.posts = sample_posts

    result = run_pipeline(
        app_config,
        now=datetime(2026, 7, 19, 12, 34, 56, tzinfo=KST),
        crawler_factory=FakeCrawler,
        codex_runner_factory=SuccessfulRunner,
    )

    assert result.exit_code == 0
    assert result.output_directory.parts[-2:] == ("2026-07-19", "123456")
    assert (result.output_directory / "raw_posts.json").is_file()
    assert (result.output_directory / "prefiltered.json").is_file()
    assert (result.output_directory / "candidates.json").is_file()
    assert (result.output_directory / "report.html").is_file()
    run = json.loads((result.output_directory / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "success"
    assert run["prefiltered_count"] == 20


def test_pipeline_uses_custom_final_candidate_count(app_config, sample_posts) -> None:
    FakeCrawler.posts = sample_posts
    custom_config = replace(
        app_config,
        codex=replace(app_config.codex, final_candidate_count=3),
    )

    result = run_pipeline(
        custom_config,
        now=datetime(2026, 7, 19, 12, 40, tzinfo=KST),
        crawler_factory=FakeCrawler,
        codex_runner_factory=SuccessfulRunner,
    )

    candidates = json.loads(
        (result.output_directory / "candidates.json").read_text(encoding="utf-8")
    )
    report = (result.output_directory / "report.html").read_text(encoding="utf-8")
    assert len(candidates["candidates"]) == 3
    assert "최종 3개를 선정했습니다." in report


def test_pipeline_codex_failure_keeps_collection_and_fallback(app_config, sample_posts) -> None:
    FakeCrawler.posts = sample_posts

    result = run_pipeline(
        app_config,
        now=datetime(2026, 7, 19, 13, 0, tzinfo=KST),
        crawler_factory=FakeCrawler,
        codex_runner_factory=FailedPreflightRunner,
    )

    assert result.exit_code == 4
    assert not (result.output_directory / "candidates.json").exists()
    assert (result.output_directory / "raw_posts.json").is_file()
    report = (result.output_directory / "report.html").read_text(encoding="utf-8")
    assert "규칙 기반 임시 후보" in report
    run = json.loads((result.output_directory / "run.json").read_text(encoding="utf-8"))
    assert run["codex"]["error_code"] == "login_required"


def test_codex_failure_does_not_pollute_next_run_history(app_config, sample_posts) -> None:
    FakeCrawler.posts = sample_posts
    failed = run_pipeline(
        app_config,
        now=datetime(2026, 7, 19, 13, 30, tzinfo=KST),
        crawler_factory=FakeCrawler,
        codex_runner_factory=FailedPreflightRunner,
    )
    retried = run_pipeline(
        app_config,
        now=datetime(2026, 7, 19, 13, 31, tzinfo=KST),
        crawler_factory=FakeCrawler,
        codex_runner_factory=SuccessfulRunner,
    )

    assert failed.status == "codex_fallback"
    assert retried.status == "success"
    run = json.loads((retried.output_directory / "run.json").read_text(encoding="utf-8"))
    assert "history_duplicate" not in run["exclusions"]


def test_second_run_does_not_overwrite_first_and_uses_history(app_config, sample_posts) -> None:
    FakeCrawler.posts = sample_posts
    first = run_pipeline(
        app_config,
        now=datetime(2026, 7, 19, 14, 0, tzinfo=KST),
        crawler_factory=FakeCrawler,
        codex_runner_factory=SuccessfulRunner,
    )
    second = run_pipeline(
        app_config,
        now=datetime(2026, 7, 19, 14, 0, tzinfo=KST),
        crawler_factory=FakeCrawler,
        codex_runner_factory=SuccessfulRunner,
    )

    assert first.output_directory != second.output_directory
    assert second.output_directory.name == "140000-01"
    run = json.loads((second.output_directory / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "insufficient_candidates"
    assert run["exclusions"]["history_duplicate"] == 25


def test_pipeline_can_forward_log_events_to_gui(app_config, sample_posts) -> None:
    FakeCrawler.posts = sample_posts
    events = []

    result = run_pipeline(
        app_config,
        now=datetime(2026, 7, 19, 15, 0, tzinfo=KST),
        crawler_factory=FakeCrawler,
        codex_runner_factory=SuccessfulRunner,
        event_callback=events.append,
    )

    assert result.status == "success"
    assert any("실행 시작" in event.message for event in events)
    assert any("Codex 평가 완료" in event.message for event in events)
