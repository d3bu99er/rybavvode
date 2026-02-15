from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import SESSION_KEY, verify_admin_credentials
from app.services.repository import (
    get_post,
    list_attachments,
    list_posts,
    list_topics,
    restore_post,
    soft_delete_post,
    update_topic_coordinates,
)
from app.services.sync_service import SyncService

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="app/templates")
sync_service = SyncService()


def _is_auth(request: Request) -> bool:
    return bool(request.session.get(SESSION_KEY))


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request, "error": ""})


@router.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if verify_admin_credentials(username, password):
        request.session[SESSION_KEY] = True
        return RedirectResponse(url="/admin/posts", status_code=303)
    return templates.TemplateResponse(
        "admin_login.html",
        {"request": request, "error": "Неверные учетные данные"},
        status_code=401,
    )


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)


@router.get("/posts")
def admin_posts(
    request: Request,
    q: str | None = None,
    include_deleted: bool = True,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    if not _is_auth(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    posts = list_posts(
        db,
        since=None,
        has_geo=False,
        include_deleted=include_deleted,
        q=q,
        limit=min(limit, 500),
        offset=0,
    )
    return templates.TemplateResponse(
        "admin_posts.html",
        {
            "request": request,
            "posts": posts,
            "q": q or "",
            "include_deleted": include_deleted,
        },
    )


@router.get("/topics")
def admin_topics(
    request: Request,
    q: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    if not _is_auth(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    topics = list_topics(db, q=q, limit=min(limit, 500), offset=0)
    return templates.TemplateResponse(
        "admin_topics.html",
        {
            "request": request,
            "topics": topics,
            "q": q or "",
        },
    )


@router.get("/attachments")
def admin_attachments(
    request: Request,
    q: str | None = None,
    only_missing: bool = False,
    limit: int = 300,
    db: Session = Depends(get_db),
):
    if not _is_auth(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    rows = list_attachments(db, q=q, only_missing=only_missing, limit=min(limit, 500), offset=0)
    return templates.TemplateResponse(
        "admin_attachments.html",
        {
            "request": request,
            "rows": rows,
            "q": q or "",
            "only_missing": only_missing,
        },
    )


@router.post("/posts/{post_id}/attachments/retry")
async def retry_post_attachments_handler(post_id: int, request: Request, db: Session = Depends(get_db)):
    if not _is_auth(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    post = get_post(db, post_id)
    if not post:
        return RedirectResponse(url="/admin/attachments", status_code=303)
    await sync_service.retry_post_attachments(db, post, force=False)
    db.commit()
    return RedirectResponse(url="/admin/attachments", status_code=303)


@router.post("/topics/{topic_id}/coords")
def update_topic_coords_handler(
    topic_id: int,
    request: Request,
    lat: float = Form(...),
    lon: float = Form(...),
    confidence: float = Form(1.0),
    db: Session = Depends(get_db),
):
    if not _is_auth(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    if lat < -90 or lat > 90 or lon < -180 or lon > 180:
        return RedirectResponse(url="/admin/topics?error=invalid_coords", status_code=303)
    conf = max(0.0, min(1.0, confidence))
    if update_topic_coordinates(db, topic_id, lat=lat, lon=lon, confidence=conf, provider="manual"):
        db.commit()
    return RedirectResponse(url="/admin/topics", status_code=303)


@router.post("/posts/{post_id}/delete")
def delete_post(post_id: int, request: Request, db: Session = Depends(get_db)):
    if not _is_auth(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    if soft_delete_post(db, post_id):
        db.commit()
    return RedirectResponse(url="/admin/posts", status_code=303)


@router.post("/posts/{post_id}/restore")
def restore_post_handler(post_id: int, request: Request, db: Session = Depends(get_db)):
    if not _is_auth(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    if restore_post(db, post_id):
        db.commit()
    return RedirectResponse(url="/admin/posts", status_code=303)
