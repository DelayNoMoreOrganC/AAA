"""One-time, token-protected workstation owner creation."""
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select, text

from ..config import DATA_DIR
from ..database import get_db
from ..models import Org, Role, User
from ..schemas import RegisterRequest
from ..security import hash_password

router = APIRouter(prefix="/api/setup", tags=["setup"])


class SetupRequest(RegisterRequest):
    password: str = Field(..., min_length=12, max_length=72)
    setup_token: str = Field(..., min_length=32, max_length=128)
    output_directory: str = Field(default="", max_length=500)


@router.get("/status")
async def setup_status(db=Depends(get_db)):
    existing = (await db.execute(select(User.id).limit(1))).scalar_one_or_none()
    return {"required": existing is None}


@router.post("")
async def setup_owner(body: SetupRequest, db=Depends(get_db)):
    await db.execute(text("BEGIN IMMEDIATE"))
    if (await db.execute(select(User.id).limit(1))).scalar_one_or_none() is not None:
        raise HTTPException(409, "工作站已初始化，请登录")
    path = DATA_DIR / "setup.token"
    expected = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    if not expected or not secrets.compare_digest(expected, body.setup_token):
        raise HTTPException(403, "初始化凭据无效，请在工作站本机重新打开启动链接")
    if body.output_directory.strip():
        from ..services.output_export import set_output_directory
        try:
            set_output_directory(body.output_directory.strip())
        except (ValueError, OSError):
            raise HTTPException(400, "输出目录不可用，请选择工作站本机的绝对目录，并确认有写入权限。 [GD_OUTPUT_DIRECTORY_INVALID]") from None
    org = Org(name=body.org_name.strip())
    db.add(org)
    await db.flush()
    db.add(User(username=body.username, display_name=body.display_name or body.username,
                hashed_password=hash_password(body.password), org_id=org.id, role=Role.admin))
    await db.commit()
    path.unlink(missing_ok=True)
    return {"ok": True}
