from datetime import UTC, datetime

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import Post, Source, Topic


def get_or_create_source(db: Session, name: str, base_url: str) -> Source:
    source = db.execute(select(Source).where(Source.name == name)).scalar_one_or_none()
    if source:
        return source
    source = Source(name=name, base_url=base_url)
    db.add(source)
    db.flush()
    return source


def upsert_topic(db: Session, source_id: int, external_id: str, title: str, url: str, place_name: str) -> Topic:
    topic = db.execute(select(Topic).where(and_(Topic.source_id == source_id, Topic.external_id == external_id))).scalar_one_or_none()
    now = datetime.now(UTC)
    if topic:
        topic.title = title
        topic.url = url
        topic.place_name = place_name
        topic.last_seen_at = now
        db.flush()
        return topic
    topic = Topic(
        source_id=source_id,
        external_id=external_id,
        title=title,
        url=url,
        place_name=place_name,
        last_seen_at=now,
    )
    db.add(topic)
    db.flush()
    return topic


def upsert_post(
    db: Session,
    topic_id: int,
    external_id: str,
    author: str,
    posted_at_utc: datetime,
    content_text: str,
    url: str,
) -> Post:
    post = db.execute(select(Post).where(and_(Post.topic_id == topic_id, Post.external_id == external_id))).scalar_one_or_none()
    if post:
        post.author = author
        post.posted_at_utc = posted_at_utc
        post.content_text = content_text
        post.url = url
        db.flush()
        return post
    post = Post(
        topic_id=topic_id,
        external_id=external_id,
        author=author,
        posted_at_utc=posted_at_utc,
        content_text=content_text,
        url=url,
    )
    db.add(post)
    db.flush()
    return post


def list_posts(
    db: Session,
    since: datetime | None = None,
    has_geo: bool = True,
    include_deleted: bool = False,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    stmt: Select = select(Post).join(Post.topic).options(joinedload(Post.topic)).order_by(Post.posted_at_utc.desc())
    conditions = []
    if since:
        conditions.append(Post.posted_at_utc >= since)
    if has_geo:
        conditions.append(Topic.geocoded_lat.is_not(None))
        conditions.append(Topic.geocoded_lon.is_not(None))
    if not include_deleted:
        conditions.append(Post.is_deleted.is_(False))
    if q:
        like = f"%{q}%"
        conditions.append(or_(Post.content_text.ilike(like), Post.author.ilike(like), Topic.title.ilike(like)))
    if conditions:
        stmt = stmt.where(and_(*conditions))
    return db.execute(stmt.limit(limit).offset(offset)).scalars().unique().all()


def get_post(db: Session, post_id: int) -> Post | None:
    return db.execute(select(Post).where(Post.id == post_id).options(joinedload(Post.topic))).scalar_one_or_none()


def get_topic(db: Session, topic_id: int) -> Topic | None:
    return db.execute(select(Topic).where(Topic.id == topic_id)).scalar_one_or_none()


def list_topics(db: Session, q: str | None = None, limit: int = 200, offset: int = 0):
    stmt: Select = select(Topic).order_by(Topic.last_seen_at.desc())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Topic.title.ilike(like), Topic.place_name.ilike(like)))
    return db.execute(stmt.limit(limit).offset(offset)).scalars().all()


def update_topic_coordinates(
    db: Session,
    topic_id: int,
    lat: float,
    lon: float,
    confidence: float | None = None,
    provider: str = "manual",
) -> bool:
    topic = get_topic(db, topic_id)
    if not topic:
        return False
    topic.geocoded_lat = lat
    topic.geocoded_lon = lon
    topic.geocode_confidence = confidence
    topic.geocode_provider = provider
    topic.geocode_updated_at = datetime.now(UTC)
    db.flush()
    return True


def soft_delete_post(db: Session, post_id: int) -> bool:
    post = get_post(db, post_id)
    if not post:
        return False
    post.is_deleted = True
    post.deleted_at = datetime.now(UTC)
    db.flush()
    return True


def restore_post(db: Session, post_id: int) -> bool:
    post = get_post(db, post_id)
    if not post:
        return False
    post.is_deleted = False
    post.deleted_at = None
    db.flush()
    return True


def posts_for_map(db: Session, since: datetime | None, q: str | None, limit: int, min_geo_confidence: float):
    stmt = (
        select(Post)
        .join(Post.topic)
        .options(joinedload(Post.topic))
        .where(Post.is_deleted.is_(False))
        .where(Topic.geocoded_lat.is_not(None), Topic.geocoded_lon.is_not(None))
        .where(func.coalesce(Topic.geocode_confidence, 0.0) >= min_geo_confidence)
        .order_by(Post.posted_at_utc.desc())
    )
    if since:
        stmt = stmt.where(Post.posted_at_utc >= since)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Post.content_text.ilike(like), Post.author.ilike(like), Topic.title.ilike(like)))
    return db.execute(stmt.limit(limit)).scalars().unique().all()


def topics_for_map(
    db: Session,
    since: datetime | None,
    q: str | None,
    limit: int,
    min_geo_confidence: float,
    posts_per_topic: int = 10,
):
    topic_stmt: Select = (
        select(Topic)
        .where(Topic.geocoded_lat.is_not(None), Topic.geocoded_lon.is_not(None))
        .where(func.coalesce(Topic.geocode_confidence, 0.0) >= min_geo_confidence)
        .order_by(Topic.last_seen_at.desc())
    )
    if q:
        like = f"%{q}%"
        topic_stmt = topic_stmt.where(or_(Topic.title.ilike(like), Topic.place_name.ilike(like)))
    topics = db.execute(topic_stmt.limit(limit)).scalars().all()

    result: list[tuple[Topic, list[Post]]] = []
    for topic in topics:
        posts_stmt: Select = (
            select(Post)
            .where(Post.topic_id == topic.id, Post.is_deleted.is_(False))
            .order_by(Post.posted_at_utc.desc())
            .limit(posts_per_topic)
        )
        if since:
            posts_stmt = posts_stmt.where(Post.posted_at_utc >= since)
        if q:
            like = f"%{q}%"
            posts_stmt = posts_stmt.where(or_(Post.content_text.ilike(like), Post.author.ilike(like)))

        posts = db.execute(posts_stmt).scalars().all()
        if posts:
            result.append((topic, posts))
    return result
