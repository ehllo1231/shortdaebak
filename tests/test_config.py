from __future__ import annotations

from pathlib import Path

import pytest

from app.config import ConfigError, load_config


def test_load_example_config(tmp_path: Path) -> None:
    example = Path("config.example.yaml").read_text(encoding="utf-8")
    path = tmp_path / "config.yaml"
    path.write_text(example, encoding="utf-8")

    config = load_config(path)

    assert config.dcinside.galleries[0].type == "major"
    assert config.codex.final_candidate_count == 5
    assert config.output.base_directory == Path("output")


def test_reject_unknown_setting(tmp_path: Path) -> None:
    example = Path("config.example.yaml").read_text(encoding="utf-8")
    path = tmp_path / "config.yaml"
    path.write_text(
        example.replace("  pages_per_gallery: 2", "  pages_per_gallery: 2\n  mystery: true"),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="mystery"):
        load_config(path)


def test_accept_custom_final_candidate_count(tmp_path: Path) -> None:
    example = Path("config.example.yaml").read_text(encoding="utf-8")
    path = tmp_path / "config.yaml"
    path.write_text(
        example.replace("final_candidate_count: 5", "final_candidate_count: 3"), encoding="utf-8"
    )

    config = load_config(path)

    assert config.codex.final_candidate_count == 3


def test_reject_final_candidate_count_above_prefilter_count(tmp_path: Path) -> None:
    example = Path("config.example.yaml").read_text(encoding="utf-8")
    path = tmp_path / "config.yaml"
    path.write_text(
        example.replace("final_candidate_count: 5", "final_candidate_count: 21"),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="prefilter.candidate_count"):
        load_config(path)


def test_reject_non_ephemeral_codex(tmp_path: Path) -> None:
    example = Path("config.example.yaml").read_text(encoding="utf-8")
    path = tmp_path / "config.yaml"
    path.write_text(example.replace("ephemeral: true", "ephemeral: false"), encoding="utf-8")

    with pytest.raises(ConfigError, match="ephemeral"):
        load_config(path)
