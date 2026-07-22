from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from app.codex_runner import CodexError
from app.config import AppConfig
from app.events import CallbackLogHandler, EventCallback
from app.models import KST
from app.progress import ProgressStreamHandler
from app.scripting.adapters import ScriptInputError, load_community_topic_briefs
from app.scripting.generator import ScriptGenerator
from app.scripting.models import topic_briefs_payload
from app.scripting.reporting import render_script_report
from app.storage import write_json_atomic, write_text_atomic

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TOPIC_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "topic_briefs.schema.json"
SCRIPT_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "script_packages.schema.json"
SCRIPT_PROMPT_PATH = PROJECT_ROOT / "prompts" / "generate_scripts.txt"


@dataclass(frozen=True, slots=True)
class ScriptPipelineResult:
    exit_code: int
    status: str
    output_directory: Path


def _create_script_run_directory(source_run_directory: Path, started_at: datetime) -> Path:
    base = source_run_directory / "scripts"
    stem = started_at.strftime("%H%M%S")
    for suffix in range(100):
        name = stem if suffix == 0 else f"{stem}-{suffix:02d}"
        path = base / name
        try:
            path.mkdir(parents=True, exist_ok=False)
            return path
        except FileExistsError:
            continue
    raise OSError(f"대본 실행 폴더를 생성할 수 없습니다: {base}")


def _configure_logger(
    log_path: Path, event_callback: EventCallback | None = None
) -> logging.Logger:
    logger = logging.getLogger(f"dc_shorts.script.{log_path.parent.name}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = ProgressStreamHandler(sys.stderr)
    stream_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    if event_callback is not None:
        callback_handler = CallbackLogHandler(event_callback)
        callback_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(callback_handler)
    return logger


def _close_logger(logger: logging.Logger) -> None:
    for handler in logger.handlers[:]:
        handler.flush()
        handler.close()
        logger.removeHandler(handler)


def _validate_topic_payload(payload: dict[str, Any]) -> None:
    try:
        schema = json.loads(TOPIC_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    except (OSError, ValueError, SchemaError) as exc:
        raise ScriptInputError(f"TopicBrief JSON Schema를 읽을 수 없습니다: {exc}") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise ScriptInputError(f"TopicBrief 검증 실패 [{path}]: {first.message}")
    if payload["count"] != len(payload["topics"]):
        raise ScriptInputError("TopicBrief 개수 필드가 실제 배열 길이와 다릅니다.")


def run_script_pipeline(
    config: AppConfig,
    source_run_directory: Path,
    ranks: tuple[int, ...],
    *,
    now: datetime | None = None,
    generator_factory: Callable[..., Any] = ScriptGenerator,
    event_callback: EventCallback | None = None,
) -> ScriptPipelineResult:
    source_run_id, topics = load_community_topic_briefs(source_run_directory, ranks)
    brief_set_id = source_run_id
    topic_payload = topic_briefs_payload(brief_set_id, topics)
    _validate_topic_payload(topic_payload)

    started_at = (now or datetime.now(KST)).astimezone(KST)
    output_directory = _create_script_run_directory(source_run_directory.resolve(), started_at)
    logger = _configure_logger(output_directory / "script_run.log", event_callback)
    stderr_path = output_directory / "codex_stderr.log"
    write_text_atomic(stderr_path, "")
    run_data: dict[str, Any] = {
        "source_run_id": source_run_id,
        "script_run_id": output_directory.name,
        "started_at": started_at.isoformat(),
        "finished_at": None,
        "status": "running",
        "requested_ranks": list(sorted(ranks)),
        "topic_count": len(topics),
        "script_count": 0,
        "codex": {
            "enabled": config.codex.enabled,
            "used": False,
            "version": None,
            "error_code": None,
        },
    }
    write_json_atomic(output_directory / "topic_briefs.json", topic_payload)
    write_json_atomic(output_directory / "script_run.json", run_data)
    logger.info("대본 실행 시작: 원본=%s, 후보=%s", source_run_id, ",".join(map(str, ranks)))

    packages: dict[str, Any] | None = None
    codex_error: str | None = None
    try:
        if not config.codex.enabled:
            raise CodexError(
                "설정에서 Codex가 비활성화되어 대본을 생성할 수 없습니다.",
                code="codex_disabled",
            )
        generator = generator_factory(
            config.codex,
            SCRIPT_SCHEMA_PATH,
            SCRIPT_PROMPT_PATH,
            logger=logger,
        )
        run_data["codex"]["version"] = generator.preflight()
        logger.info("Codex CLI 사전 점검 완료: %s", run_data["codex"]["version"])
        run_data["codex"]["used"] = True
        packages = generator.generate(topics, brief_set_id, stderr_path)
        write_json_atomic(output_directory / "script_packages.json", packages)
        run_data["script_count"] = len(packages["scripts"])
        status = "success"
        exit_code = 0
        logger.info("대본 생성 완료: %d개", run_data["script_count"])
    except CodexError as exc:
        status = "codex_failed"
        exit_code = 4
        codex_error = str(exc)
        run_data["codex"]["error_code"] = exc.code
        logger.error("대본 생성 실패 [%s]: %s", exc.code, exc)
    except Exception as exc:
        status = "internal_error"
        exit_code = 6
        codex_error = "예상하지 못한 내부 오류가 발생했습니다. script_run.log를 확인하세요."
        run_data["error"] = f"{type(exc).__name__}: {exc}"
        logger.exception("예상하지 못한 대본 생성 오류")
    finally:
        render_script_report(
            output_directory / "script_report.html",
            brief_set_id=brief_set_id,
            generated_at=started_at,
            status=status,
            topics=topics,
            packages=packages,
            codex_error=codex_error,
            candidate_report_href="../../report.html",
        )
        run_data["status"] = status
        run_data["finished_at"] = datetime.now(KST).isoformat()
        write_json_atomic(output_directory / "script_run.json", run_data)
        logger.info("대본 실행 종료: 상태=%s", status)
        _close_logger(logger)
    return ScriptPipelineResult(exit_code, status, output_directory)
