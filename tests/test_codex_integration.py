from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.codex_runner import CodexRunner
from app.models import KST
from app.scripting.generator import ScriptGenerator
from tests.helpers import topic_brief


@pytest.mark.integration
def test_live_codex_evaluation(app_config, sample_posts, tmp_path) -> None:
    runner = CodexRunner(
        app_config.codex,
        Path("schemas/candidates.schema.json"),
        Path("prompts/evaluate_candidates.txt"),
    )
    runner.preflight()
    result = runner.evaluate(
        sample_posts[:20],
        datetime.now(KST).date().isoformat(),
        tmp_path / "codex_stderr.log",
    )
    assert len(result["candidates"]) == 5


@pytest.mark.integration
def test_live_codex_script_generation(app_config, sample_posts, tmp_path) -> None:
    runner = ScriptGenerator(
        app_config.codex,
        Path("schemas/script_packages.schema.json"),
        Path("prompts/generate_scripts.txt"),
    )
    runner.preflight()
    topics = (topic_brief(sample_posts[0]),)
    result = runner.generate(
        topics,
        "integration-topic-set",
        tmp_path / "script_codex_stderr.log",
    )
    assert len(result["scripts"]) == 1
    assert result["scripts"][0]["topic_id"] == topics[0].topic_id
