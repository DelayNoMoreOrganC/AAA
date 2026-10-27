from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import require_admin
from ..models import Org, Role, User
from ..schemas import OrgCreate, OrgOut, UserCreate, UserOut, UserUpdate
from ..security import hash_password

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/orgs", response_model=list[OrgOut])
async def list_orgs(user=Depends(require_admin), db=Depends(get_db)):
    res = await db.execute(select(Org).where(Org.id == user.org_id).order_by(Org.name))
    return [OrgOut(id=o.id, name=o.name) for o in res.scalars().all()]


@router.post("/orgs", response_model=OrgOut, status_code=201)
async def create_org(body: OrgCreate, user=Depends(require_admin), db=Depends(get_db)):
    raise HTTPException(status.HTTP_403_FORBIDDEN, "机构管理员仅可管理本机构，不支持创建其他机构")


@router.get("/users", response_model=list[UserOut])
async def list_users(user=Depends(require_admin), db=Depends(get_db)):
    res = await db.execute(select(User).where(User.org_id == user.org_id).order_by(User.created_at))
    out = []
    for u in res.scalars().all():
        out.append(UserOut(id=u.id, username=u.username, display_name=u.display_name, role=u.role.value, org_id=u.org_id, is_active=u.is_active))
    return out


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(body: UserCreate, user=Depends(require_admin), db=Depends(get_db)):
    org_id = body.org_id or user.org_id
    if org_id != user.org_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只能为本机构创建账号")
    role_val = Role.admin if body.role == "admin" else Role.lawyer
    new_user = User(username=body.username, display_name=body.display_name, role=role_val, org_id=org_id, hashed_password=hash_password(body.password))
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return UserOut(id=new_user.id, username=new_user.username, display_name=new_user.display_name, role=new_user.role.value, org_id=new_user.org_id, is_active=new_user.is_active)


@router.put("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: str, body: UserUpdate, user=Depends(require_admin), db=Depends(get_db)):
    res = await db.execute(select(User).where(User.id == user_id, User.org_id == user.org_id))
    target = res.scalar_one_or_none()
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    if body.display_name is not None:
        target.display_name = body.display_name
    if body.role is not None:
        target.role = Role.admin if body.role == "admin" else Role.lawyer
    if body.is_active is not None:
        target.is_active = body.is_active
    if body.password:
        target.hashed_password = hash_password(body.password)
    await db.commit()
    await db.refresh(target)
    return UserOut(id=target.id, username=target.username, display_name=target.display_name, role=target.role.value, org_id=target.org_id, is_active=target.is_active)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: str, user=Depends(require_admin), db=Depends(get_db)):
    res = await db.execute(select(User).where(User.id == user_id, User.org_id == user.org_id))
    target = res.scalar_one_or_none()
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    await db.delete(target)
    await db.commit()
    return None
