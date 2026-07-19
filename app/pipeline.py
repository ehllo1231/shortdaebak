from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.codex_runner import CodexError, CodexRunner
from app.config import AppConfig
from app.crawler import CrawlBlockedError, CrawlError, DcinsideCrawler
from app.filtering import filter_posts
from app.models import KST, HistoryIndex, Post
from app.reporting import build_fallback_candidates, render_report
from app.storage import write_json_atomic, write_text_atomic

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "candidates.schema.json"
PROMPT_PATH = PROJECT_ROOT / "prompts" / "evaluate_candidates.txt"


@dataclass(frozen=True, slots=True)
class PipelineResult:
    exit_code: int
    status: str
    output_directory: Path


def _create_run_directory(base: Path, started_at: datetime) -> tuple[str, Path]:
    date_directory = base / started_at.strftime("%Y-%m-%d")
    stem = started_at.strftime("%H%M%S")
    for suffix in range(100):
        run_id = stem if suffix == 0 else f"{stem}-{suffix:02d}"
        path = date_directory / run_id
        try:
            path.mkdir(parents=True, exist_ok=False)
            return run_id, path
        except FileExistsError:
            continue
    raise OSError(f"실행 폴더를 생성할 수 없습니다: {date_directory}")


def _configure_logger(log_path: Path) -> logging.Logger:
    logger = logging.getLogger(f"dc_shorts.{log_path.parent.name}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def _close_logger(logger: logging.Logger) -> None:
    for handler in logger.handlers[:]:
        handler.flush()
        handler.close()
        logger.removeHandler(handler)


def _load_history(base: Path, days: int, now: datetime, logger: logging.Logger) -> HistoryIndex:
    if days <= 0 or not base.exists():
        return HistoryIndex()
    cutoff = now.date() - timedelta(days=days)
    urls: set[str] = set()
    post_keys: set[str] = set()
    for path in base.glob("*/*/raw_posts.json"):
        try:
            run_date = datetime.strptime(path.parents[1].name, "%Y-%m-%d").date()
            if run_date < cutoff:
                continue
            run_state = json.loads(path.with_name("run.json").read_text(encoding="utf-8"))
            if run_state.get("status") != "success":
                continue
            value = json.loads(path.read_text(encoding="utf-8"))
            for post in value.get("posts", []):
                urls.add(post["url"])
                post_keys.add(HistoryIndex.key(post["gallery_id"], post["id"]))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("이전 실행 결과를 읽지 못했습니다 [%s]: %s", path, exc)
    return HistoryIndex(frozenset(urls), frozenset(post_keys))


def _posts_payload(run_id: str, posts: list[Post] | tuple[Post, ...]) -> dict[str, Any]:
    return {"run_id": run_id, "count": len(posts), "posts": [post.to_dict() for post in posts]}


def run_pipeline(
    config: AppConfig,
    *,
    now: datetime | None = None,
    crawler_factory: Callable[..., Any] = DcinsideCrawler,
    codex_runner_factory: Callable[..., Any] = CodexRunner,
) -> PipelineResult:
    started_at = (now or datetime.now(KST)).astimezone(KST)
    base_directory = config.output.base_directory
    run_id, output_directory = _create_run_directory(base_directory, started_at)
    logger = _configure_logger(output_directory / "run.log")
    stderr_path = output_directory / "codex_stderr.log"
    write_text_atomic(stderr_path, "")
    run_data: dict[str, Any] = {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "finished_at": None,
        "status": "running",
        "collection_count": 0,
        "eligible_count": 0,
        "prefiltered_count": 0,
        "displayed_count": 0,
        "exclusions": {},
        "codex": {
            "enabled": config.codex.enabled,
            "used": False,
            "version": None,
            "error_code": None,
        },
    }
    write_json_atomic(output_directory / "run.json", run_data)
    logger.info("실행 시작: %s", run_id)

    runner: Any | None = None
    codex_preflight_error: CodexError | None = None
    if config.codex.enabled:
        runner = codex_runner_factory(
            config.codex,
            SCHEMA_PATH,
            PROMPT_PATH,
            logger=logger,
        )
        try:
            run_data["codex"]["version"] = runner.preflight()
            logger.info("Codex CLI 사전 점검 완료: %s", run_data["codex"]["version"])
        except CodexError as exc:
            codex_preflight_error = exc
            run_data["codex"]["error_code"] = exc.code
            logger.error("Codex 사전 점검 실패 [%s]: %s", exc.code, exc)

    try:
        crawler = crawler_factory(config.dcinside, logger=logger)
        posts = crawler.collect()
        run_data["collection_count"] = len(posts)
        history = _load_history(
            base_directory, config.dcinside.dedupe_history_days, started_at, logger
        )
        write_json_atomic(output_directory / "raw_posts.json", _posts_payload(run_id, posts))
        logger.info("본문 수집 완료: %d개", len(posts))

        result = filter_posts(
            posts,
            config.dcinside,
            config.prefilter,
            history=history,
            now=started_at,
        )
        selected = list(result.selected)
        run_data["eligible_count"] = result.eligible_count
        run_data["prefiltered_count"] = len(selected)
        run_data["exclusions"] = result.exclusions
        write_json_atomic(
            output_directory / "prefiltered.json",
            {
                **_posts_payload(run_id, selected),
                "eligible_count": result.eligible_count,
                "exclusions": result.exclusions,
            },
        )
        logger.info("규칙 기반 후보 선정: %d개", len(selected))

        codex_error: str | None = None
        candidates: list[dict[str, Any]]
        if len(selected) < config.codex.final_candidate_count:
            status = "insufficient_candidates"
            exit_code = 3
            candidates = build_fallback_candidates(selected)
            logger.warning("Codex 평가 생략: 후보가 %d개로 5개보다 적습니다.", len(selected))
        elif not config.codex.enabled:
            status = "codex_fallback"
            exit_code = 4
            codex_error = "설정에서 Codex 평가가 비활성화되어 있습니다."
            candidates = build_fallback_candidates(selected)
        elif codex_preflight_error is not None:
            status = "codex_fallback"
            exit_code = 4
            codex_error = str(codex_preflight_error)
            candidates = build_fallback_candidates(selected)
        else:
            try:
                evaluation = runner.evaluate(selected, started_at.date().isoformat(), stderr_path)
                write_json_atomic(output_directory / "candidates.json", evaluation)
                candidates = evaluation["candidates"]
                status = "success"
                exit_code = 0
                run_data["codex"]["used"] = True
                logger.info("Codex 평가 완료: 5개 후보")
            except CodexError as exc:
                status = "codex_fallback"
                exit_code = 4
                codex_error = str(exc)
                run_data["codex"]["used"] = True
                run_data["codex"]["error_code"] = exc.code
                candidates = build_fallback_candidates(selected)
                logger.error("Codex 평가 실패 [%s]: %s", exc.code, exc)

        run_data["displayed_count"] = len(candidates)
        render_report(
            output_directory / "report.html",
            run_id=run_id,
            generated_at=started_at,
            status=status,
            candidates=candidates,
            collection_count=len(posts),
            prefiltered_count=len(selected),
            codex_error=codex_error,
        )
    except CrawlBlockedError as exc:
        status = "collection_blocked"
        exit_code = 5
        run_data["error"] = str(exc)
        logger.error("수집 중단: %s", exc)
        write_json_atomic(output_directory / "raw_posts.json", _posts_payload(run_id, []))
        write_json_atomic(output_directory / "prefiltered.json", _posts_payload(run_id, []))
        render_report(
            output_directory / "report.html",
            run_id=run_id,
            generated_at=started_at,
            status=status,
            candidates=[],
            collection_count=0,
            prefiltered_count=0,
            codex_error=str(exc),
        )
    except CrawlError as exc:
        status = "collection_failed"
        exit_code = 5
        run_data["error"] = str(exc)
        logger.error("수집 실패: %s", exc)
        write_json_atomic(output_directory / "raw_posts.json", _posts_payload(run_id, []))
        write_json_atomic(output_directory / "prefiltered.json", _posts_payload(run_id, []))
        render_report(
            output_directory / "report.html",
            run_id=run_id,
            generated_at=started_at,
            status=status,
            candidates=[],
            collection_count=0,
            prefiltered_count=0,
            codex_error=str(exc),
        )
    except Exception as exc:
        status = "internal_error"
        exit_code = 6
        run_data["error"] = f"{type(exc).__name__}: {exc}"
        logger.exception("예상하지 못한 오류")
        raw_path = output_directory / "raw_posts.json"
        prefiltered_path = output_directory / "prefiltered.json"
        if not raw_path.exists():
            write_json_atomic(raw_path, _posts_payload(run_id, []))
        if not prefiltered_path.exists():
            write_json_atomic(prefiltered_path, _posts_payload(run_id, []))
        render_report(
            output_directory / "report.html",
            run_id=run_id,
            generated_at=started_at,
            status=status,
            candidates=[],
            collection_count=run_data["collection_count"],
            prefiltered_count=run_data["prefiltered_count"],
            codex_error="예상하지 못한 내부 오류가 발생했습니다. run.log를 확인하세요.",
        )
    finally:
        finished_at = datetime.now(KST)
        run_data["status"] = status
        run_data["finished_at"] = finished_at.isoformat()
        write_json_atomic(output_directory / "run.json", run_data)
        logger.info("실행 종료: %s (상태=%s)", run_id, status)
        _close_logger(logger)
    return PipelineResult(exit_code, status, output_directory)
