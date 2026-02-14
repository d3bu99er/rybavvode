import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Topic
from app.services.forum_scraper import ForumScraper
from app.services.geocoding import GeocodingService, GoogleGeocoder, YandexGeocoder
from app.services.repository import get_or_create_source, upsert_post, upsert_topic

logger = logging.getLogger(__name__)


class SyncService:
    def __init__(self):
        settings = get_settings()
        self.settings = settings
        self.scraper = ForumScraper(
            forum_root_url=settings.forum_root_url,
            max_forum_pages=settings.max_forum_pages,
            max_topic_pages=settings.max_topic_pages,
            timeout_seconds=settings.http_timeout_seconds,
            max_concurrency=settings.max_concurrency,
            requests_per_second=settings.requests_per_second,
            forum_session_cookie=settings.forum_session_cookie,
        )

        provider = (
            GoogleGeocoder(settings.google_geocoding_api_key, timeout=settings.http_timeout_seconds)
            if settings.geocoder_provider.lower() == "google"
            else YandexGeocoder(settings.yandex_geocoder_api_key, timeout=settings.http_timeout_seconds)
        )
        self.geocoding = GeocodingService(provider)

    def geocode_expired(self, topic: Topic) -> bool:
        if topic.geocoded_lat is None or topic.geocoded_lon is None or topic.geocode_updated_at is None:
            return True
        ttl = timedelta(days=self.settings.geocode_ttl_days)
        return topic.geocode_updated_at < datetime.now(UTC) - ttl

    async def run(self, db: Session):
        source = get_or_create_source(db, self.settings.forum_source_name, self.settings.forum_root_url)
        topics = await self.scraper.fetch_topics()
        logger.info("Fetched %s topics", len(topics))
        for scraped_topic in topics:
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
                upsert_post(
                    db,
                    topic_id=topic.id,
                    external_id=p.external_id,
                    author=p.author,
                    posted_at_utc=p.posted_at_utc,
                    content_text=p.content_text,
                    url=p.url,
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
