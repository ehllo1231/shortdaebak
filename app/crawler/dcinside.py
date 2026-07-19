from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Callable
from datetime import datetime
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup, Tag

from app.config import DcinsideConfig, GalleryConfig
from app.models import KST, Post
from app.progress import ProgressBar

BASE_URL = "https://gall.dcinside.com"
BLOCK_MARKERS = ("캡차", "captcha", "access denied", "접근이 차단", "비정상적인 접근")
SPACE_RE = re.compile(r"[ \t\r\f\v]+")


class CrawlError(RuntimeError):
    pass


class CrawlBlockedError(CrawlError):
    pass


class ParseError(CrawlError):
    pass


def _route(gallery_type: str) -> str:
    return "board" if gallery_type == "major" else "mgallery/board"


def _list_url(gallery: GalleryConfig, page: int) -> str:
    query = urlencode({"id": gallery.id, "page": page})
    return f"{BASE_URL}/{_route(gallery.type)}/lists/?{query}"


def _view_url(gallery: GalleryConfig, post_id: str, page: int) -> str:
    query = urlencode({"id": gallery.id, "no": post_id, "page": page})
    return f"{BASE_URL}/{_route(gallery.type)}/view/?{query}"


def _parse_count(value: str) -> int:
    text = value.strip().replace(",", "")
    if not text or text == "-":
        return 0
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(만|[kK])?", text)
    if not match:
        return 0
    number = float(match.group(1))
    suffix = match.group(2)
    if suffix == "만":
        number *= 10_000
    elif suffix and suffix.lower() == "k":
        number *= 1_000
    return max(0, int(number))


def _parse_datetime(value: str, now: datetime) -> datetime:
    text = value.strip()
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y.%m.%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=KST)
        except ValueError:
            continue
    for pattern in ("%H:%M", "%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, pattern)
            return now.astimezone(KST).replace(
                hour=parsed.hour, minute=parsed.minute, second=parsed.second, microsecond=0
            )
        except ValueError:
            continue
    for pattern in ("%y.%m.%d", "%y/%m/%d"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=KST)
        except ValueError:
            continue
    raise ParseError(f"게시 시간을 해석할 수 없습니다: {text!r}")


def _required_text(row: Tag, selector: str) -> str:
    element = row.select_one(selector)
    if element is None:
        raise ParseError(f"필수 요소를 찾을 수 없습니다: {selector}")
    return element.get_text(" ", strip=True)


def parse_list_page(
    html: str,
    gallery: GalleryConfig,
    page: int,
    *,
    now: datetime | None = None,
) -> list[Post]:
    current_time = now or datetime.now(KST)
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("table.gall_list tbody tr.ub-content")
    if not rows:
        lowered = html.casefold()
        if any(marker.casefold() in lowered for marker in BLOCK_MARKERS):
            raise CrawlBlockedError("사이트가 CAPTCHA 또는 접근 차단 화면을 반환했습니다.")
        raise ParseError(
            "게시물 목록을 찾지 못했습니다. DCInside HTML 구조가 변경됐을 수 있습니다."
        )

    posts: list[Post] = []
    for row in rows:
        post_id = (row.get("data-no") or "").strip()
        number = _required_text(row, "td.gall_num")
        data_type = (row.get("data-type") or "").casefold()
        if not post_id or not number.isdigit() or data_type == "icon_notice":
            continue

        title_cell = row.select_one("td.gall_tit")
        if title_cell is None or title_cell.select_one("em.icon_ad"):
            continue
        anchor = title_cell.select_one('a[href*="/view/"]')
        if anchor is None:
            continue
        title = SPACE_RE.sub(" ", anchor.get_text(" ", strip=True)).strip()
        if not title:
            continue

        date_element = row.select_one("td.gall_date")
        if date_element is None:
            raise ParseError(f"게시물 {post_id}의 작성 시간을 찾을 수 없습니다.")
        date_text = date_element.get("title") or date_element.get_text(" ", strip=True)
        reply = title_cell.select_one(".reply_num")
        comments = _parse_count(reply.get_text(strip=True).strip("[]")) if reply else 0
        posts.append(
            Post(
                id=post_id,
                title=title,
                body="",
                url=_view_url(gallery, post_id, page),
                gallery_id=gallery.id,
                gallery_name=gallery.name,
                gallery_type=gallery.type,
                created_at=_parse_datetime(date_text, current_time),
                views=_parse_count(_required_text(row, "td.gall_count")),
                recommendations=_parse_count(_required_text(row, "td.gall_recommend")),
                comments=comments,
                source_page=page,
            )
        )
    return posts


def parse_view_page(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one(".writing_view_box .write_div, .view_content_wrap .write_div")
    if body is None:
        lowered = html.casefold()
        if any(marker.casefold() in lowered for marker in BLOCK_MARKERS):
            raise CrawlBlockedError("사이트가 CAPTCHA 또는 접근 차단 화면을 반환했습니다.")
        raise ParseError(
            "게시물 본문을 찾지 못했습니다. 삭제된 글이거나 HTML 구조가 변경됐을 수 있습니다."
        )
    for element in body.select("script, style, noscript, iframe"):
        element.decompose()
    lines = []
    for line in body.get_text("\n").splitlines():
        normalized = SPACE_RE.sub(" ", line).strip()
        if normalized:
            lines.append(normalized)
    return "\n".join(lines)


class DcinsideCrawler:
    def __init__(
        self,
        config: DcinsideConfig,
        *,
        logger: logging.Logger | None = None,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.session = session or requests.Session()
        self.session.headers.update(
            {"User-Agent": config.user_agent, "Accept-Language": "ko-KR,ko;q=0.9"}
        )
        self.sleep = sleep
        self.monotonic = monotonic
        self._last_request_at: float | None = None

    def _wait_for_interval(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = self.monotonic() - self._last_request_at
        wait = self.config.request_interval_seconds - elapsed
        if wait > 0:
            self.sleep(wait)

    def _get(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(self.config.retries + 1):
            self._wait_for_interval()
            try:
                response = self.session.get(url, timeout=self.config.timeout_seconds)
                self._last_request_at = self.monotonic()
                if response.status_code == 403:
                    raise CrawlBlockedError(
                        f"HTTP {response.status_code}: 접근이 차단됐거나 요청이 제한됐습니다."
                    )
                if response.status_code == 429:
                    last_error = CrawlBlockedError("HTTP 429: 요청이 제한됐습니다.")
                    if attempt >= self.config.retries:
                        raise last_error
                    delay = min(8.0, math.pow(2, attempt))
                    self.logger.warning("HTTP 429, %.1f초 후 재시도", delay)
                    self.sleep(delay)
                    continue
                response.raise_for_status()
                response.encoding = response.apparent_encoding or "utf-8"
                return response.text
            except CrawlBlockedError:
                raise
            except requests.RequestException as exc:
                self._last_request_at = self.monotonic()
                last_error = exc
                if attempt >= self.config.retries:
                    break
                delay = min(8.0, math.pow(2, attempt))
                self.logger.warning(
                    "HTTP 요청 실패, %.1f초 후 재시도 (%d/%d): %s",
                    delay,
                    attempt + 1,
                    self.config.retries,
                    url,
                )
                self.sleep(delay)
        raise CrawlError(f"HTTP 요청이 실패했습니다: {url}: {last_error}") from last_error

    def collect(self) -> list[Post]:
        collected: list[Post] = []
        successful_list_pages = 0
        for gallery in self.config.galleries:
            summaries: list[Post] = []
            for page in range(1, self.config.pages_per_gallery + 1):
                url = _list_url(gallery, page)
                try:
                    summaries.extend(parse_list_page(self._get(url), gallery, page))
                    successful_list_pages += 1
                except CrawlBlockedError:
                    raise
                except CrawlError as exc:
                    self.logger.error("목록 수집 실패 [%s, %d페이지]: %s", gallery.name, page, exc)
            self.logger.info("%s: 목록에서 %d개 게시물 발견", gallery.name, len(summaries))
            seen: set[str] = set()
            unique_summaries: list[Post] = []
            for summary in summaries:
                key = f"{summary.gallery_id}:{summary.id}"
                if key in seen:
                    continue
                seen.add(key)
                unique_summaries.append(summary)
            progress = ProgressBar(
                f"{gallery.name} 본문 수집",
                len(unique_summaries),
                self.logger,
                clock=self.monotonic,
            )
            progress.start()
            for summary in unique_summaries:
                success = False
                try:
                    body = parse_view_page(self._get(summary.url))
                except CrawlBlockedError:
                    raise
                except CrawlError as exc:
                    self.logger.warning("본문 수집 실패 [%s/%s]: %s", gallery.id, summary.id, exc)
                else:
                    summary.body = body
                    collected.append(summary)
                    success = True
                finally:
                    progress.advance(success=success)
        if successful_list_pages == 0:
            raise CrawlError("모든 갤러리 목록 수집이 실패했습니다.")
        return collected
