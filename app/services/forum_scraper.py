import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

logger = logging.getLogger(__name__)


@dataclass
class ScrapedTopic:
    external_id: str
    title: str
    url: str
    place_name: str


@dataclass
class ScrapedPost:
    topic_external_id: str
    external_id: str
    author: str
    posted_at_utc: datetime
    content_text: str
    url: str
    attachments: list["ScrapedAttachment"]


@dataclass
class ScrapedAttachment:
    source_url: str
    file_name: str
    is_image: bool


class ForumScraper:
    def __init__(
        self,
        forum_root_url: str,
        max_forum_pages: int,
        max_topic_pages: int,
        timeout_seconds: int,
        max_concurrency: int,
        requests_per_second: float,
        forum_session_cookie: str = "",
    ):
        self.forum_root_url = forum_root_url
        self.max_forum_pages = max_forum_pages
        self.max_topic_pages = max_topic_pages
        self.timeout_seconds = timeout_seconds
        self.semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self.sleep_seconds = 1.0 / max(0.1, requests_per_second)
        self.user_agent = "FishingMapMVPBot/1.0 (+respect robots.txt and ToS)"
        self.forum_session_cookie = forum_session_cookie
        self._robot_parser: RobotFileParser | None = None

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": self.user_agent}
        if self.forum_session_cookie:
            headers["Cookie"] = self.forum_session_cookie
        return headers

    async def _allowed_by_robots(self, url: str) -> bool:
        if self._robot_parser is None:
            parsed = urlparse(self.forum_root_url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            rp = RobotFileParser()
            rp.set_url(robots_url)
            try:
                rp.read()
            except Exception as exc:
                logger.warning("Could not read robots.txt (%s), fallback allow", exc)
                return True
            self._robot_parser = rp
        return self._robot_parser.can_fetch(self.user_agent, url)

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> str:
        if not await self._allowed_by_robots(url):
            logger.warning("Blocked by robots.txt: %s", url)
            return ""
        retries = 3
        for attempt in range(1, retries + 1):
            try:
                async with self.semaphore:
                    response = await client.get(url)
                    response.raise_for_status()
                    await asyncio.sleep(self.sleep_seconds)
                    return response.text
            except Exception as exc:
                if attempt == retries:
                    logger.error("Fetch failed %s: %s", url, exc)
                    return ""
                await asyncio.sleep(attempt * 1.0)
        return ""

    @staticmethod
    def normalize_url(base: str, href: str) -> str:
        return urljoin(base, href)

    @staticmethod
    def extract_topic_external_id(url: str) -> str:
        m = re.search(r"\.(\d+)(?:/|$)", url)
        return m.group(1) if m else url.rstrip("/").split("/")[-1]

    @staticmethod
    def extract_post_external_id(tag) -> str:
        candidates = [tag.get("id", ""), tag.get("data-content", "")]
        for candidate in candidates:
            m = re.search(r"(\d+)", candidate)
            if m:
                return m.group(1)
        return ""

    @staticmethod
    def clean_text(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def extract_content_text(self, message) -> str:
        content_tag = message.select_one("div.bbWrapper, article.message-body, div.message-content")
        if not content_tag:
            return ""
        # Remove attachment metadata blocks from message text.
        for node in content_tag.select(
            ".attachment, .attachments, .message-attachments, .js-attachmentInfo, .bbCodeBlock--unfurl"
        ):
            node.decompose()
        return self.clean_text(content_tag.get_text(" ", strip=True))

    @staticmethod
    def _is_image_filename(name: str) -> bool:
        ext = Path(name.lower()).suffix
        return ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

    def extract_attachments(self, message, page_url: str) -> list[ScrapedAttachment]:
        seen: set[str] = set()
        attachments: list[ScrapedAttachment] = []

        for link in message.select("a[href*='/attachments/']"):
            href = link.get("href")
            if not href:
                continue
            source_url = self.normalize_url(page_url, href)
            if source_url in seen:
                continue
            seen.add(source_url)
            text_name = self.clean_text(link.get_text(" ", strip=True))
            file_name = text_name or Path(urlparse(source_url).path).name or "attachment.bin"
            attachments.append(
                ScrapedAttachment(
                    source_url=source_url,
                    file_name=file_name,
                    is_image=self._is_image_filename(file_name),
                )
            )

        for img in message.select("img[src*='/attachments/']"):
            src = img.get("src")
            if not src:
                continue
            source_url = self.normalize_url(page_url, src)
            if source_url in seen:
                continue
            seen.add(source_url)
            file_name = Path(urlparse(source_url).path).name or "attachment.jpg"
            attachments.append(
                ScrapedAttachment(
                    source_url=source_url,
                    file_name=file_name,
                    is_image=True,
                )
            )
        return attachments

    @staticmethod
    def title_to_place_name(title: str) -> str:
        return ForumScraper.clean_text(title)

    @staticmethod
    def parse_datetime_to_utc(value: str) -> datetime:
        dt = date_parser.parse(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)

    async def fetch_topics(self) -> list[ScrapedTopic]:
        topics: dict[str, ScrapedTopic] = {}
        async with httpx.AsyncClient(timeout=self.timeout_seconds, headers=self._headers(), follow_redirects=True) as client:
            for page in range(1, self.max_forum_pages + 1):
                page_url = self.forum_root_url if page == 1 else f"{self.forum_root_url}page-{page}"
                html = await self._fetch(client, page_url)
                if not html:
                    continue
                soup = BeautifulSoup(html, "html.parser")
                for link in soup.select("a[data-tp-primary='on'], a.structItem-title, .structItem-title a"):
                    href = link.get("href")
                    if not href:
                        continue
                    topic_url = self.normalize_url(page_url, href)
                    if "/threads/" not in topic_url:
                        continue
                    title = self.clean_text(link.get_text(" ", strip=True))
                    topic_external_id = self.extract_topic_external_id(topic_url)
                    topics[topic_external_id] = ScrapedTopic(
                        external_id=topic_external_id,
                        title=title,
                        url=topic_url,
                        place_name=self.title_to_place_name(title),
                    )
        return list(topics.values())

    async def _topic_last_page(self, client: httpx.AsyncClient, topic_url: str) -> int:
        html = await self._fetch(client, topic_url)
        if not html:
            return 1
        soup = BeautifulSoup(html, "html.parser")
        pages = [1]
        for a in soup.select("a[href*='/page-']"):
            href = a.get("href", "")
            m = re.search(r"/page-(\d+)", href)
            if m:
                pages.append(int(m.group(1)))
        return max(pages)

    async def fetch_topic_posts(self, topic: ScrapedTopic) -> list[ScrapedPost]:
        posts: dict[str, ScrapedPost] = {}
        async with httpx.AsyncClient(timeout=self.timeout_seconds, headers=self._headers(), follow_redirects=True) as client:
            last_page = await self._topic_last_page(client, topic.url)
            start_page = max(1, last_page - self.max_topic_pages + 1)
            for page in range(start_page, last_page + 1):
                page_url = topic.url if page == 1 else f"{topic.url}page-{page}"
                html = await self._fetch(client, page_url)
                if not html:
                    continue
                soup = BeautifulSoup(html, "html.parser")
                for message in soup.select("article.message, div.message"):
                    post_external_id = self.extract_post_external_id(message)
                    if not post_external_id:
                        continue
                    author_tag = message.select_one("a.username, h4.message-name, span.username")
                    author = self.clean_text(author_tag.get_text(" ", strip=True)) if author_tag else "unknown"
                    time_tag = message.select_one("time")
                    dt_value = ""
                    if time_tag:
                        dt_value = time_tag.get("datetime") or time_tag.get("title") or time_tag.get_text(" ", strip=True)
                    if not dt_value:
                        continue
                    content_text = self.extract_content_text(message)
                    permalink = message.select_one("a[href*='/posts/'], a.u-concealed")
                    if permalink and permalink.get("href"):
                        post_url = self.normalize_url(page_url, permalink.get("href"))
                    else:
                        post_url = f"{topic.url}#post-{post_external_id}"
                    posts[post_external_id] = ScrapedPost(
                        topic_external_id=topic.external_id,
                        external_id=post_external_id,
                        author=author,
                        posted_at_utc=self.parse_datetime_to_utc(dt_value),
                        content_text=content_text,
                        url=post_url,
                        attachments=self.extract_attachments(message, page_url),
                    )
        return list(posts.values())
