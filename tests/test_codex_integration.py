from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.codex_runner import CodexRunner
from app.models import KST


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
