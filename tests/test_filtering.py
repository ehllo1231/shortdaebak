from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from app.filtering import filter_posts
from app.models import KST, HistoryIndex


def test_score_and_select_top_twenty(app_config, sample_posts) -> None:
    result = filter_posts(
        sample_posts,
        app_config.dcinside,
        app_config.prefilter,
        now=datetime(2026, 7, 19, 12, tzinfo=KST),
    )

    assert result.eligible_count == 25
    assert len(result.selected) == 20
    assert all(post.rule_score is not None for post in result.selected)
    assert result.selected == tuple(
        sorted(result.selected, key=lambda post: post.rule_score, reverse=True)
    )


def test_exclusions_and_history_deduplication(app_config, sample_posts) -> None:
    empty = replace(sample_posts[0], id="empty", body="", url="https://example/empty")
    short = replace(sample_posts[1], id="short", body="짧음", url="https://example/short")
    keyword = replace(
        sample_posts[2], id="keyword", body="광고 " * 30, url="https://example/keyword"
    )
    history = HistoryIndex(
        urls=frozenset({sample_posts[3].url}),
        post_keys=frozenset(),
    )

    result = filter_posts(
        [empty, short, keyword, sample_posts[3], sample_posts[4]],
        app_config.dcinside,
        app_config.prefilter,
        history=history,
    )

    assert len(result.selected) == 1
    assert result.exclusions == {
        "empty_body": 1,
        "short_body": 1,
        "excluded_keyword": 1,
        "history_duplicate": 1,
    }


def test_near_duplicate_keeps_stronger_post(app_config, sample_posts) -> None:
    first = sample_posts[0]
    stronger = replace(
        first,
        id="other",
        url="https://example/other",
        recommendations=100,
        comments=50,
    )

    result = filter_posts([first, stronger], app_config.dcinside, app_config.prefilter)

    assert [post.id for post in result.selected] == ["other"]
    assert result.exclusions["near_duplicate"] == 1
