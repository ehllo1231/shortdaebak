from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.scripting import ScriptInputError, load_community_topic_briefs
from tests.helpers import candidate_result


def _write_source_run(path: Path, sample_posts, *, status: str = "success") -> None:
    path.mkdir(parents=True)
    (path / "run.json").write_text(
        json.dumps(
            {
                "run_id": "120000",
                "started_at": "2026-07-19T12:00:00+09:00",
                "status": status,
            }
        ),
        encoding="utf-8",
    )
    (path / "candidates.json").write_text(
        json.dumps(candidate_result(sample_posts), ensure_ascii=False),
        encoding="utf-8",
    )
    (path / "raw_posts.json").write_text(
        json.dumps(
            {"run_id": "120000", "posts": [post.to_dict() for post in sample_posts]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_community_adapter_builds_source_independent_topic_briefs(tmp_path, sample_posts) -> None:
    run_directory = tmp_path / "120000"
    _write_source_run(run_directory, sample_posts)

    source_run_id, topics = load_community_topic_briefs(run_directory, (3, 1))

    assert source_run_id == "120000"
    assert [topic.provenance.candidate_rank for topic in topics] == [1, 3]
    assert all(topic.origin == "community_candidate" for topic in topics)
    assert topics[0].source_references[0].url == sample_posts[0].url
    assert "사실 확인되지 않았습니다" in topics[0].uncertainties[0]


def test_community_adapter_preserves_high_risk_and_truncation(tmp_path, sample_posts) -> None:
    sample_posts[0].body = "가" * 6_100
    run_directory = tmp_path / "120000"
    _write_source_run(run_directory, sample_posts)
    candidates = json.loads((run_directory / "candidates.json").read_text(encoding="utf-8"))
    candidates["candidates"][0]["risk_level"] = "high"
    candidates["candidates"][0]["risks"] = ["식별 가능성"]
    (run_directory / "candidates.json").write_text(
        json.dumps(candidates, ensure_ascii=False), encoding="utf-8"
    )

    _, topics = load_community_topic_briefs(run_directory, (1,))

    assert topics[0].risk_level == "high"
    assert "식별 가능성" in topics[0].risk_notes
    assert topics[0].source_material_truncated is True
    assert len(topics[0].source_material) == 6_000


@pytest.mark.parametrize("status", ["codex_fallback", "insufficient_candidates"])
def test_community_adapter_rejects_unsuccessful_candidate_runs(
    tmp_path, sample_posts, status
) -> None:
    run_directory = tmp_path / "120000"
    _write_source_run(run_directory, sample_posts, status=status)

    with pytest.raises(ScriptInputError, match="성공한 실행"):
        load_community_topic_briefs(run_directory, (1,))


def test_community_adapter_rejects_duplicate_or_unknown_ranks(tmp_path, sample_posts) -> None:
    run_directory = tmp_path / "120000"
    _write_source_run(run_directory, sample_posts)

    with pytest.raises(ScriptInputError, match="중복"):
        load_community_topic_briefs(run_directory, (1, 1))
    with pytest.raises(ScriptInputError, match="존재하지 않는"):
        load_community_topic_briefs(run_directory, (99,))
