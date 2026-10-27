from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from ..deps import require_admin
from ..services.output_export import output_directory, set_output_directory

router = APIRouter(prefix="/api/workstation", tags=["workstation"])


class OutputSettings(BaseModel):
    output_directory: str = Field(min_length=3, max_length=500)


@router.get("/output")
async def get_output(user=Depends(require_admin)):
    return {"output_directory": str(output_directory())}


@router.put("/output")
async def update_output(body: OutputSettings, user=Depends(require_admin)):
    try:
        path = set_output_directory(body.output_directory.strip())
    except (ValueError, OSError):
        raise HTTPException(400, "输出目录不可用，请选择工作站本机的绝对目录，并确认有写入权限。 [GD_OUTPUT_DIRECTORY_INVALID]") from None
    return {"output_directory": str(path)}
