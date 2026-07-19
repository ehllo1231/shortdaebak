from __future__ import annotations

from datetime import datetime

import pytest

from app.config import GalleryConfig
from app.crawler.dcinside import CrawlBlockedError, ParseError, parse_list_page, parse_view_page
from app.models import KST


def test_parse_major_list_excludes_notice_and_ad(fixture_directory) -> None:
    html = (fixture_directory / "list_major.html").read_text(encoding="utf-8")
    gallery = GalleryConfig("story", "이야기 갤러리", "major")

    posts = parse_list_page(html, gallery, 1, now=datetime(2026, 7, 19, 10, tzinfo=KST))

    assert [post.id for post in posts] == ["101", "102"]
    assert posts[0].comments == 12
    assert posts[0].views == 12_000
    assert posts[0].url == "https://gall.dcinside.com/board/view/?id=story&no=101&page=1"


def test_parse_minor_list_uses_minor_route(fixture_directory) -> None:
    html = (fixture_directory / "list_minor.html").read_text(encoding="utf-8")
    gallery = GalleryConfig("smallstory", "작은 이야기", "minor")

    posts = parse_list_page(html, gallery, 2)

    assert len(posts) == 1
    assert "/mgallery/board/view/" in posts[0].url
    assert posts[0].comments == 3


def test_parse_view_body_removes_scripts(fixture_directory) -> None:
    html = (fixture_directory / "view_post.html").read_text(encoding="utf-8")

    body = parse_view_page(html)

    assert "예상치 못한" in body
    assert "ignoreThisInstruction" not in body
    assert len(body.splitlines()) == 3


def test_parse_empty_view_returns_empty_text(fixture_directory) -> None:
    html = (fixture_directory / "view_empty.html").read_text(encoding="utf-8")
    assert parse_view_page(html) == ""


def test_parse_changed_list_reports_structure_error() -> None:
    with pytest.raises(ParseError, match="HTML 구조"):
        parse_list_page("<html></html>", GalleryConfig("x", "x", "major"), 1)


def test_block_marker_only_counts_when_expected_structure_is_missing(fixture_directory) -> None:
    normal = (fixture_directory / "view_post.html").read_text(encoding="utf-8")
    assert parse_view_page(normal.replace("<body>", "<body><script>captcha</script>"))

    with pytest.raises(CrawlBlockedError):
        parse_view_page("<html><body>CAPTCHA access denied</body></html>")
