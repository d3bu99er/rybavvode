import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Post, PostAttachment, Topic
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

    @staticmethod
    def _looks_like_image(mime_type: str | None = None, *values: str | None) -> bool:
        if mime_type and mime_type.lower().startswith("image/"):
            return True
        image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
        image_token_pattern = re.compile(r"(?:^|[-_.])(jpg|jpeg|png|gif|webp|bmp)(?:[.-]\d+)?$", re.IGNORECASE)
        for value in values:
            if not value:
                continue
            path = urlparse(value).path
            name = Path(path).name
            ext = Path(name).suffix.lower()
            if ext in image_exts:
                return True
            base_no_query = name.split("?", maxsplit=1)[0]
            if image_token_pattern.search(base_no_query):
                return True
        return False

    def _canonical_attachment_rel_path(self, post_id: int, attachment_id: int, file_name: str) -> str:
        safe_name = self._safe_file_name(file_name)
        return f"{post_id}/{attachment_id}_{safe_name}"

    def _resolve_attachment_path(self, rel_path: str) -> Path | None:
        try:
            root = self.attachments_dir.resolve()
            candidate = (self.attachments_dir / rel_path).resolve()
            candidate.relative_to(root)
            return candidate
        except Exception:
            return None

    def _find_existing_attachment_rel_path(self, post_id: int, attachment_id: int, file_name: str) -> str | None:
        canonical_rel = self._canonical_attachment_rel_path(post_id, attachment_id, file_name)
        canonical_abs = self.attachments_dir / canonical_rel
        if canonical_abs.exists():
            return canonical_rel

        safe_name = self._safe_file_name(file_name)
        post_dir = self.attachments_dir / str(post_id)
        if not post_dir.exists():
            return None

        # Legacy files used a sequence index prefix: "<post_id>/<idx>_<safe_name>".
        pattern = f"*_{safe_name}"
        for candidate in sorted(post_dir.glob(pattern)):
            if candidate.is_file():
                return f"{post_id}/{candidate.name}"
        return None

    @staticmethod
    def _cookie_names(cookie_header: str) -> str:
        names: list[str] = []
        for chunk in cookie_header.split(";"):
            if "=" not in chunk:
                continue
            name = chunk.split("=", maxsplit=1)[0].strip()
            if name:
                names.append(name)
        return ",".join(names) if names else "<none>"

    @staticmethod
    def _response_text_preview(resp: httpx.Response, limit: int = 220) -> str:
        content_type = (resp.headers.get("content-type") or "").lower()
        if content_type and not any(t in content_type for t in {"text", "json", "xml", "html"}):
            return ""
        try:
            text = resp.text
        except Exception:
            return ""
        text = re.sub(r"\s+", " ", text).strip()
        return text[:limit]

    @classmethod
    def _auth_failure_reason(cls, resp: httpx.Response) -> str:
        markers: list[str] = []
        final_url = str(resp.url)
        content_type = (resp.headers.get("content-type") or "").lower() or "<none>"
        location = resp.headers.get("location")
        body_preview = cls._response_text_preview(resp)
        lowered = body_preview.lower()

        if resp.status_code == 401:
            markers.append("http_401")
        if resp.status_code == 403:
            markers.append("http_403")
        if ForumAuthService.is_login_redirect_url(final_url):
            markers.append("redirected_to_login")
        if "cloudflare" in lowered or "cf-chl" in lowered or "captcha" in lowered or "verify you are human" in lowered:
            markers.append("anti_bot_challenge")
        if (
            "you do not have permission" in lowered
            or "permission denied" in lowered
            or "forbidden" in lowered
        ):
            markers.append("permission_denied_page")
        if (
            "login/login" in lowered
            or "/login/" in lowered
            or "log in" in lowered
            or "sign in" in lowered
        ):
            markers.append("login_required_page")
        if not markers:
            markers.append("no_known_marker")

        parts = [f"markers={','.join(markers)}", f"content_type={content_type}"]
        if location:
            parts.append(f"location={location}")
        if body_preview:
            parts.append(f"body_preview={body_preview}")
        return "; ".join(parts)

    async def _download_attachment(
        self, source_url: str, local_abs_path: Path
    ) -> tuple[str | None, int | None, str] | None:
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
                        reason = self._auth_failure_reason(resp)
                        logger.warning(
                            "Attachment download unauthorized: %s (status=%s, final_url=%s, cookie_names=%s, reason=%s)",
                            source_url,
                            resp.status_code,
                            resp.url,
                            self._cookie_names(cookie),
                            reason,
                        )
                        return None
                    resp.raise_for_status()
                    data = resp.content
                    local_abs_path.parent.mkdir(parents=True, exist_ok=True)
                    local_abs_path.write_bytes(data)
                    return resp.headers.get("content-type"), len(data), str(resp.url)
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
            if not att.is_image and self._looks_like_image(att.mime_type, att.file_name, att.source_url):
                att.is_image = True

            existing_rel = self._find_existing_attachment_rel_path(post.id, att.id, att.file_name)
            if existing_rel and not force:
                if att.local_rel_path != existing_rel:
                    att.local_rel_path = existing_rel
                abs_existing = self.attachments_dir / existing_rel
                if abs_existing.exists():
                    att.size_bytes = abs_existing.stat().st_size
                if not att.is_image and self._looks_like_image(att.mime_type, att.file_name, att.source_url, existing_rel):
                    att.is_image = True
                continue

            # Download only images; skip non-image attachments by design.
            if not att.is_image:
                continue

            rel_path = self._canonical_attachment_rel_path(post.id, att.id, att.file_name)
            abs_path = self.attachments_dir / rel_path
            result = await self._download_attachment(att.source_url, abs_path)
            if result:
                mime_type, size_bytes, final_url = result
                att.local_rel_path = rel_path
                att.mime_type = mime_type
                att.size_bytes = size_bytes
                if not att.is_image and self._looks_like_image(mime_type, att.file_name, att.source_url, final_url, rel_path):
                    att.is_image = True
                downloaded += 1
        return downloaded, total

    async def retry_missing_attachments(self, db: Session, posts_limit: int = 100) -> tuple[int, int, int]:
        limit = max(1, min(int(posts_limit), 1000))
        post_ids = [
            row[0]
            for row in db.execute(
                select(PostAttachment.post_id)
                .where(PostAttachment.local_rel_path.is_(None))
                .group_by(PostAttachment.post_id)
                .order_by(PostAttachment.post_id.desc())
                .limit(limit)
            ).all()
        ]
        if not post_ids:
            logger.info("Retry missing attachments: nothing to process")
            return 0, 0, 0

        processed_posts = 0
        downloaded_total = 0
        checked_total = 0

        for post_id in post_ids:
            post = db.get(Post, post_id)
            if not post:
                continue
            try:
                downloaded, checked = await self.retry_post_attachments(db, post, force=False)
                db.commit()
                processed_posts += 1
                downloaded_total += downloaded
                checked_total += checked
            except Exception:
                db.rollback()
                logger.exception("Retry missing attachments failed for post_id=%s", post_id)
        logger.info(
            "Retry missing attachments finished (posts=%s, downloaded=%s, checked=%s)",
            processed_posts,
            downloaded_total,
            checked_total,
        )
        return processed_posts, downloaded_total, checked_total

    def cleanup_non_image_attachments(self, db: Session, limit: int = 1000) -> tuple[int, int, int, int]:
        rows_limit = max(1, min(int(limit), 20000))
        rows = db.execute(
            select(PostAttachment)
            .where(PostAttachment.local_rel_path.is_not(None), PostAttachment.is_image.is_(False))
            .order_by(PostAttachment.id.asc())
            .limit(rows_limit)
        ).scalars().all()

        scanned = len(rows)
        deleted_files = 0
        detached_rows = 0
        reclassified_rows = 0

        for att in rows:
            rel_path = att.local_rel_path or ""
            if self._looks_like_image(att.mime_type, att.file_name, att.source_url, rel_path):
                if not att.is_image:
                    att.is_image = True
                    reclassified_rows += 1
                continue

            abs_path = self._resolve_attachment_path(rel_path)
            if abs_path and abs_path.exists() and abs_path.is_file():
                try:
                    abs_path.unlink()
                    deleted_files += 1
                except Exception as exc:
                    logger.warning("Failed deleting non-image attachment file: %s (%s)", abs_path, exc)
            if abs_path:
                parent = abs_path.parent
                if parent != self.attachments_dir:
                    try:
                        parent.rmdir()
                    except OSError:
                        pass

            att.local_rel_path = None
            att.size_bytes = None
            att.mime_type = None
            detached_rows += 1

        if scanned:
            logger.info(
                "Cleanup non-image attachments finished (scanned=%s, deleted_files=%s, detached_rows=%s, reclassified_rows=%s)",
                scanned,
                deleted_files,
                detached_rows,
                reclassified_rows,
            )
        return scanned, deleted_files, detached_rows, reclassified_rows

    async def geocode_topic(self, db: Session, topic: Topic) -> str:
        if (topic.geocode_provider or "").lower() == "manual":
            return "skipped_manual"
        if not topic.place_name:
            return "skipped_empty_place"
        geo = await self.geocoding.geocode(topic.place_name)
        if not geo:
            return "not_found"
        topic.geocoded_lat = geo.lat
        topic.geocoded_lon = geo.lon
        topic.geocode_provider = geo.provider
        topic.geocode_confidence = geo.confidence
        topic.geocode_updated_at = datetime.now(UTC)
        db.flush()
        return "updated"

    async def run(self, db: Session):
        await self._ensure_forum_cookie(force_refresh=False)
        source = get_or_create_source(db, self.settings.forum_source_name, self.settings.forum_root_url)
        scanned, deleted_files, detached_rows, reclassified_rows = self.cleanup_non_image_attachments(db, limit=1000)
        if deleted_files or detached_rows or reclassified_rows:
            logger.info(
                "Applied non-image cleanup in run() (scanned=%s, deleted_files=%s, detached_rows=%s, reclassified_rows=%s)",
                scanned,
                deleted_files,
                detached_rows,
                reclassified_rows,
            )
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
                    for attachment in p.attachments:
                        db_attachment = upsert_post_attachment(
                            db,
                            post_id=post.id,
                            source_url=attachment.source_url,
                            file_name=attachment.file_name,
                            is_image=attachment.is_image,
                        )

                        if not db_attachment.is_image and self._looks_like_image(
                            db_attachment.mime_type,
                            db_attachment.file_name,
                            db_attachment.source_url,
                        ):
                            db_attachment.is_image = True

                        existing_rel = self._find_existing_attachment_rel_path(
                            post_id=post.id,
                            attachment_id=db_attachment.id,
                            file_name=db_attachment.file_name,
                        )
                        if existing_rel:
                            db_attachment.local_rel_path = existing_rel
                            abs_existing = self.attachments_dir / existing_rel
                            if abs_existing.exists():
                                db_attachment.size_bytes = abs_existing.stat().st_size
                            if not db_attachment.is_image and self._looks_like_image(
                                db_attachment.mime_type,
                                db_attachment.file_name,
                                db_attachment.source_url,
                                existing_rel,
                            ):
                                db_attachment.is_image = True
                            continue

                        rel_path = self._canonical_attachment_rel_path(post.id, db_attachment.id, db_attachment.file_name)
                        abs_path = self.attachments_dir / rel_path
                        if self.settings.download_attachments and db_attachment.is_image and not abs_path.exists():
                            downloaded = await self._download_attachment(db_attachment.source_url, abs_path)
                            if downloaded:
                                mime_type, size_bytes, final_url = downloaded
                                db_attachment.mime_type = mime_type
                                db_attachment.size_bytes = size_bytes
                                if not db_attachment.is_image and self._looks_like_image(
                                    mime_type,
                                    db_attachment.file_name,
                                    db_attachment.source_url,
                                    final_url,
                                    rel_path,
                                ):
                                    db_attachment.is_image = True
                        if abs_path.exists():
                            db_attachment.local_rel_path = rel_path
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Failed processing topic %s", scraped_topic.url)
