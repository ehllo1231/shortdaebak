from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models import Post
from app.scripting.models import (
    MAX_SOURCE_MATERIAL_CHARACTERS,
    SourceReference,
    TopicBrief,
    TopicProvenance,
)


class ScriptInputError(ValueError):
    pass


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ScriptInputError(f"{label} 파일을 찾을 수 없습니다: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ScriptInputError(f"{label} 파일을 읽을 수 없습니다: {exc}") from exc
    if not isinstance(value, dict):
        raise ScriptInputError(f"{label} 파일의 최상위 값은 객체여야 합니다.")
    return value


def _validated_ranks(ranks: tuple[int, ...]) -> tuple[int, ...]:
    if not ranks:
        raise ScriptInputError("하나 이상의 후보 순위를 지정하세요.")
    if any(isinstance(rank, bool) or not isinstance(rank, int) or rank <= 0 for rank in ranks):
        raise ScriptInputError("후보 순위는 1 이상의 정수여야 합니다.")
    if len(set(ranks)) != len(ranks):
        raise ScriptInputError("중복된 후보 순위를 지정할 수 없습니다.")
    return tuple(sorted(ranks))


class CommunityTopicAdapter:
    """Convert selected community candidates into source-independent TopicBriefs."""

    def __init__(self, source_run_directory: Path) -> None:
        self.source_run_directory = source_run_directory

    def load(self, ranks: tuple[int, ...]) -> tuple[str, tuple[TopicBrief, ...]]:
        run_directory = self.source_run_directory.resolve()
        if not run_directory.is_dir():
            raise ScriptInputError(
                f"후보 실행 폴더를 찾을 수 없습니다: {self.source_run_directory}"
            )
        selected_ranks = _validated_ranks(ranks)

        run_state = _read_json_object(run_directory / "run.json", "실행 상태")
        if run_state.get("status") != "success":
            raise ScriptInputError("Codex 후보 선정에 성공한 실행만 대본으로 만들 수 있습니다.")
        source_run_id = run_state.get("run_id")
        if not isinstance(source_run_id, str) or not source_run_id:
            raise ScriptInputError("run.json에 유효한 run_id가 없습니다.")
        started_at = run_state.get("started_at")
        if not isinstance(started_at, str) or len(started_at) < 10:
            raise ScriptInputError("run.json에 유효한 started_at이 없습니다.")

        candidate_data = _read_json_object(run_directory / "candidates.json", "후보 결과")
        raw_data = _read_json_object(run_directory / "raw_posts.json", "원문 결과")
        if candidate_data.get("evaluation_status") != "codex":
            raise ScriptInputError("Codex가 평가한 candidates.json만 사용할 수 있습니다.")
        if candidate_data.get("run_date") != started_at[:10]:
            raise ScriptInputError("후보 결과의 실행 날짜가 run.json과 일치하지 않습니다.")
        if raw_data.get("run_id") != source_run_id:
            raise ScriptInputError("원문 결과의 실행 ID가 run.json과 일치하지 않습니다.")

        raw_candidates = candidate_data.get("candidates")
        raw_posts = raw_data.get("posts")
        if not isinstance(raw_candidates, list) or not isinstance(raw_posts, list):
            raise ScriptInputError("후보 또는 원문 배열이 올바르지 않습니다.")

        candidates_by_rank: dict[int, dict[str, Any]] = {}
        for candidate in raw_candidates:
            if (
                not isinstance(candidate, dict)
                or isinstance(candidate.get("rank"), bool)
                or not isinstance(candidate.get("rank"), int)
            ):
                raise ScriptInputError("candidates.json에 유효하지 않은 후보가 있습니다.")
            rank = candidate["rank"]
            if rank in candidates_by_rank:
                raise ScriptInputError("candidates.json에 중복된 후보 순위가 있습니다.")
            candidates_by_rank[rank] = candidate

        missing = [str(rank) for rank in selected_ranks if rank not in candidates_by_rank]
        if missing:
            raise ScriptInputError(f"존재하지 않는 후보 순위입니다: {', '.join(missing)}")

        posts_by_url: dict[str, Post] = {}
        try:
            for raw_post in raw_posts:
                post = Post.from_dict(raw_post)
                if post.url in posts_by_url:
                    raise ScriptInputError("raw_posts.json에 중복된 원문 URL이 있습니다.")
                posts_by_url[post.url] = post
        except (KeyError, TypeError, ValueError) as exc:
            raise ScriptInputError(
                f"raw_posts.json에 유효하지 않은 원문이 있습니다: {exc}"
            ) from exc

        topics: list[TopicBrief] = []
        for rank in selected_ranks:
            candidate = candidates_by_rank[rank]
            url = candidate.get("url")
            post = posts_by_url.get(url)
            if post is None:
                raise ScriptInputError(
                    f"{rank}위 후보의 원문을 raw_posts.json에서 찾을 수 없습니다."
                )
            if candidate.get("post_id") != post.id or candidate.get("title") != post.title:
                raise ScriptInputError(f"{rank}위 후보와 원문의 ID 또는 제목이 일치하지 않습니다.")

            risks = candidate.get("risks")
            review_notes = candidate.get("review_notes")
            if not isinstance(risks, list) or any(not isinstance(item, str) for item in risks):
                raise ScriptInputError(f"{rank}위 후보의 위험 정보가 올바르지 않습니다.")
            if not isinstance(review_notes, str):
                raise ScriptInputError(f"{rank}위 후보의 검토 메모가 올바르지 않습니다.")
            risk_notes = tuple([*risks, *([review_notes] if review_notes else [])])
            truncated = len(post.body) > MAX_SOURCE_MATERIAL_CHARACTERS
            uncertainties = ["커뮤니티 게시물의 주장은 사실 확인되지 않았습니다."]
            if truncated:
                uncertainties.append("원문이 입력 길이 제한으로 일부 잘렸습니다.")

            required_strings = {
                "summary": candidate.get("summary"),
                "reason": candidate.get("reason"),
                "hook": candidate.get("hook"),
                "risk_level": candidate.get("risk_level"),
            }
            invalid = [
                name for name, value in required_strings.items() if not isinstance(value, str)
            ]
            if invalid:
                raise ScriptInputError(
                    f"{rank}위 후보에 필수 문자열이 없습니다: {', '.join(invalid)}"
                )

            topics.append(
                TopicBrief(
                    topic_id=f"{source_run_id}:{post.gallery_id}:{post.id}",
                    origin="community_candidate",
                    title=post.title,
                    summary=required_strings["summary"],
                    source_material=post.body[:MAX_SOURCE_MATERIAL_CHARACTERS],
                    source_material_original_length=len(post.body),
                    source_material_truncated=truncated,
                    desired_angle=required_strings["reason"],
                    audience="YouTube Shorts 일반 시청자",
                    hook_candidates=(required_strings["hook"],),
                    source_references=(
                        SourceReference(
                            id="source_post",
                            source_type="community_post",
                            title=post.title,
                            url=post.url,
                        ),
                    ),
                    risk_level=required_strings["risk_level"],
                    risk_notes=risk_notes,
                    uncertainties=tuple(uncertainties),
                    provenance=TopicProvenance(source_run_id, rank, post.id),
                )
            )
        return source_run_id, tuple(topics)


def load_community_topic_briefs(
    source_run_directory: Path,
    ranks: tuple[int, ...],
) -> tuple[str, tuple[TopicBrief, ...]]:
    return CommunityTopicAdapter(source_run_directory).load(ranks)
