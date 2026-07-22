from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.storage import write_text_atomic

WEIGHT_NAMES = (
    "recency",
    "recommendations",
    "comments",
    "views",
    "body_length",
    "engagement",
)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GalleryConfig:
    id: str
    name: str
    type: str


@dataclass(frozen=True, slots=True)
class DcinsideConfig:
    galleries: tuple[GalleryConfig, ...]
    pages_per_gallery: int
    request_interval_seconds: float
    timeout_seconds: float
    retries: int
    min_body_length: int
    excluded_keywords: tuple[str, ...]
    dedupe_history_days: int
    user_agent: str


@dataclass(frozen=True, slots=True)
class PrefilterConfig:
    candidate_count: int
    weights: dict[str, float]


@dataclass(frozen=True, slots=True)
class CodexConfig:
    enabled: bool
    executable: str
    timeout_seconds: float
    final_candidate_count: int
    sandbox: str
    ephemeral: bool


@dataclass(frozen=True, slots=True)
class OutputConfig:
    base_directory: Path


@dataclass(frozen=True, slots=True)
class AppConfig:
    dcinside: DcinsideConfig
    prefilter: PrefilterConfig
    codex: CodexConfig
    output: OutputConfig


def _mapping(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{location}은(는) 객체여야 합니다.")
    return value


def _reject_unknown(data: dict[str, Any], allowed: set[str], location: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"{location}에 알 수 없는 설정이 있습니다: {', '.join(unknown)}")


def _positive_number(value: Any, location: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{location}은(는) 숫자여야 합니다.")
    if not math.isfinite(value) or (value < 0 if allow_zero else value <= 0):
        qualifier = "0 이상" if allow_zero else "0보다 큰"
        raise ConfigError(f"{location}은(는) {qualifier} 값이어야 합니다.")
    return float(value)


def _positive_int(value: Any, location: str, *, allow_zero: bool = False) -> int:
    number = _positive_number(value, location, allow_zero=allow_zero)
    if not number.is_integer():
        raise ConfigError(f"{location}은(는) 정수여야 합니다.")
    return int(number)


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"설정 파일을 찾을 수 없습니다: {config_path}")

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"설정 파일을 읽을 수 없습니다: {exc}") from exc

    return parse_config(raw)


def parse_config(raw: Any) -> AppConfig:
    """Validate an in-memory YAML-compatible value as application configuration."""

    top = _mapping(raw, "config")
    _reject_unknown(top, {"dcinside", "prefilter", "codex", "output"}, "config")

    dc = _mapping(top.get("dcinside"), "dcinside")
    _reject_unknown(
        dc,
        {
            "galleries",
            "pages_per_gallery",
            "request_interval_seconds",
            "timeout_seconds",
            "retries",
            "min_body_length",
            "excluded_keywords",
            "dedupe_history_days",
            "user_agent",
        },
        "dcinside",
    )
    raw_galleries = dc.get("galleries")
    if not isinstance(raw_galleries, list) or not raw_galleries:
        raise ConfigError("dcinside.galleries에 하나 이상의 갤러리를 지정하세요.")
    galleries: list[GalleryConfig] = []
    seen_gallery_ids: set[tuple[str, str]] = set()
    for index, item in enumerate(raw_galleries):
        location = f"dcinside.galleries[{index}]"
        gallery = _mapping(item, location)
        _reject_unknown(gallery, {"id", "name", "type"}, location)
        gallery_id = gallery.get("id")
        name = gallery.get("name")
        gallery_type = gallery.get("type")
        if not isinstance(gallery_id, str) or not gallery_id.strip():
            raise ConfigError(f"{location}.id를 입력하세요.")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{location}.name을 입력하세요.")
        if gallery_type not in {"major", "minor"}:
            raise ConfigError(f"{location}.type은 major 또는 minor여야 합니다.")
        key = (gallery_type, gallery_id.strip())
        if key in seen_gallery_ids:
            raise ConfigError(f"중복된 갤러리입니다: {gallery_id}")
        seen_gallery_ids.add(key)
        galleries.append(GalleryConfig(gallery_id.strip(), name.strip(), gallery_type))

    keywords = dc.get("excluded_keywords", [])
    if not isinstance(keywords, list) or any(not isinstance(item, str) for item in keywords):
        raise ConfigError("dcinside.excluded_keywords는 문자열 배열이어야 합니다.")
    user_agent = dc.get(
        "user_agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36 DCShortsCollector/0.1",
    )
    if not isinstance(user_agent, str) or not user_agent.strip():
        raise ConfigError("dcinside.user_agent는 빈 문자열이면 안 됩니다.")
    dc_config = DcinsideConfig(
        galleries=tuple(galleries),
        pages_per_gallery=_positive_int(dc.get("pages_per_gallery", 2), "pages_per_gallery"),
        request_interval_seconds=_positive_number(
            dc.get("request_interval_seconds", 1.5),
            "request_interval_seconds",
            allow_zero=True,
        ),
        timeout_seconds=_positive_number(dc.get("timeout_seconds", 10), "timeout_seconds"),
        retries=_positive_int(dc.get("retries", 2), "retries", allow_zero=True),
        min_body_length=_positive_int(dc.get("min_body_length", 100), "min_body_length"),
        excluded_keywords=tuple(item.strip() for item in keywords if item.strip()),
        dedupe_history_days=_positive_int(
            dc.get("dedupe_history_days", 30), "dedupe_history_days", allow_zero=True
        ),
        user_agent=user_agent.strip(),
    )
    if dc_config.pages_per_gallery > 20:
        raise ConfigError("pages_per_gallery는 과도한 요청을 막기 위해 20 이하여야 합니다.")
    if dc_config.retries > 5:
        raise ConfigError("retries는 5 이하여야 합니다.")

    prefilter = _mapping(top.get("prefilter"), "prefilter")
    _reject_unknown(prefilter, {"candidate_count", "weights"}, "prefilter")
    raw_weights = _mapping(prefilter.get("weights"), "prefilter.weights")
    _reject_unknown(raw_weights, set(WEIGHT_NAMES), "prefilter.weights")
    missing_weights = sorted(set(WEIGHT_NAMES) - set(raw_weights))
    if missing_weights:
        raise ConfigError(f"누락된 필터 가중치: {', '.join(missing_weights)}")
    weights = {
        name: _positive_number(raw_weights[name], f"prefilter.weights.{name}", allow_zero=True)
        for name in WEIGHT_NAMES
    }
    if sum(weights.values()) <= 0:
        raise ConfigError("필터 가중치 합은 0보다 커야 합니다.")
    prefilter_config = PrefilterConfig(
        candidate_count=_positive_int(
            prefilter.get("candidate_count", 20), "prefilter.candidate_count"
        ),
        weights=weights,
    )
    if prefilter_config.candidate_count < 5:
        raise ConfigError("prefilter.candidate_count는 최소 5여야 합니다.")
    if prefilter_config.candidate_count > 100:
        raise ConfigError("prefilter.candidate_count는 최대 100이어야 합니다.")

    codex = _mapping(top.get("codex"), "codex")
    _reject_unknown(
        codex,
        {
            "enabled",
            "executable",
            "timeout_seconds",
            "final_candidate_count",
            "sandbox",
            "ephemeral",
        },
        "codex",
    )
    enabled = codex.get("enabled", True)
    ephemeral = codex.get("ephemeral", True)
    if not isinstance(enabled, bool) or not isinstance(ephemeral, bool):
        raise ConfigError("codex.enabled와 codex.ephemeral은 boolean이어야 합니다.")
    if not ephemeral:
        raise ConfigError("Codex 평가는 ephemeral 모드만 허용합니다.")
    executable = codex.get("executable", "codex")
    if not isinstance(executable, str) or not executable.strip():
        raise ConfigError("codex.executable을 입력하세요.")
    final_count = _positive_int(
        codex.get("final_candidate_count", 5), "codex.final_candidate_count"
    )
    if final_count > prefilter_config.candidate_count:
        raise ConfigError(
            "codex.final_candidate_count는 prefilter.candidate_count 이하여야 합니다."
        )
    sandbox = codex.get("sandbox", "read-only")
    if sandbox != "read-only":
        raise ConfigError("Codex 평가용 sandbox는 read-only만 허용합니다.")
    codex_config = CodexConfig(
        enabled=enabled,
        executable=executable.strip(),
        timeout_seconds=_positive_number(
            codex.get("timeout_seconds", 300), "codex.timeout_seconds"
        ),
        final_candidate_count=final_count,
        sandbox=sandbox,
        ephemeral=ephemeral,
    )

    output = _mapping(top.get("output"), "output")
    _reject_unknown(output, {"base_directory"}, "output")
    base_directory = output.get("base_directory", "output")
    if not isinstance(base_directory, str) or not base_directory.strip():
        raise ConfigError("output.base_directory를 입력하세요.")

    return AppConfig(
        dcinside=dc_config,
        prefilter=prefilter_config,
        codex=codex_config,
        output=OutputConfig(Path(base_directory).expanduser()),
    )


def config_to_mapping(config: AppConfig) -> dict[str, Any]:
    return {
        "dcinside": {
            "galleries": [
                {"id": gallery.id, "name": gallery.name, "type": gallery.type}
                for gallery in config.dcinside.galleries
            ],
            "pages_per_gallery": config.dcinside.pages_per_gallery,
            "request_interval_seconds": config.dcinside.request_interval_seconds,
            "timeout_seconds": config.dcinside.timeout_seconds,
            "retries": config.dcinside.retries,
            "min_body_length": config.dcinside.min_body_length,
            "excluded_keywords": list(config.dcinside.excluded_keywords),
            "dedupe_history_days": config.dcinside.dedupe_history_days,
            "user_agent": config.dcinside.user_agent,
        },
        "prefilter": {
            "candidate_count": config.prefilter.candidate_count,
            "weights": dict(config.prefilter.weights),
        },
        "codex": {
            "enabled": config.codex.enabled,
            "executable": config.codex.executable,
            "timeout_seconds": config.codex.timeout_seconds,
            "final_candidate_count": config.codex.final_candidate_count,
            "sandbox": config.codex.sandbox,
            "ephemeral": config.codex.ephemeral,
        },
        "output": {"base_directory": str(config.output.base_directory)},
    }


def save_config(path: str | Path, config: AppConfig) -> None:
    content = yaml.safe_dump(
        config_to_mapping(config),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    write_text_atomic(Path(path), content)
