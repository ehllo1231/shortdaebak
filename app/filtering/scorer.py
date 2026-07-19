from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher

from app.config import WEIGHT_NAMES, DcinsideConfig, PrefilterConfig
from app.models import KST, HistoryIndex, Post

NORMALIZE_RE = re.compile(r"[^0-9a-zA-Z가-힣]+")


@dataclass(frozen=True, slots=True)
class FilterResult:
    selected: tuple[Post, ...]
    eligible_count: int
    exclusions: dict[str, int]


def _normalized_text(post: Post) -> str:
    value = f"{post.title} {post.body[:1000]}".casefold()
    return NORMALIZE_RE.sub("", value)


def _quality_key(post: Post) -> tuple[int, int, int, datetime]:
    return (post.recommendations, post.comments, post.views, post.created_at)


def _minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    low = min(values)
    high = max(values)
    if math.isclose(low, high):
        return [0.5] * len(values)
    return [(value - low) / (high - low) for value in values]


def _deduplicate(posts: list[Post], exclusions: Counter[str]) -> list[Post]:
    exact: dict[tuple[str, str], Post] = {}
    for post in posts:
        key = (post.gallery_id, post.id)
        previous = exact.get(key)
        if previous is None or _quality_key(post) > _quality_key(previous):
            if previous is not None:
                exclusions["duplicate"] += 1
            exact[key] = post
        else:
            exclusions["duplicate"] += 1

    kept: list[Post] = []
    normalized: list[str] = []
    for post in sorted(exact.values(), key=_quality_key, reverse=True):
        text = _normalized_text(post)
        duplicate = any(
            SequenceMatcher(None, text, previous, autojunk=False).ratio() >= 0.90
            for previous in normalized
            if text and previous
        )
        if duplicate:
            exclusions["near_duplicate"] += 1
            continue
        kept.append(post)
        normalized.append(text)
    return kept


def filter_posts(
    posts: list[Post],
    dc_config: DcinsideConfig,
    prefilter_config: PrefilterConfig,
    *,
    history: HistoryIndex | None = None,
    now: datetime | None = None,
) -> FilterResult:
    history_index = history or HistoryIndex()
    current_time = (now or datetime.now(KST)).astimezone(KST)
    exclusions: Counter[str] = Counter()
    eligible: list[Post] = []
    keywords = tuple(keyword.casefold() for keyword in dc_config.excluded_keywords)

    for post in posts:
        combined = f"{post.title}\n{post.body}".casefold()
        history_key = HistoryIndex.key(post.gallery_id, post.id)
        if not post.body.strip():
            exclusions["empty_body"] += 1
        elif len(post.body.strip()) < dc_config.min_body_length:
            exclusions["short_body"] += 1
        elif keywords and any(keyword in combined for keyword in keywords):
            exclusions["excluded_keyword"] += 1
        elif post.url in history_index.urls or history_key in history_index.post_keys:
            exclusions["history_duplicate"] += 1
        else:
            eligible.append(post)

    eligible = _deduplicate(eligible, exclusions)
    if not eligible:
        return FilterResult((), 0, dict(exclusions))

    age_hours = [
        max(0.0, (current_time - post.created_at.astimezone(KST)).total_seconds() / 3600)
        for post in eligible
    ]
    raw: dict[str, list[float]] = {
        "recency": [math.pow(0.5, age / 72.0) for age in age_hours],
        "recommendations": [math.log1p(post.recommendations) for post in eligible],
        "comments": [math.log1p(post.comments) for post in eligible],
        "views": [math.log1p(post.views) for post in eligible],
        "body_length": [min(len(post.body) / 1000.0, 1.0) for post in eligible],
        "engagement": [
            (post.recommendations + post.comments) / max(post.views, 1) for post in eligible
        ],
    }
    normalized = {
        name: values if name in {"recency", "body_length"} else _minmax(values)
        for name, values in raw.items()
    }
    weight_total = sum(prefilter_config.weights.values())
    scored: list[Post] = []
    for index, post in enumerate(eligible):
        components = {name: round(normalized[name][index], 6) for name in WEIGHT_NAMES}
        score = (
            sum(components[name] * prefilter_config.weights[name] for name in WEIGHT_NAMES)
            / weight_total
            * 100
        )
        scored.append(post.with_score(round(score, 3), components))

    scored.sort(
        key=lambda post: (
            post.rule_score or 0,
            post.recommendations,
            post.comments,
            post.created_at,
        ),
        reverse=True,
    )
    selected = tuple(scored[: prefilter_config.candidate_count])
    return FilterResult(selected, len(scored), dict(exclusions))
