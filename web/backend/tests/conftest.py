"""Isolate all backend tests from workstation user data."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
root = Path(tempfile.mkdtemp(prefix="gd-backend-tests-"))
os.environ["V5_DATA_DIR"] = str(root)
os.environ["V5_DATABASE_URL"] = "sqlite+aiosqlite:///" + (root / "test.db").as_posix()
