"""Frontend HTML page routes.

Serves Jinja2 templates for the web UI. Authentication state is derived from
the ``arcus_session`` cookie set by ``/auth/login``.
"""

import logging
import uuid

from fastapi import APIRouter, Cookie, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import User
from api.utils.deps import get_current_user_optional

logger = logging.getLogger(__name__)

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory="api/templates")


def _render(request: Request, template: str, **ctx):
    return templates.TemplateResponse(request, template, ctx)


async def _admin_exists(db: AsyncSession) -> bool:
    """Return True if at least one admin user exists."""
    result = await db.execute(select(func.count()).select_from(User).where(User.role == "admin"))
    return result.scalar_one() > 0


# ---------------------------------------------------------------------------
# Root redirect
# ---------------------------------------------------------------------------


@router.get("/")
async def root(
    arcus_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Redirect to dashboard if logged in, else to login (or setup if no admin)."""
    if not await _admin_exists(db):
        return RedirectResponse("/setup", status_code=302)
    if arcus_session:
        return RedirectResponse("/dashboard", status_code=302)
    return RedirectResponse("/login", status_code=302)


# ---------------------------------------------------------------------------
# Setup page
# ---------------------------------------------------------------------------


@router.get("/setup")
async def setup_page(request: Request, db: AsyncSession = Depends(get_db)):
    if await _admin_exists(db):
        return RedirectResponse("/login", status_code=302)
    return _render(request, "setup.html")


# ---------------------------------------------------------------------------
# Login page
# ---------------------------------------------------------------------------


@router.get("/login")
async def login_page(request: Request, setup: str = ""):
    return _render(request, "login.html", setup_done=setup == "1")


# ---------------------------------------------------------------------------
# Change-password page
# ---------------------------------------------------------------------------


@router.get("/change-password")
async def change_password_page(
    request: Request,
    arcus_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user_optional(credentials=None, session_token=arcus_session, db=db)
    if user is None:
        return RedirectResponse("/login", status_code=302)
    return _render(request, "change_password.html", user=user, must_change=user.must_change_password)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get("/dashboard")
async def dashboard_page(
    request: Request,
    changed: str = "",
    arcus_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user_optional(credentials=None, session_token=arcus_session, db=db)
    if user is None:
        return RedirectResponse("/login", status_code=302)
    if user.must_change_password:
        return RedirectResponse("/change-password", status_code=302)
    flash = "Password updated successfully." if changed == "1" else None
    return _render(request, "dashboard.html", user=user, flash=flash, flash_type="success")


# ---------------------------------------------------------------------------
# Admin panel
# ---------------------------------------------------------------------------


@router.get("/admin")
async def admin_page(
    request: Request,
    arcus_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user_optional(credentials=None, session_token=arcus_session, db=db)
    if user is None:
        return RedirectResponse("/login", status_code=302)
    if user.role != "admin":
        return RedirectResponse("/dashboard", status_code=302)
    return _render(request, "admin.html", user=user, main_class="max-w-6xl")


@router.get("/admin/users/{user_id}/manage")
async def admin_user_page(
    user_id: str,
    request: Request,
    arcus_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user_optional(credentials=None, session_token=arcus_session, db=db)
    if user is None:
        return RedirectResponse("/login", status_code=302)
    if user.role != "admin":
        return RedirectResponse("/dashboard", status_code=302)

    try:
        target_id = uuid.UUID(user_id)
    except ValueError:
        return RedirectResponse("/admin", status_code=302)

    target_user = await db.get(User, target_id)
    if target_user is None:
        return RedirectResponse("/admin", status_code=302)

    return _render(request, "admin_user.html", user=user, target_user=target_user, main_class="max-w-6xl")
