"""Frontend HTML page routes.

Serves Jinja2 templates for the web UI. Authentication state is derived from
the ``arcus_session`` cookie set by ``/auth/login``.
"""

import logging

from fastapi import APIRouter, Cookie, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.utils.deps import get_current_user_optional

logger = logging.getLogger(__name__)

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory="api/templates")


def _render(request: Request, template: str, **ctx):
    return templates.TemplateResponse(request, template, ctx)


# ---------------------------------------------------------------------------
# Root redirect
# ---------------------------------------------------------------------------


@router.get("/")
async def root(
    arcus_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Redirect to dashboard if logged in, else to login (or setup if no admin)."""
    from sqlalchemy import func, select

    from api.models import User

    if arcus_session:
        result = await db.execute(
            select(func.count()).select_from(User).where(User.role == "admin")
        )
        if result.scalar_one() == 0:
            return RedirectResponse("/setup", status_code=302)
        return RedirectResponse("/dashboard", status_code=302)

    result = await db.execute(
        select(func.count()).select_from(User).where(User.role == "admin")
    )
    if result.scalar_one() == 0:
        return RedirectResponse("/setup", status_code=302)
    return RedirectResponse("/login", status_code=302)


# ---------------------------------------------------------------------------
# Setup page
# ---------------------------------------------------------------------------


@router.get("/setup")
async def setup_page(request: Request, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import func, select

    from api.models import User

    result = await db.execute(
        select(func.count()).select_from(User).where(User.role == "admin")
    )
    if result.scalar_one() > 0:
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
    user = await get_current_user_optional(session_token=arcus_session, db=db)
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
    user = await get_current_user_optional(session_token=arcus_session, db=db)
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
    user = await get_current_user_optional(session_token=arcus_session, db=db)
    if user is None:
        return RedirectResponse("/login", status_code=302)
    if user.role != "admin":
        return RedirectResponse("/dashboard", status_code=302)
    return _render(request, "admin.html", user=user)
