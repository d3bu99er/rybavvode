from datetime import UTC, datetime

from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import Post, PostAttachment, Source, Topic


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


def upsert_post_attachment(
    db: Session,
    post_id: int,
    source_url: str,
    file_name: str,
    is_image: bool,
    local_rel_path: str | None = None,
    mime_type: str | None = None,
    size_bytes: int | None = None,
) -> PostAttachment:
    attachment = db.execute(
        select(PostAttachment).where(and_(PostAttachment.post_id == post_id, PostAttachment.source_url == source_url))
    ).scalar_one_or_none()
    if attachment:
        attachment.file_name = file_name
        attachment.is_image = is_image
        if local_rel_path is not None:
            attachment.local_rel_path = local_rel_path
        if mime_type is not None:
            attachment.mime_type = mime_type
        if size_bytes is not None:
            attachment.size_bytes = size_bytes
        db.flush()
        return attachment

    attachment = PostAttachment(
        post_id=post_id,
        source_url=source_url,
        file_name=file_name,
        is_image=is_image,
        local_rel_path=local_rel_path,
        mime_type=mime_type,
        size_bytes=size_bytes,
    )
    db.add(attachment)
    db.flush()
    return attachment


def list_attachments(
    db: Session,
    q: str | None = None,
    only_missing: bool = False,
    limit: int = 200,
    offset: int = 0,
):
    stmt: Select = (
        select(PostAttachment)
        .join(PostAttachment.post)
        .join(Post.topic)
        .options(joinedload(PostAttachment.post).joinedload(Post.topic))
        .order_by(Post.posted_at_utc.desc())
    )
    if only_missing:
        stmt = stmt.where(PostAttachment.local_rel_path.is_(None))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Post.author.ilike(like),
                Post.content_text.ilike(like),
                Topic.title.ilike(like),
                PostAttachment.file_name.ilike(like),
            )
        )
    return db.execute(stmt.limit(limit).offset(offset)).scalars().unique().all()


def attachments_for_post(db: Session, post_id: int):
    stmt: Select = (
        select(PostAttachment)
        .where(PostAttachment.post_id == post_id)
        .order_by(PostAttachment.id.asc())
    )
    return db.execute(stmt).scalars().all()


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
):
    post_exists_stmt = select(Post.id).where(Post.topic_id == Topic.id, Post.is_deleted.is_(False))
    if since:
        post_exists_stmt = post_exists_stmt.where(Post.posted_at_utc >= since)
    if q:
        like = f"%{q}%"
        post_exists_stmt = post_exists_stmt.where(or_(Post.content_text.ilike(like), Post.author.ilike(like)))

    topic_stmt: Select = (
        select(Topic)
        .where(Topic.geocoded_lat.is_not(None), Topic.geocoded_lon.is_not(None))
        .where(func.coalesce(Topic.geocode_confidence, 0.0) >= min_geo_confidence)
        .where(exists(post_exists_stmt))
        .order_by(Topic.last_seen_at.desc())
    )
    if q:
        like = f"%{q}%"
        topic_stmt = topic_stmt.where(or_(Topic.title.ilike(like), Topic.place_name.ilike(like)))
    return db.execute(topic_stmt.limit(limit)).scalars().all()


def topic_posts_paginated(
    db: Session,
    topic_id: int,
    page: int = 1,
    per_page: int = 15,
    include_deleted: bool = False,
):
    base_stmt: Select = select(Post).where(Post.topic_id == topic_id)
    if not include_deleted:
        base_stmt = base_stmt.where(Post.is_deleted.is_(False))

    total = db.execute(select(func.count()).select_from(base_stmt.subquery())).scalar_one()
    page = max(1, page)
    per_page = max(1, min(per_page, 100))
    offset = (page - 1) * per_page
    items_stmt = (
        base_stmt.options(joinedload(Post.attachments))
        .order_by(Post.posted_at_utc.desc())
        .offset(offset)
        .limit(per_page)
    )
    items = db.execute(items_stmt).scalars().unique().all()
    return items, total


def count_posts_for_map(
    db: Session,
    since: datetime | None,
    q: str | None,
    min_geo_confidence: float,
) -> int:
    stmt: Select = (
        select(func.count(Post.id))
        .join(Post.topic)
        .where(Post.is_deleted.is_(False))
        .where(Topic.geocoded_lat.is_not(None), Topic.geocoded_lon.is_not(None))
        .where(func.coalesce(Topic.geocode_confidence, 0.0) >= min_geo_confidence)
    )
    if since:
        stmt = stmt.where(Post.posted_at_utc >= since)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Post.content_text.ilike(like), Post.author.ilike(like), Topic.title.ilike(like)))
    return int(db.execute(stmt).scalar_one())
