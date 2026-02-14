from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.schemas import PostOut, TopicOut
from app.services.map_service import build_map, parse_period
from app.services.repository import get_post, get_topic, list_posts, posts_for_map

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


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


@router.get("/")
def home(
    request: Request,
    period: str = Query(default="7d"),
    q: str | None = Query(default=None),
    limit: int = Query(default=200, le=500),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    since = parse_period(period)
    posts = posts_for_map(db, since=since, q=q, limit=limit, min_geo_confidence=settings.min_geo_confidence)
    map_html = build_map(posts)
    return templates.TemplateResponse(
        "map.html",
        {
            "request": request,
            "map_html": map_html,
            "period": period,
            "q": q or "",
            "limit": limit,
            "posts_count": len(posts),
        },
    )
