from __future__ import annotations

import json
import os
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.scripting import CommunityTopicAdapter, ScriptInputError


class GuiInputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CandidateChoice:
    rank: int
    post_id: str
    title: str
    url: str
    summary: str
    reason: str
    hook: str
    fun_score: int
    twist_score: int
    clarity_score: int
    shorts_fit_score: int
    total_score: int
    risks: tuple[str, ...]
    risk_level: str
    review_notes: str


@dataclass(frozen=True, slots=True)
class CandidateReport:
    report_path: Path
    run_directory: Path
    run_id: str
    started_at: datetime
    candidates: tuple[CandidateChoice, ...]

    @property
    def display_name(self) -> str:
        stamp = self.started_at.strftime("%Y-%m-%d %H:%M")
        return f"{stamp} · 후보 {len(self.candidates)}개 · {self.run_directory.name}"


def parse_gallery_input(value: str, selected_type: str) -> tuple[str, str]:
    raw = value.strip()
    if not raw:
        raise GuiInputError("갤러리 URL 또는 ID를 입력하세요.")
    if "://" not in raw:
        if selected_type not in {"major", "minor"}:
            raise GuiInputError("갤러리 유형은 major 또는 minor여야 합니다.")
        return raw, selected_type

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.casefold() != "gall.dcinside.com":
        raise GuiInputError("DCInside 갤러리 URL만 사용할 수 있습니다.")
    if parsed.path.startswith("/mini/"):
        raise GuiInputError("미니 갤러리는 현재 지원하지 않습니다.")
    if parsed.path.startswith("/mgallery/board/"):
        gallery_type = "minor"
    elif parsed.path.startswith("/board/"):
        gallery_type = "major"
    else:
        raise GuiInputError("정식 또는 마이너 갤러리 URL 형식을 확인하세요.")
    gallery_ids = parse_qs(parsed.query).get("id", [])
    if not gallery_ids or not gallery_ids[0].strip():
        raise GuiInputError("갤러리 URL에 id 값이 없습니다.")
    return gallery_ids[0].strip(), gallery_type


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GuiInputError(f"{label}을(를) 읽을 수 없습니다: {exc}") from exc
    if not isinstance(value, dict):
        raise GuiInputError(f"{label}의 최상위 값은 객체여야 합니다.")
    return value


def _candidate_choice(value: dict[str, Any]) -> CandidateChoice:
    string_fields = ("post_id", "title", "url", "summary", "reason", "hook", "review_notes")
    integer_fields = (
        "rank",
        "fun_score",
        "twist_score",
        "clarity_score",
        "shorts_fit_score",
        "total_score",
    )
    if any(not isinstance(value.get(name), str) for name in string_fields):
        raise GuiInputError("후보 결과에 필수 문자열이 없습니다.")
    if any(
        isinstance(value.get(name), bool) or not isinstance(value.get(name), int)
        for name in integer_fields
    ):
        raise GuiInputError("후보 결과에 유효하지 않은 점수 또는 순위가 있습니다.")
    risks = value.get("risks")
    risk_level = value.get("risk_level")
    if not isinstance(risks, list) or any(not isinstance(item, str) for item in risks):
        raise GuiInputError("후보 위험 목록이 올바르지 않습니다.")
    if risk_level not in {"low", "medium", "high"}:
        raise GuiInputError("후보 위험도가 올바르지 않습니다.")
    return CandidateChoice(
        rank=value["rank"],
        post_id=value["post_id"],
        title=value["title"],
        url=value["url"],
        summary=value["summary"],
        reason=value["reason"],
        hook=value["hook"],
        fun_score=value["fun_score"],
        twist_score=value["twist_score"],
        clarity_score=value["clarity_score"],
        shorts_fit_score=value["shorts_fit_score"],
        total_score=value["total_score"],
        risks=tuple(risks),
        risk_level=risk_level,
        review_notes=value["review_notes"],
    )


def load_candidate_report(report_path: str | Path) -> CandidateReport:
    path = Path(report_path).resolve()
    if not path.is_file() or path.suffix.casefold() != ".html":
        raise GuiInputError(f"HTML 후보 보고서를 찾을 수 없습니다: {report_path}")
    run_directory = path.parent
    candidate_data = _read_object(run_directory / "candidates.json", "후보 결과")
    candidates = candidate_data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise GuiInputError("후보 결과에 선택할 후보가 없습니다.")
    ranks = tuple(value.get("rank") for value in candidates if isinstance(value, dict))
    if len(ranks) != len(candidates):
        raise GuiInputError("후보 결과 배열이 올바르지 않습니다.")
    try:
        run_id, topics = CommunityTopicAdapter(run_directory).load(ranks)
    except ScriptInputError as exc:
        raise GuiInputError(str(exc)) from exc
    if len(topics) != len(candidates):
        raise GuiInputError("후보 결과와 원문 연결 개수가 다릅니다.")

    run_state = _read_object(run_directory / "run.json", "실행 상태")
    try:
        started_at = datetime.fromisoformat(run_state["started_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GuiInputError("실행 상태에 유효한 시작 시각이 없습니다.") from exc
    choices = tuple(
        sorted((_candidate_choice(value) for value in candidates), key=lambda choice: choice.rank)
    )
    return CandidateReport(path, run_directory, run_id, started_at, choices)


def find_recent_reports(
    base_directory: str | Path, *, limit: int = 30
) -> tuple[CandidateReport, ...]:
    base = Path(base_directory).expanduser()
    if not base.is_dir() or limit <= 0:
        return ()
    indexed: list[tuple[datetime, Path]] = []
    for state_path in base.glob("*/*/run.json"):
        try:
            state = _read_object(state_path, "실행 상태")
            if state.get("status") != "success":
                continue
            started_at = datetime.fromisoformat(state["started_at"])
            report_path = state_path.with_name("report.html")
            if not report_path.is_file():
                continue
            indexed.append((started_at, report_path))
        except (GuiInputError, KeyError, TypeError, ValueError):
            continue
    indexed.sort(key=lambda item: item[0], reverse=True)

    reports: list[CandidateReport] = []
    for _, path in indexed:
        try:
            reports.append(load_candidate_report(path))
        except GuiInputError:
            continue
        if len(reports) >= limit:
            break
    return tuple(reports)


def open_local_file(path: str | Path) -> None:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise GuiInputError(f"열 파일을 찾을 수 없습니다: {resolved}")
    try:
        startfile = getattr(os, "startfile", None)
        if startfile is not None:
            startfile(str(resolved))
        elif not webbrowser.open(resolved.as_uri()):
            raise OSError("기본 브라우저를 시작하지 못했습니다.")
    except OSError as exc:
        raise GuiInputError(f"파일을 열 수 없습니다: {exc}") from exc
