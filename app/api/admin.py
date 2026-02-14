from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import SESSION_KEY, verify_admin_credentials
from app.services.repository import list_posts, restore_post, soft_delete_post

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="app/templates")


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
