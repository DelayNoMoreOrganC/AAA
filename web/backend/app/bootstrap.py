"""First-run setup: no shipped accounts or passwords."""
from sqlalchemy import select

from .config import DATA_DIR, local_secret
from .database import AsyncSessionLocal
from .models import User


async def ensure_bootstrap_admin():
    # Retain the legacy entry-point name for deployment compatibility.
    async with AsyncSessionLocal() as db:
        if (await db.execute(select(User.id).limit(1))).scalar_one_or_none() is None:
            local_secret("setup.token")
        else:
            (DATA_DIR / "setup.token").unlink(missing_ok=True)
