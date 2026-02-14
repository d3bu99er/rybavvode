from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Post, Source, Topic


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    testing_session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session, future=True)
    Base.metadata.create_all(bind=engine)
    session = testing_session_local()

    source = Source(name="test", base_url="https://example.com")
    session.add(source)
    session.flush()

    topic = Topic(
        source_id=source.id,
        external_id="1",
        title="Пруд Рыбный",
        url="https://example.com/t/1",
        place_name="Пруд Рыбный",
        geocoded_lat=55.7,
        geocoded_lon=37.6,
        geocode_provider="yandex",
        geocode_confidence=0.9,
        last_seen_at=datetime.now(UTC),
    )
    session.add(topic)
    session.flush()

    post = Post(
        topic_id=topic.id,
        external_id="101",
        author="Ivan",
        posted_at_utc=datetime.now(UTC),
        content_text="Отличный клев",
        url="https://example.com/p/101",
    )
    session.add(post)
    session.commit()
    yield session
    session.close()
