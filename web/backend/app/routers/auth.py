"""Authentication endpoints: login, me, refresh, change-password."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..config import get_settings
from ..deps import get_current_user
from ..models import NamedWorkspace, Org, Role, User
from ..schemas import ChangePasswordRequest, LoginRequest, NameLoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserOut
from ..security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/options")
async def auth_options():
    return {"name_login_enabled": get_settings().name_login_enabled}


def _profile_tokens(user):
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "该使用者已停用，请联系管理员")
    if user.role != Role.lawyer:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "此账号不能通过姓名进入")
    return TokenResponse(access_token=create_access_token(user.id, {"org": user.org_id, "role": user.role.value, "profile": True}),
                         refresh_token=create_refresh_token(user.id))


@router.post("/name-login", response_model=TokenResponse)
async def name_login(body: NameLoginRequest, db: AsyncSession = Depends(get_db)):
    if not get_settings().name_login_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "此工作站尚未启用姓名工作空间")
    key = body.name.casefold()
    if key in {"admin", "administrator", "管理员"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "管理员请使用工作站管理入口")
    async def lookup():
        return (await db.execute(select(User).join(NamedWorkspace, NamedWorkspace.user_id == User.id)
                                 .where(NamedWorkspace.name_key == key))).scalar_one_or_none()
    user = await lookup()
    if user:
        return _profile_tokens(user)
    org = Org(name=body.name + "的工作空间")
    db.add(org)
    await db.flush()
    user = User(org_id=org.id, username="profile_" + secrets.token_hex(16), display_name=body.name,
                role=Role.lawyer, hashed_password=hash_password(secrets.token_urlsafe(32)))
    db.add(user)
    await db.flush()
    db.add(NamedWorkspace(name_key=key, user_id=user.id))
    try:
        await db.commit()
    except IntegrityError:
        # Concurrent first login with the same name must resolve to one profile.
        await db.rollback()
        user = await lookup()
        if user is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "工作空间正在创建，请重试")
    return _profile_tokens(user)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    if not get_settings().registration_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "registration disabled")
    username = body.username.strip().lower()
    result = await db.execute(select(User).where(func.lower(User.username) == username.lower()))
    if result.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已存在")

    org = Org(name=body.org_name.strip())
    db.add(org)
    await db.flush()
    user = User(
        username=username,
        display_name=body.display_name.strip() or username,
        # Self-registered users receive a private organization but no access
        # to global system settings or user administration.
        role=Role.lawyer,
        org_id=org.id,
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已存在")
    await db.refresh(user)
    extra = {"org": user.org_id, "role": user.role.value}
    return TokenResponse(
        access_token=create_access_token(user.id, extra),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(func.lower(User.username) == body.username.strip().lower())
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad credentials")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "disabled")
    extra = {"org": user.org_id, "role": user.role.value}
    return TokenResponse(
        access_token=create_access_token(user.id, extra),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad refresh token")
    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user invalid")
    profile = await db.scalar(select(NamedWorkspace).where(NamedWorkspace.user_id == user.id))
    if profile and (not get_settings().name_login_enabled or user.role != Role.lawyer):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "姓名工作空间已停用")
    extra = {"org": user.org_id, "role": user.role.value}
    if profile:
        extra["profile"] = True
    return TokenResponse(
        access_token=create_access_token(user.id, extra),
        refresh_token=create_refresh_token(user.id),
    )


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.old_password, user.hashed_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "old password wrong")
    user.hashed_password = hash_password(body.new_password)
    await db.commit()
    return {"ok": True}
