from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from app.codex_runner.base import (
    CodexError,
    ProcessRunner,
    StructuredCodexRunner,
    WhichRunner,
)
from app.config import CodexConfig
from app.scripting.models import (
    SCRIPT_PACKAGE_SCHEMA_VERSION,
    SCRIPT_STYLE_ID,
    TARGET_DURATION_MAX_SECONDS,
    TARGET_DURATION_MIN_SECONDS,
    TopicBrief,
)

EXPECTED_ROLES = ("hook", "setup", "development", "payoff", "closing")


class ScriptGenerator(StructuredCodexRunner):
    def __init__(
        self,
        config: CodexConfig,
        schema_path: Path,
        prompt_path: Path,
        *,
        logger: logging.Logger | None = None,
        process_runner: ProcessRunner = subprocess.run,
        which: WhichRunner = shutil.which,
    ) -> None:
        super().__init__(
            config,
            schema_path,
            prompt_path,
            operation_name="Codex 대본 생성",
            result_filename="script_packages.json",
            logger=logger,
            process_runner=process_runner,
            which=which,
        )
        self._schema: dict[str, Any] | None = None

    def _load_schema(self, topic_count: int) -> dict[str, Any]:
        if self._schema is not None:
            schema = json.loads(json.dumps(self._schema))
        else:
            try:
                schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
                Draft202012Validator.check_schema(schema)
            except (OSError, json.JSONDecodeError, SchemaError) as exc:
                raise CodexError(
                    f"대본 JSON Schema를 읽을 수 없습니다: {exc}", code="schema_invalid"
                ) from exc
            self._schema = schema
            schema = json.loads(json.dumps(schema))
        scripts_schema = schema["properties"]["scripts"]
        scripts_schema["minItems"] = topic_count
        scripts_schema["maxItems"] = topic_count
        return schema

    def build_stdin(self, topics: tuple[TopicBrief, ...], brief_set_id: str) -> str:
        try:
            instructions = self.prompt_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise CodexError(
                f"대본 프롬프트를 읽을 수 없습니다: {exc}", code="prompt_missing"
            ) from exc
        data = {
            "brief_set_id": brief_set_id,
            "topic_count": len(topics),
            "target_duration_seconds": {
                "minimum": TARGET_DURATION_MIN_SECONDS,
                "maximum": TARGET_DURATION_MAX_SECONDS,
            },
            "topics": [topic.to_dict() for topic in topics],
        }
        serialized = json.dumps(data, ensure_ascii=False, indent=2)
        serialized = serialized.replace("<", "\\u003c").replace(">", "\\u003e")
        return (
            f"{instructions}\n\n<UNTRUSTED_TOPIC_BRIEFS>\n{serialized}\n</UNTRUSTED_TOPIC_BRIEFS>\n"
        )

    def validate_result(
        self,
        value: Any,
        topics: tuple[TopicBrief, ...],
        brief_set_id: str,
    ) -> dict[str, Any]:
        schema = self._load_schema(len(topics))
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            first = errors[0]
            path = ".".join(str(part) for part in first.absolute_path) or "<root>"
            raise CodexError(
                f"대본 JSON Schema 검증 실패 [{path}]: {first.message}",
                code="schema_validation_failed",
            )
        if value["schema_version"] != SCRIPT_PACKAGE_SCHEMA_VERSION:
            raise CodexError("대본 계약 버전이 요청과 다릅니다.", code="result_integrity_failed")
        if value["brief_set_id"] != brief_set_id:
            raise CodexError("대본 결과의 입력 묶음 ID가 다릅니다.", code="result_integrity_failed")

        topics_by_id = {topic.topic_id: topic for topic in topics}
        if len(topics_by_id) != len(topics):
            raise CodexError("중복된 TopicBrief ID가 있습니다.", code="result_integrity_failed")
        scripts_by_id: dict[str, dict[str, Any]] = {}
        for script in value["scripts"]:
            topic_id = script["topic_id"]
            topic = topics_by_id.get(topic_id)
            if topic is None or topic_id in scripts_by_id:
                raise CodexError(
                    "대본 결과에 알 수 없거나 중복된 주제가 있습니다.",
                    code="result_integrity_failed",
                )
            expected_references = [reference.to_dict() for reference in topic.source_references]
            copied_fields = {
                "origin": topic.origin,
                "topic_title": topic.title,
                "source_references": expected_references,
                "risk_level": topic.risk_level,
                "risk_notes": list(topic.risk_notes),
                "uncertainties": list(topic.uncertainties),
            }
            if any(script[name] != expected for name, expected in copied_fields.items()):
                raise CodexError(
                    "대본 결과가 TopicBrief의 출처 또는 위험 정보를 변경했습니다.",
                    code="result_integrity_failed",
                )
            if script["style_id"] != SCRIPT_STYLE_ID:
                raise CodexError(
                    "대본 스타일 ID가 요청과 다릅니다.", code="result_integrity_failed"
                )

            segments = script["segments"]
            roles = tuple(segment["role"] for segment in segments)
            orders = tuple(segment["order"] for segment in segments)
            if roles != EXPECTED_ROLES or orders != (1, 2, 3, 4, 5):
                raise CodexError(
                    "대본 구간 순서가 hook부터 closing까지 이어지지 않습니다.",
                    code="result_integrity_failed",
                )
            duration = sum(segment["estimated_seconds"] for segment in segments)
            if duration != script["estimated_duration_seconds"]:
                raise CodexError(
                    "대본 구간 시간 합계가 전체 예상 시간과 다릅니다.",
                    code="result_integrity_failed",
                )
            valid_reference_ids = {reference.id for reference in topic.source_references}
            if any(
                not set(segment["source_reference_ids"]).issubset(valid_reference_ids)
                for segment in segments
            ):
                raise CodexError(
                    "대본 구간이 TopicBrief에 없는 출처를 참조했습니다.",
                    code="result_integrity_failed",
                )
            if not segments[-1]["narration"].rstrip().endswith("?"):
                raise CodexError(
                    "대본의 마무리는 시청자 질문으로 끝나야 합니다.",
                    code="result_integrity_failed",
                )
            required_warnings = {*topic.risk_notes, *topic.uncertainties}
            if not required_warnings.issubset(set(script["review_warnings"])):
                raise CodexError(
                    "대본 결과에 원본 위험 또는 불확실성 경고가 누락됐습니다.",
                    code="result_integrity_failed",
                )
            scripts_by_id[topic_id] = script

        value["scripts"] = [scripts_by_id[topic.topic_id] for topic in topics]
        return value

    def generate(
        self,
        topics: tuple[TopicBrief, ...],
        brief_set_id: str,
        stderr_path: Path,
    ) -> dict[str, Any]:
        if not topics:
            raise CodexError("대본을 만들 TopicBrief가 없습니다.", code="insufficient_topics")
        schema = self._load_schema(len(topics))
        stdin = self.build_stdin(topics, brief_set_id)
        value = self.execute_structured(stdin, schema, stderr_path)
        return self.validate_result(value, topics, brief_set_id)
