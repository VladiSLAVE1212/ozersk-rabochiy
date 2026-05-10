"""Озёрск Рабочий — простая FastAPI-газета."""
from __future__ import annotations

import os
import re
import secrets
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .auth import authenticate, create_user, current_user, hash_password
from .content import make_summary, render_body, slugify
from .db import get_conn, init_db

BASE_DIR = Path(__file__).resolve().parent

# Pick uploads dir: explicit env var > /data/uploads (fly volume) > local static path
def _resolve_uploads_dir() -> Path:
    explicit = os.environ.get("OZERSK_UPLOADS")
    if explicit:
        return Path(explicit).resolve()
    fly_vol = Path("/data")
    if fly_vol.is_dir() and os.access(fly_vol, os.W_OK):
        return fly_vol / "uploads"
    return BASE_DIR / "static" / "uploads"


UPLOADS_DIR = _resolve_uploads_dir()
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MiB

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

SECRET_KEY = os.environ.get("OZERSK_SECRET", secrets.token_hex(32))
SITE_NAME = "Озёрск Рабочий"
TAGLINE = "Орган трудящихся города Озёрска"

app = FastAPI(title=SITE_NAME, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=60 * 60 * 24 * 14)
app.mount("/static/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.on_event("startup")
def _startup() -> None:
    init_db()
    _ensure_default_admin()


def _ensure_default_admin() -> None:
    """Create a default admin if none exists, so first-run works."""
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        if row["c"] > 0:
            return
    username = os.environ.get("OZERSK_ADMIN_USER", "admin")
    password = os.environ.get("OZERSK_ADMIN_PASSWORD", "admin")
    create_user(username, "Главный редактор", password, is_admin=True)


# ---------- helpers ----------

def _all_categories():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM categories ORDER BY name").fetchall()


def _category_by_slug(slug: str):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM categories WHERE slug = ?", (slug,)).fetchone()


def _category_by_id(cat_id: Optional[int]):
    if cat_id is None:
        return None
    with get_conn() as conn:
        return conn.execute("SELECT * FROM categories WHERE id = ?", (cat_id,)).fetchone()


def _unique_slug(base: str, exclude_id: Optional[int] = None) -> str:
    slug = slugify(base)
    candidate = slug
    i = 2
    with get_conn() as conn:
        while True:
            if exclude_id is None:
                row = conn.execute("SELECT id FROM posts WHERE slug = ?", (candidate,)).fetchone()
            else:
                row = conn.execute(
                    "SELECT id FROM posts WHERE slug = ? AND id <> ?",
                    (candidate, exclude_id),
                ).fetchone()
            if row is None:
                return candidate
            candidate = f"{slug}-{i}"
            i += 1


def _require_user(request: Request):
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})
    return user


def _can_edit(user, post) -> bool:
    if user is None:
        return False
    if user["is_admin"]:
        return True
    return post["author_id"] == user["id"]


def _ctx(request: Request, **extra):
    """Build base template context."""
    return {
        "request": request,
        "site_name": SITE_NAME,
        "tagline": TAGLINE,
        "categories": _all_categories(),
        "user": current_user(request),
        **extra,
    }


def render(request: Request, template: str, *, status_code: int = 200, **extra):
    return templates.TemplateResponse(
        request, template, _ctx(request, **extra), status_code=status_code
    )


def _fetch_posts(
    *,
    category_id: Optional[int] = None,
    query: Optional[str] = None,
    limit: int = 30,
    offset: int = 0,
) -> list:
    with get_conn() as conn:
        if query:
            # FTS5 query — escape the user input as a phrase to avoid syntax errors
            terms = [t for t in re.split(r"\s+", query.strip()) if t]
            if not terms:
                return []
            fts_q = " ".join(f'"{t}"' for t in terms)
            sql = (
                "SELECT p.*, c.slug AS category_slug, c.name AS category_name, "
                "       u.display_name AS author_name "
                "FROM posts_fts f "
                "JOIN posts p ON p.id = f.rowid "
                "LEFT JOIN categories c ON c.id = p.category_id "
                "LEFT JOIN users u ON u.id = p.author_id "
                "WHERE p.published = 1 AND posts_fts MATCH ? "
            )
            params: list = [fts_q]
            if category_id is not None:
                sql += "AND p.category_id = ? "
                params.append(category_id)
            sql += "ORDER BY p.created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            return conn.execute(sql, params).fetchall()

        sql = (
            "SELECT p.*, c.slug AS category_slug, c.name AS category_name, "
            "       u.display_name AS author_name "
            "FROM posts p "
            "LEFT JOIN categories c ON c.id = p.category_id "
            "LEFT JOIN users u ON u.id = p.author_id "
            "WHERE p.published = 1 "
        )
        params = []
        if category_id is not None:
            sql += "AND p.category_id = ? "
            params.append(category_id)
        sql += "ORDER BY p.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return conn.execute(sql, params).fetchall()


# ---------- public ----------

@app.get("/", response_class=HTMLResponse)
def home(request: Request, q: Optional[str] = None, cat: Optional[str] = None):
    category = _category_by_slug(cat) if cat else None
    posts = _fetch_posts(
        category_id=category["id"] if category else None,
        query=q,
        limit=30,
    )
    return render(
        request,
        "index.html",
        posts=posts,
        current_category=category,
        query=q or "",
    )


@app.get("/category/{slug}", response_class=HTMLResponse)
def category_view(request: Request, slug: str):
    category = _category_by_slug(slug)
    if category is None:
        raise HTTPException(404)
    posts = _fetch_posts(category_id=category["id"], limit=50)
    return render(request, "index.html", posts=posts, current_category=category, query="")


@app.get("/post/{slug}", response_class=HTMLResponse)
def post_view(request: Request, slug: str):
    with get_conn() as conn:
        post = conn.execute(
            "SELECT p.*, c.slug AS category_slug, c.name AS category_name, "
            "       u.display_name AS author_name "
            "FROM posts p "
            "LEFT JOIN categories c ON c.id = p.category_id "
            "LEFT JOIN users u ON u.id = p.author_id "
            "WHERE p.slug = ? AND p.published = 1",
            (slug,),
        ).fetchone()
    if post is None:
        raise HTTPException(404)
    body_html = render_body(post["body"])
    return render(request, "post.html", post=post, body_html=body_html)


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ---------- admin ----------

@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_form(request: Request, error: Optional[str] = None):
    if current_user(request) is not None:
        return RedirectResponse("/admin", status_code=302)
    return render(request, "admin/login.html", error=error)


@app.post("/admin/login")
def admin_login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = authenticate(username, password)
    if user is None:
        return RedirectResponse(
            "/admin/login?error=" + "Неверный логин или пароль", status_code=302
        )
    request.session["user_id"] = user["id"]
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/logout")
def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=302)


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, user=Depends(_require_user)):
    with get_conn() as conn:
        if user["is_admin"]:
            posts = conn.execute(
                "SELECT p.*, c.name AS category_name, u.display_name AS author_name "
                "FROM posts p "
                "LEFT JOIN categories c ON c.id = p.category_id "
                "LEFT JOIN users u ON u.id = p.author_id "
                "ORDER BY p.created_at DESC"
            ).fetchall()
        else:
            posts = conn.execute(
                "SELECT p.*, c.name AS category_name, u.display_name AS author_name "
                "FROM posts p "
                "LEFT JOIN categories c ON c.id = p.category_id "
                "LEFT JOIN users u ON u.id = p.author_id "
                "WHERE p.author_id = ? "
                "ORDER BY p.created_at DESC",
                (user["id"],),
            ).fetchall()
    return render(request, "admin/dashboard.html", posts=posts)


@app.get("/admin/posts/new", response_class=HTMLResponse)
def admin_post_new(request: Request, user=Depends(_require_user)):
    return render(request, "admin/edit.html", post=None, error=None)


@app.post("/admin/posts/new")
def admin_post_create(
    request: Request,
    title: str = Form(...),
    category_id: Optional[int] = Form(None),
    cover_url: str = Form(""),
    body: str = Form(...),
    summary: str = Form(""),
    published: Optional[str] = Form(None),
    user=Depends(_require_user),
):
    title = (title or "").strip()
    body = (body or "").strip()
    if not title or not body:
        return render(
            request,
            "admin/edit.html",
            status_code=400,
            post=None,
            error="Заголовок и текст обязательны",
        )
    slug = _unique_slug(title)
    rendered = render_body(body)
    final_summary = (summary or "").strip() or make_summary(rendered)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO posts (slug, title, summary, body, cover_url, category_id, "
            "author_id, published) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                slug,
                title,
                final_summary,
                body,
                (cover_url or "").strip(),
                category_id if category_id else None,
                user["id"],
                1 if published else 0,
            ),
        )
    return RedirectResponse(f"/post/{slug}", status_code=302)


@app.get("/admin/posts/{post_id}/edit", response_class=HTMLResponse)
def admin_post_edit(request: Request, post_id: int, user=Depends(_require_user)):
    with get_conn() as conn:
        post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if post is None:
        raise HTTPException(404)
    if not _can_edit(user, post):
        raise HTTPException(403)
    return render(request, "admin/edit.html", post=post, error=None)


@app.post("/admin/posts/{post_id}/edit")
def admin_post_update(
    request: Request,
    post_id: int,
    title: str = Form(...),
    category_id: Optional[int] = Form(None),
    cover_url: str = Form(""),
    body: str = Form(...),
    summary: str = Form(""),
    published: Optional[str] = Form(None),
    user=Depends(_require_user),
):
    with get_conn() as conn:
        post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if post is None:
        raise HTTPException(404)
    if not _can_edit(user, post):
        raise HTTPException(403)
    title = (title or "").strip()
    body = (body or "").strip()
    if not title or not body:
        return render(
            request,
            "admin/edit.html",
            status_code=400,
            post=post,
            error="Заголовок и текст обязательны",
        )
    slug = post["slug"]
    if title.lower() != post["title"].lower():
        slug = _unique_slug(title, exclude_id=post_id)
    rendered = render_body(body)
    final_summary = (summary or "").strip() or make_summary(rendered)
    with get_conn() as conn:
        conn.execute(
            "UPDATE posts SET title=?, slug=?, summary=?, body=?, cover_url=?, "
            "category_id=?, published=?, updated_at=datetime('now') "
            "WHERE id=?",
            (
                title,
                slug,
                final_summary,
                body,
                (cover_url or "").strip(),
                category_id if category_id else None,
                1 if published else 0,
                post_id,
            ),
        )
    return RedirectResponse(f"/post/{slug}", status_code=302)


@app.post("/admin/posts/{post_id}/delete")
def admin_post_delete(request: Request, post_id: int, user=Depends(_require_user)):
    with get_conn() as conn:
        post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        if post is None:
            raise HTTPException(404)
        if not _can_edit(user, post):
            raise HTTPException(403)
        conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    return RedirectResponse("/admin", status_code=302)


# ---------- uploads ----------

@app.post("/admin/upload")
async def admin_upload(
    request: Request,
    file: UploadFile = File(...),
    user=Depends(_require_user),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_IMAGE_EXTS:
        return JSONResponse({"error": "Недопустимый формат файла"}, status_code=400)
    name = f"{secrets.token_hex(8)}{suffix}"
    dest = UPLOADS_DIR / name
    size = 0
    with dest.open("wb") as out:
        while True:
            chunk = await file.read(64 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                out.close()
                dest.unlink(missing_ok=True)
                return JSONResponse({"error": "Файл слишком большой (макс 5 МБ)"}, status_code=400)
            out.write(chunk)
    url = f"/static/uploads/{name}"
    return {"url": url}


# ---------- admin: users (admin-only) ----------

@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request, user=Depends(_require_user)):
    if not user["is_admin"]:
        raise HTTPException(403)
    with get_conn() as conn:
        users = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    return render(request, "admin/users.html", users=users, error=None, ok=None)


@app.post("/admin/users")
def admin_users_create(
    request: Request,
    username: str = Form(...),
    display_name: str = Form(""),
    password: str = Form(...),
    is_admin: Optional[str] = Form(None),
    user=Depends(_require_user),
):
    if not user["is_admin"]:
        raise HTTPException(403)
    username = (username or "").strip()
    if not username or not password:
        with get_conn() as conn:
            users = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        return render(
            request,
            "admin/users.html",
            status_code=400,
            users=users,
            error="Логин и пароль обязательны",
            ok=None,
        )
    try:
        create_user(username, display_name or username, password, is_admin=bool(is_admin))
    except Exception as exc:  # noqa: BLE001
        with get_conn() as conn:
            users = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        return render(
            request,
            "admin/users.html",
            status_code=400,
            users=users,
            error=f"Ошибка: {exc}",
            ok=None,
        )
    return RedirectResponse("/admin/users", status_code=302)


@app.post("/admin/users/{user_id}/password")
def admin_user_set_password(
    request: Request,
    user_id: int,
    password: str = Form(...),
    user=Depends(_require_user),
):
    if not user["is_admin"]:
        raise HTTPException(403)
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(password), user_id),
        )
    return RedirectResponse("/admin/users", status_code=302)


@app.post("/admin/users/{user_id}/delete")
def admin_user_delete(request: Request, user_id: int, user=Depends(_require_user)):
    if not user["is_admin"]:
        raise HTTPException(403)
    if user_id == user["id"]:
        raise HTTPException(400, "Нельзя удалить самого себя")
    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return RedirectResponse("/admin/users", status_code=302)


# ---------- error handlers ----------

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 302 and "Location" in (exc.headers or {}):
        return RedirectResponse(exc.headers["Location"], status_code=302)
    if exc.status_code == 404:
        return render(request, "404.html", status_code=404)
    if exc.status_code == 403:
        return render(request, "403.html", status_code=403)
    return HTMLResponse(f"<h1>{exc.status_code}</h1><p>{exc.detail}</p>", status_code=exc.status_code)
