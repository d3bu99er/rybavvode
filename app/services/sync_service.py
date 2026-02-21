import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Post, Topic
from app.services.forum_auth import ForumAuthService
from app.services.forum_scraper import ForumScraper
from app.services.geocoding import GeocodingService, GoogleGeocoder, YandexGeocoder
from app.services.repository import (
    attachments_for_post,
    get_or_create_source,
    upsert_post,
    upsert_post_attachment,
    upsert_topic,
)

logger = logging.getLogger(__name__)


class SyncService:
    def __init__(self):
        settings = get_settings()
        self.settings = settings
        self.user_agent = "FishingMapMVPBot/1.0 (+respect robots.txt and ToS)"
        self.auth = ForumAuthService(
            forum_root_url=settings.forum_root_url,
            forum_login_url=settings.forum_login_url,
            username=settings.forum_username,
            password=settings.forum_password,
            timeout_seconds=settings.http_timeout_seconds,
            user_agent=self.user_agent,
            fallback_cookie=settings.forum_session_cookie,
            preferred_cookie_name=settings.forum_session_cookie_name,
        )
        self.scraper = ForumScraper(
            forum_root_url=settings.forum_root_url,
            max_forum_pages=settings.max_forum_pages,
            max_topic_pages=settings.max_topic_pages,
            timeout_seconds=settings.http_timeout_seconds,
            max_concurrency=settings.max_concurrency,
            requests_per_second=settings.requests_per_second,
            forum_session_cookie=settings.forum_session_cookie,
            user_agent=self.user_agent,
        )

        provider = (
            GoogleGeocoder(settings.google_geocoding_api_key, timeout=settings.http_timeout_seconds)
            if settings.geocoder_provider.lower() == "google"
            else YandexGeocoder(settings.yandex_geocoder_api_key, timeout=settings.http_timeout_seconds)
        )
        self.geocoding = GeocodingService(provider)
        self.attachments_dir = Path(settings.attachments_dir)
        self.attachments_dir.mkdir(parents=True, exist_ok=True)

    async def _ensure_forum_cookie(self, force_refresh: bool = False) -> str:
        cookie = await self.auth.ensure_cookie(force_refresh=force_refresh)
        self.scraper.set_forum_session_cookie(cookie)
        return cookie

    @staticmethod
    def _safe_file_name(file_name: str) -> str:
        keep = []
        for ch in file_name:
            if ch.isalnum() or ch in {"-", "_", ".", " "}:
                keep.append(ch)
            else:
                keep.append("_")
        sanitized = "".join(keep).strip().replace(" ", "_")
        return sanitized or "attachment.bin"

    async def _download_attachment(self, source_url: str, local_abs_path: Path) -> tuple[str | None, int | None] | None:
        cookie = await self._ensure_forum_cookie(force_refresh=False)
        if not cookie:
            return None
        for attempt in range(2):
            headers = {"User-Agent": self.user_agent, "Cookie": cookie}
            try:
                async with httpx.AsyncClient(
                    timeout=self.settings.http_timeout_seconds,
                    follow_redirects=True,
                    headers=headers,
                ) as client:
                    resp = await client.get(source_url)
                    if resp.status_code in {401, 403} or ForumAuthService.is_login_redirect_url(str(resp.url)):
                        if attempt == 0:
                            cookie = await self._ensure_forum_cookie(force_refresh=True)
                            if cookie:
                                continue
                        logger.warning(
                            "Attachment download unauthorized: %s (status=%s, final_url=%s)",
                            source_url,
                            resp.status_code,
                            resp.url,
                        )
                        return None
                    resp.raise_for_status()
                    data = resp.content
                    local_abs_path.parent.mkdir(parents=True, exist_ok=True)
                    local_abs_path.write_bytes(data)
                    return resp.headers.get("content-type"), len(data)
            except Exception as exc:
                if attempt == 0:
                    cookie = await self._ensure_forum_cookie(force_refresh=True)
                    if cookie:
                        continue
                logger.warning("Attachment download failed: %s (%s)", source_url, exc)
                return None
        return None

    async def retry_post_attachments(self, db: Session, post: Post, force: bool = False) -> tuple[int, int]:
        downloaded = 0
        total = 0
        for att in attachments_for_post(db, post.id):
            total += 1
            safe_name = self._safe_file_name(att.file_name)
            rel_path = f"{post.id}/{att.id}_{safe_name}"
            abs_path = self.attachments_dir / rel_path
            if abs_path.exists() and not force:
                if att.local_rel_path != rel_path:
                    att.local_rel_path = rel_path
                continue
            result = await self._download_attachment(att.source_url, abs_path)
            if result:
                mime_type, size_bytes = result
                att.local_rel_path = rel_path
                att.mime_type = mime_type
                att.size_bytes = size_bytes
                downloaded += 1
        return downloaded, total

    def geocode_expired(self, topic: Topic) -> bool:
        if topic.geocoded_lat is None or topic.geocoded_lon is None or topic.geocode_updated_at is None:
            return True
        ttl = timedelta(days=self.settings.geocode_ttl_days)
        return topic.geocode_updated_at < datetime.now(UTC) - ttl

    async def run(self, db: Session):
        await self._ensure_forum_cookie(force_refresh=False)
        source = get_or_create_source(db, self.settings.forum_source_name, self.settings.forum_root_url)
        db.commit()
        topics = await self.scraper.fetch_topics()
        logger.info("Fetched %s topics", len(topics))
        for scraped_topic in topics:
            try:
                topic = upsert_topic(
                    db,
                    source_id=source.id,
                    external_id=scraped_topic.external_id,
                    title=scraped_topic.title,
                    url=scraped_topic.url,
                    place_name=scraped_topic.place_name,
                )
                posts = await self.scraper.fetch_topic_posts(scraped_topic)
                for p in posts:
                    post = upsert_post(
                        db,
                        topic_id=topic.id,
                        external_id=p.external_id,
                        author=p.author,
                        posted_at_utc=p.posted_at_utc,
                        content_text=p.content_text,
                        url=p.url,
                    )
                    for idx, attachment in enumerate(p.attachments):
                        safe_name = self._safe_file_name(attachment.file_name)
                        rel_path = f"{post.id}/{idx}_{safe_name}"
                        abs_path = self.attachments_dir / rel_path
                        mime_type = None
                        size_bytes = None
                        if self.settings.download_attachments and not abs_path.exists():
                            downloaded = await self._download_attachment(attachment.source_url, abs_path)
                            if downloaded:
                                mime_type, size_bytes = downloaded
                        upsert_post_attachment(
                            db,
                            post_id=post.id,
                            source_url=attachment.source_url,
                            file_name=attachment.file_name,
                            is_image=attachment.is_image,
                            local_rel_path=rel_path if abs_path.exists() else None,
                            mime_type=mime_type,
                            size_bytes=size_bytes,
                        )
                if self.geocode_expired(topic):
                    geo = await self.geocoding.geocode(topic.place_name)
                    if geo:
                        topic.geocoded_lat = geo.lat
                        topic.geocoded_lon = geo.lon
                        topic.geocode_provider = geo.provider
                        topic.geocode_confidence = geo.confidence
                        topic.geocode_updated_at = datetime.now(UTC)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Failed processing topic %s", scraped_topic.url)
