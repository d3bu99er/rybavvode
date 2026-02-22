from datetime import datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.schemas import PostOut, TopicOut
from app.services.map_service import build_map, build_map_v2, parse_period
from app.services.repository import (
    count_posts_for_map,
    get_post,
    get_topic,
    list_posts,
    topic_activity_for_map,
    topic_posts_paginated,
    topics_for_map,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _is_preview_image_source(source_url: str) -> bool:
    path = urlparse(source_url or "").path.lower()
    return "/data/attachments/" in path


def _is_original_image_source(source_url: str) -> bool:
    path = urlparse(source_url or "").path.lower()
    return "/attachments/" in path and "/data/attachments/" not in path


def _post_images_for_ui(post) -> list[dict[str, str]]:
    image_attachments = sorted(
        (a for a in post.attachments if a.is_image and a.local_rel_path),
        key=lambda a: a.id,
    )
    if not image_attachments:
        return []

    preview_urls: list[str] = []
    original_urls: list[str] = []
    other_urls: list[str] = []

    for att in image_attachments:
        local_url = f"/media/attachments/{att.local_rel_path}"
        if _is_preview_image_source(att.source_url):
            preview_urls.append(local_url)
        elif _is_original_image_source(att.source_url):
            original_urls.append(local_url)
        else:
            other_urls.append(local_url)

    pairs: list[dict[str, str]] = []

    if preview_urls:
        for idx, preview in enumerate(preview_urls):
            href = original_urls[idx] if idx < len(original_urls) else preview
            pairs.append({"src": preview, "href": href})
        for idx in range(len(preview_urls), len(original_urls)):
            src = original_urls[idx]
            pairs.append({"src": src, "href": src})
    else:
        for src in original_urls:
            pairs.append({"src": src, "href": src})

    for src in other_urls:
        pairs.append({"src": src, "href": src})

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in pairs:
        key = (item["src"], item["href"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/api/posts", response_model=list[PostOut])
def api_posts(
    since: datetime | None = Query(default=None),
    has_geo: bool = Query(default=True),
    include_deleted: bool = Query(default=False),
    q: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_posts(
        db,
        since=since,
        has_geo=has_geo,
        include_deleted=include_deleted,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.get("/api/posts/{post_id}", response_model=PostOut)
def api_post(post_id: int, db: Session = Depends(get_db)):
    post = get_post(db, post_id)
    if not post:
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return post


@router.get("/api/topics/{topic_id}", response_model=TopicOut)
def api_topic(topic_id: int, db: Session = Depends(get_db)):
    topic = get_topic(db, topic_id)
    if not topic:
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return topic


@router.get("/api/topics/{topic_id}/messages")
def api_topic_messages(
    topic_id: int,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=15, ge=1, le=100),
    db: Session = Depends(get_db),
):
    topic = get_topic(db, topic_id)
    if not topic:
        return JSONResponse({"detail": "Not found"}, status_code=404)
    posts, total = topic_posts_paginated(db, topic_id=topic_id, page=page, per_page=per_page, include_deleted=False)
    total_pages = (total + per_page - 1) // per_page if total else 1
    items = []
    for post in posts:
        image_links = _post_images_for_ui(post)
        images = [item["src"] for item in image_links]
        items.append(
            {
                "id": post.id,
                "author": post.author,
                "posted_at_local": post.posted_at_utc.strftime("%d-%m-%Y %H:%M"),
                "content_text": post.content_text or "",
                "images": images,
                "image_links": image_links,
            }
        )
    return {
        "topic_id": topic_id,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "items": items,
    }


@router.get("/")
def home(
    request: Request,
    period: str = Query(default="7d"),
    q: str | None = Query(default=None),
    limit: int = Query(default=200, le=500),
    ui: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    since = parse_period(period)
    if ui == "legacy":
        use_v2 = False
    elif ui == "v2":
        use_v2 = True
    else:
        use_v2 = settings.map_ui_v2

    if use_v2:
        topic_rows = topic_activity_for_map(
            db,
            since=since,
            q=q,
            limit=limit,
            min_geo_confidence=settings.min_geo_confidence,
        )
        map_html = build_map_v2(topic_rows)
        topics_count = len(topic_rows)
    else:
        topics = topics_for_map(
            db,
            since=since,
            q=q,
            limit=limit,
            min_geo_confidence=settings.min_geo_confidence,
        )
        map_html = build_map(topics)
        topics_count = len(topics)

    posts_count = count_posts_for_map(
        db,
        since=since,
        q=q,
        min_geo_confidence=settings.min_geo_confidence,
    )
    return templates.TemplateResponse(
        "map.html",
        {
            "request": request,
            "map_html": map_html,
            "period": period,
            "q": q or "",
            "limit": limit,
            "topics_count": topics_count,
            "posts_count": posts_count,
            "ui_mode": "v2" if use_v2 else "legacy",
        },
    )
