from __future__ import annotations

import json
from datetime import datetime

from app.codex_runner import CodexError
from app.models import KST
from app.scripting.pipeline import run_script_pipeline
from tests.helpers import candidate_result, script_result


def _write_source_run(path, sample_posts) -> None:
    path.mkdir(parents=True)
    (path / "run.json").write_text(
        json.dumps(
            {
                "run_id": "120000",
                "started_at": "2026-07-19T12:00:00+09:00",
                "status": "success",
            }
        ),
        encoding="utf-8",
    )
    candidates = candidate_result(sample_posts)
    candidates["candidates"][0]["risk_level"] = "high"
    candidates["candidates"][0]["risks"] = ["식별 가능성"]
    (path / "candidates.json").write_text(
        json.dumps(candidates, ensure_ascii=False), encoding="utf-8"
    )
    (path / "raw_posts.json").write_text(
        json.dumps(
            {"run_id": "120000", "posts": [post.to_dict() for post in sample_posts]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (path / "report.html").write_text("candidate report", encoding="utf-8")


class SuccessfulScriptGenerator:
    def __init__(self, config, schema_path, prompt_path, logger=None):
        self.config = config

    def preflight(self):
        return "codex-cli test"

    def generate(self, topics, source_run_id, stderr_path):
        stderr_path.write_text("", encoding="utf-8")
        return script_result(topics, source_run_id)


class FailedScriptGenerator(SuccessfulScriptGenerator):
    def generate(self, topics, source_run_id, stderr_path):
        raise CodexError("사용량 제한", code="usage_limit")


def test_script_pipeline_creates_traceable_artifacts_and_high_risk_warning(
    app_config, sample_posts, tmp_path
) -> None:
    source_run = tmp_path / "output" / "2026-07-19" / "120000"
    _write_source_run(source_run, sample_posts)

    result = run_script_pipeline(
        app_config,
        source_run,
        (1, 3),
        now=datetime(2026, 7, 19, 15, 0, tzinfo=KST),
        generator_factory=SuccessfulScriptGenerator,
    )

    assert result.exit_code == 0
    assert result.output_directory == source_run / "scripts" / "150000"
    for name in (
        "topic_briefs.json",
        "script_packages.json",
        "script_report.html",
        "script_run.json",
        "script_run.log",
        "codex_stderr.log",
    ):
        assert (result.output_directory / name).is_file()
    report = (result.output_directory / "script_report.html").read_text(encoding="utf-8")
    assert "고위험 후보입니다" in report
    assert "녹음용 합본" in report
    assert "../../report.html" in report


def test_script_pipeline_failure_keeps_inputs_but_not_packages(
    app_config, sample_posts, tmp_path
) -> None:
    source_run = tmp_path / "output" / "2026-07-19" / "120000"
    _write_source_run(source_run, sample_posts)

    result = run_script_pipeline(
        app_config,
        source_run,
        (1,),
        now=datetime(2026, 7, 19, 15, 10, tzinfo=KST),
        generator_factory=FailedScriptGenerator,
    )

    assert result.exit_code == 4
    assert (result.output_directory / "topic_briefs.json").is_file()
    assert not (result.output_directory / "script_packages.json").exists()
    run_state = json.loads(
        (result.output_directory / "script_run.json").read_text(encoding="utf-8")
    )
    assert run_state["status"] == "codex_failed"
    assert run_state["codex"]["error_code"] == "usage_limit"


def test_script_pipeline_does_not_overwrite_same_second_run(
    app_config, sample_posts, tmp_path
) -> None:
    source_run = tmp_path / "output" / "2026-07-19" / "120000"
    _write_source_run(source_run, sample_posts)
    now = datetime(2026, 7, 19, 15, 20, tzinfo=KST)

    first = run_script_pipeline(
        app_config,
        source_run,
        (1,),
        now=now,
        generator_factory=SuccessfulScriptGenerator,
    )
    second = run_script_pipeline(
        app_config,
        source_run,
        (1,),
        now=now,
        generator_factory=SuccessfulScriptGenerator,
    )

    assert first.output_directory.name == "152000"
    assert second.output_directory.name == "152000-01"
