"""Authentication routes.

Endpoints
---------
GET  /setup           – check if setup is needed (JSON)
POST /auth/setup      – create the first admin account
POST /auth/login      – exchange credentials for a JWT
POST /auth/logout     – clear the session cookie
GET  /auth/me         – return the current user
POST /auth/change-password – change password (required on first login)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import User
from api.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    SetupRequest,
    TokenResponse,
    UserResponse,
)
from api.utils.auth import (
    create_access_token,
    hash_password,
    verify_password,
)
from api.utils.deps import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])


# ---------------------------------------------------------------------------
# Setup check
# ---------------------------------------------------------------------------


@router.get("/auth/setup-status", summary="Check whether initial setup is required")
async def setup_status(db: AsyncSession = Depends(get_db)):
    """Returns ``{"needed": true}`` when no admin account exists."""
    result = await db.execute(select(func.count()).select_from(User).where(User.role == "admin"))
    count = result.scalar_one()
    return {"needed": count == 0}


# ---------------------------------------------------------------------------
# Initial admin creation
# ---------------------------------------------------------------------------


@router.post(
    "/auth/setup",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create the first admin account",
)
async def create_admin_setup(payload: SetupRequest, db: AsyncSession = Depends(get_db)):
    """One-time endpoint to bootstrap the admin account.

    Fails with 409 if an admin already exists.
    """
    result = await db.execute(select(func.count()).select_from(User).where(User.role == "admin"))
    if result.scalar_one() > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Admin account already exists.",
        )

    user = User(
        email=payload.email,
        role="admin",
        password_hash=hash_password(payload.password),
        must_change_password=False,
    )
    db.add(user)
    try:
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with that e-mail address already exists.",
        ) from None

    logger.info("Admin account created: %s", user.email)
    return user


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@router.post("/auth/login", response_model=TokenResponse, summary="Log in and receive a JWT")
async def login(payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    """Authenticate with email + password; sets an HTTP-only session cookie."""
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if user is None or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    if not user.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated.",
        )

    token = create_access_token({"sub": str(user.id), "role": user.role})

    # Set HTTP-only cookie for browser clients
    response.set_cookie(
        key="arcus_session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24,  # 24 h
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        must_change_password=user.must_change_password,
    )


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Log out")
async def logout(response: Response):
    """Clear the session cookie."""
    response.delete_cookie(key="arcus_session")


# ---------------------------------------------------------------------------
# Me
# ---------------------------------------------------------------------------


@router.get("/auth/me", response_model=UserResponse, summary="Get the authenticated user")
async def me(user: User = Depends(get_current_user)):
    return user


# ---------------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------------


@router.post(
    "/auth/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change the current user's password",
)
async def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change the current user's password.

    If the user logged in with a temp password the ``must_change_password``
    flag is cleared after a successful change.
    """
    if not user.password_hash or not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect.",
        )

    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must differ from the current password.",
        )

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    await db.commit()
    logger.info("User %s changed their password", user.id)
