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
from app.models import Post

MAX_BODY_CHARACTERS = 6_000
FINAL_COUNT_TOKEN = "{{FINAL_CANDIDATE_COUNT}}"


class CodexRunner(StructuredCodexRunner):
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
            operation_name="Codex 평가",
            result_filename="candidates.json",
            logger=logger,
            process_runner=process_runner,
            which=which,
        )
        self._schema: dict[str, Any] | None = None

    def _load_schema(self) -> dict[str, Any]:
        if self._schema is not None:
            return self._schema
        try:
            schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
            candidates_schema = schema["properties"]["candidates"]
            candidates_schema["minItems"] = self.config.final_candidate_count
            candidates_schema["maxItems"] = self.config.final_candidate_count
            candidates_schema["items"]["properties"]["rank"]["maximum"] = (
                self.config.final_candidate_count
            )
            Draft202012Validator.check_schema(schema)
        except (OSError, json.JSONDecodeError, SchemaError, KeyError, TypeError) as exc:
            raise CodexError(
                f"JSON Schema를 읽을 수 없습니다: {exc}", code="schema_invalid"
            ) from exc
        self._schema = schema
        return schema

    def build_stdin(self, posts: list[Post], run_date: str) -> str:
        try:
            instructions = self.prompt_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise CodexError(
                f"평가 프롬프트를 읽을 수 없습니다: {exc}", code="prompt_missing"
            ) from exc
        instructions = instructions.replace(
            FINAL_COUNT_TOKEN, str(self.config.final_candidate_count)
        )
        data = {
            "run_date": run_date,
            "candidate_count": len(posts),
            "final_candidate_count": self.config.final_candidate_count,
            "posts": [],
        }
        for post in posts:
            value = post.to_dict()
            value["original_body_length"] = len(post.body)
            value["body_truncated"] = len(post.body) > MAX_BODY_CHARACTERS
            value["body"] = post.body[:MAX_BODY_CHARACTERS]
            data["posts"].append(value)
        serialized = json.dumps(data, ensure_ascii=False, indent=2)
        serialized = serialized.replace("<", "\\u003c").replace(">", "\\u003e")
        return (
            f"{instructions}\n\n"
            "<UNTRUSTED_COMMUNITY_POSTS>\n"
            f"{serialized}\n"
            "</UNTRUSTED_COMMUNITY_POSTS>\n"
        )

    def validate_result(self, value: Any, posts: list[Post], run_date: str) -> dict[str, Any]:
        schema = self._load_schema()
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            first = errors[0]
            path = ".".join(str(part) for part in first.absolute_path) or "<root>"
            raise CodexError(
                f"Codex JSON Schema 검증 실패 [{path}]: {first.message}",
                code="schema_validation_failed",
            )
        if value["run_date"] != run_date:
            raise CodexError(
                "Codex 결과의 실행 날짜가 요청과 다릅니다.", code="result_integrity_failed"
            )

        source = {post.url: post for post in posts}
        ranks: set[int] = set()
        urls: set[str] = set()
        for candidate in value["candidates"]:
            post_id = candidate["post_id"]
            url = candidate["url"]
            if url not in source or url in urls:
                raise CodexError(
                    "Codex 결과에 없는 게시물이나 중복 게시물이 있습니다.",
                    code="result_integrity_failed",
                )
            original = source[url]
            if post_id != original.id or candidate["title"] != original.title:
                raise CodexError(
                    "Codex 결과가 원문 제목 또는 URL을 변경했습니다.",
                    code="result_integrity_failed",
                )
            if len(candidate["summary"].splitlines()) > 3:
                raise CodexError("Codex 요약이 3줄을 초과했습니다.", code="result_integrity_failed")
            ranks.add(candidate["rank"])
            urls.add(url)
        expected_ranks = set(range(1, self.config.final_candidate_count + 1))
        if ranks != expected_ranks:
            raise CodexError(
                f"Codex 후보 순위가 1~{self.config.final_candidate_count}를 "
                "정확히 포함하지 않습니다.",
                code="result_integrity_failed",
            )
        value["candidates"].sort(key=lambda item: item["rank"])
        return value

    def evaluate(self, posts: list[Post], run_date: str, stderr_path: Path) -> dict[str, Any]:
        if len(posts) < self.config.final_candidate_count:
            raise CodexError(
                f"Codex 평가에 필요한 {self.config.final_candidate_count}개 후보가 없습니다.",
                code="insufficient_candidates",
            )
        schema = self._load_schema()
        stdin = self.build_stdin(posts, run_date)
        value = self.execute_structured(stdin, schema, stderr_path)
        return self.validate_result(value, posts, run_date)
