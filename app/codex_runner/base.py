from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.config import CodexConfig
from app.storage import write_text_atomic

ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]
WhichRunner = Callable[[str], str | None]
_UNSUPPORTED_OUTPUT_SCHEMA_KEYWORDS = frozenset({"uniqueItems"})
_SCHEMA_MAP_KEYWORDS = frozenset(
    {"$defs", "definitions", "dependentSchemas", "patternProperties", "properties"}
)
_SCHEMA_SINGLE_KEYWORDS = frozenset(
    {
        "additionalProperties",
        "contains",
        "contentSchema",
        "else",
        "if",
        "items",
        "not",
        "propertyNames",
        "then",
        "unevaluatedProperties",
    }
)
_SCHEMA_LIST_KEYWORDS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})


class CodexError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class StructuredCodexRunner:
    """Shared non-interactive Codex CLI execution for structured JSON tasks."""

    def __init__(
        self,
        config: CodexConfig,
        schema_path: Path,
        prompt_path: Path,
        *,
        operation_name: str,
        result_filename: str,
        logger: logging.Logger | None = None,
        process_runner: ProcessRunner = subprocess.run,
        which: WhichRunner = shutil.which,
    ) -> None:
        self.config = config
        self.schema_path = schema_path.resolve()
        self.prompt_path = prompt_path.resolve()
        self.operation_name = operation_name
        self.result_filename = result_filename
        self.logger = logger or logging.getLogger(__name__)
        self.process_runner = process_runner
        self.which = which
        self.executable: str | None = None

    def _run_process(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
        environment = os.environ.copy()
        for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"):
            environment.pop(name, None)
        kwargs.setdefault("env", environment)
        return self.process_runner(command, **kwargs)

    def _resolve_executable(self) -> str:
        resolved = self.which(self.config.executable)
        if resolved is None:
            raise CodexError(
                "Codex CLI를 찾을 수 없습니다. "
                "`npm install -g @openai/codex`로 설치한 뒤 다시 실행하세요.",
                code="cli_missing",
            )
        self.executable = resolved
        return resolved

    def preflight(self) -> str:
        executable = self._resolve_executable()
        try:
            version_result = self._run_process(
                [executable, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise CodexError(f"Codex CLI를 실행할 수 없습니다: {exc}", code="cli_unusable") from exc
        if version_result.returncode != 0:
            raise CodexError("Codex CLI 버전 확인이 실패했습니다.", code="cli_unusable")

        try:
            help_result = self._run_process(
                [executable, "exec", "--help"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise CodexError(
                f"Codex CLI 옵션을 확인할 수 없습니다: {exc}", code="cli_unusable"
            ) from exc
        required_options = {
            "--sandbox",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--output-schema",
            "--output-last-message",
        }
        missing_options = sorted(required_options - set(help_result.stdout.split()))
        if help_result.returncode != 0 or missing_options:
            missing = ", ".join(missing_options) if missing_options else "exec --help"
            raise CodexError(
                f"현재 Codex CLI가 필요한 옵션을 지원하지 않습니다({missing}). "
                "`codex update`로 업데이트하세요.",
                code="cli_too_old",
            )

        try:
            login_result = self._run_process(
                [executable, "login", "status"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise CodexError(
                f"Codex 로그인 상태를 확인할 수 없습니다: {exc}", code="login_check_failed"
            ) from exc
        login_output = f"{login_result.stdout}\n{login_result.stderr}".strip()
        lowered = login_output.casefold()
        if login_result.returncode != 0 or "not logged in" in lowered or "로그인되지" in lowered:
            raise CodexError(
                "Codex CLI에 로그인되어 있지 않습니다. "
                "`codex login`을 실행해 ChatGPT로 로그인하세요.",
                code="login_required",
            )
        if "api key" in lowered or "api-key" in lowered:
            raise CodexError(
                "Codex CLI가 API 키 방식으로 로그인되어 있습니다. "
                "이 프로젝트는 ChatGPT 로그인만 허용합니다. "
                "`codex logout` 후 `codex login`을 실행하세요.",
                code="api_key_auth_rejected",
            )
        if "chatgpt" not in lowered:
            raise CodexError(
                f"Codex 인증 방식을 ChatGPT로 확인하지 못했습니다: {login_output[:200]}",
                code="unknown_auth_method",
            )
        return version_result.stdout.strip()

    def build_command(self, output_path: Path, *, schema_path: Path | None = None) -> list[str]:
        executable = self.executable or self._resolve_executable()
        command = [
            executable,
            "--ask-for-approval",
            "never",
            "exec",
            "--sandbox",
            self.config.sandbox,
            "--skip-git-repo-check",
            "--ignore-user-config",
            "--ignore-rules",
            "--output-schema",
            str(schema_path or self.schema_path),
            "--output-last-message",
            str(output_path),
        ]
        if self.config.ephemeral:
            command.append("--ephemeral")
        command.append("-")
        return command

    @staticmethod
    def _classify_failure(output: str) -> str:
        lowered = output.casefold()
        if "invalid_json_schema" in lowered or "invalid schema for response_format" in lowered:
            return "output_schema_rejected"
        if any(
            marker in lowered
            for marker in ("usage limit", "quota", "rate limit", "too many requests")
        ):
            return "usage_limit"
        if any(
            marker in lowered
            for marker in ("not logged in", "unauthorized", "authentication", "login")
        ):
            return "login_required"
        if any(marker in lowered for marker in ("utf-8", "unicode", "codec", "encoding")):
            return "encoding_error"
        return "nonzero_exit"

    @staticmethod
    def _prepare_output_schema(value: Any) -> Any:
        """Copy a JSON Schema while removing keywords unsupported by Structured Outputs."""

        if not isinstance(value, dict):
            return deepcopy(value)
        prepared: dict[str, Any] = {}
        for key, child in value.items():
            if key in _UNSUPPORTED_OUTPUT_SCHEMA_KEYWORDS:
                continue
            if key in _SCHEMA_MAP_KEYWORDS and isinstance(child, dict):
                prepared[key] = {
                    name: StructuredCodexRunner._prepare_output_schema(schema)
                    for name, schema in child.items()
                }
            elif key in _SCHEMA_SINGLE_KEYWORDS and isinstance(child, dict):
                prepared[key] = StructuredCodexRunner._prepare_output_schema(child)
            elif key in _SCHEMA_LIST_KEYWORDS and isinstance(child, list):
                prepared[key] = [
                    StructuredCodexRunner._prepare_output_schema(schema) for schema in child
                ]
            else:
                prepared[key] = deepcopy(child)
        return prepared

    def execute_structured(
        self,
        stdin: str,
        schema: dict[str, Any],
        stderr_path: Path,
    ) -> Any:
        with tempfile.TemporaryDirectory(prefix="dc-shorts-codex-") as temporary_directory:
            temporary_path = Path(temporary_directory)
            result_path = temporary_path / self.result_filename
            runtime_schema_path = temporary_path / self.schema_path.name
            output_schema = self._prepare_output_schema(schema)
            write_text_atomic(
                runtime_schema_path,
                json.dumps(output_schema, ensure_ascii=False, indent=2) + "\n",
            )
            command = self.build_command(result_path, schema_path=runtime_schema_path)
            try:
                result = self._run_process(
                    command,
                    input=stdin,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=temporary_path,
                    timeout=self.config.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
                write_text_atomic(stderr_path, stderr)
                raise CodexError(
                    f"{self.operation_name} 작업이 {self.config.timeout_seconds:g}초 안에 "
                    "완료되지 않았습니다.",
                    code="timeout",
                ) from exc
            except OSError as exc:
                raise CodexError(
                    f"Codex 프로세스를 시작할 수 없습니다: {exc}",
                    code="process_start_failed",
                ) from exc

            write_text_atomic(stderr_path, result.stderr)
            if result.returncode != 0:
                combined = f"{result.stdout}\n{result.stderr}"
                code = self._classify_failure(combined)
                raise CodexError(
                    f"{self.operation_name} 작업이 실패했습니다(종료 코드 {result.returncode}). "
                    "세부 내용은 codex_stderr.log를 확인하세요.",
                    code=code,
                )
            if not result_path.is_file():
                raise CodexError("Codex가 결과 JSON을 생성하지 않았습니다.", code="json_missing")
            try:
                return json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise CodexError(
                    f"Codex JSON을 읽을 수 없습니다: {exc}", code="json_invalid"
                ) from exc
