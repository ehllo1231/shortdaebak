from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.config import (
    AppConfig,
    CodexConfig,
    DcinsideConfig,
    GalleryConfig,
    OutputConfig,
    PrefilterConfig,
)
from app.models import KST, Post


@pytest.fixture
def fixture_directory() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        dcinside=DcinsideConfig(
            galleries=(GalleryConfig("story", "이야기 갤러리", "major"),),
            pages_per_gallery=1,
            request_interval_seconds=0,
            timeout_seconds=5,
            retries=0,
            min_body_length=30,
            excluded_keywords=("광고",),
            dedupe_history_days=30,
            user_agent="test-agent",
        ),
        prefilter=PrefilterConfig(
            candidate_count=20,
            weights={
                "recency": 0.25,
                "recommendations": 0.25,
                "comments": 0.20,
                "views": 0.10,
                "body_length": 0.10,
                "engagement": 0.10,
            },
        ),
        codex=CodexConfig(
            enabled=True,
            executable="codex",
            timeout_seconds=30,
            final_candidate_count=5,
            sandbox="read-only",
            ephemeral=True,
        ),
        output=OutputConfig(tmp_path / "output"),
    )


@pytest.fixture
def sample_posts() -> list[Post]:
    now = datetime(2026, 7, 19, 12, 0, tzinfo=KST)
    return [
        Post(
            id=str(1000 + index),
            title=f"이야기 {index}",
            body=(f"{index}번 게시물에서 예상치 못한 일이 벌어졌다. " + chr(65 + index) * 120),
            url=f"https://gall.dcinside.com/board/view/?id=story&no={1000 + index}&page=1",
            gallery_id="story",
            gallery_name="이야기 갤러리",
            gallery_type="major",
            created_at=now - timedelta(hours=index),
            views=100 + index * 20,
            recommendations=index * 2,
            comments=index,
        )
        for index in range(25)
    ]
