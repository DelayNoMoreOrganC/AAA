"""Independent static build selection, with in-memory ASGI and synthetic files."""
import importlib.util
import sys
import uuid
from pathlib import Path

import httpx
import pytest

from app import config


def isolated_module(path, prefix):
    name = "app." + prefix + "_" + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


def test_frontend_directory_defaults_without_override(monkeypatch):
    monkeypatch.delenv("V5_FRONTEND_DIST", raising=False)
    module = isolated_module(config.__file__, "static_config")
    assert module.FRONTEND_DIST == (module.WEB_DIR / "frontend" / "dist").resolve()


def test_frontend_directory_expands_home_and_resolves_relative_path(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("V5_FRONTEND_DIST", str(tmp_path / "builds" / ".." / "frozen-build"))
    module = isolated_module(config.__file__, "static_config")
    assert module.FRONTEND_DIST == (tmp_path / "frozen-build").resolve()
    # Path.expanduser uses platform home environment variables.
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("V5_FRONTEND_DIST", "~/frozen-build")
    module = isolated_module(config.__file__, "static_config")
    assert module.FRONTEND_DIST == (tmp_path / "frozen-build").resolve()


@pytest.mark.asyncio
async def test_separate_app_instances_keep_their_own_index_assets_and_spa(monkeypatch, tmp_path):
    builds = []
    for marker in ("old-worker", "staged-worker"):
        folder = tmp_path / marker
        (folder / "assets").mkdir(parents=True)
        (folder / "index.html").write_text(f"<html>{marker}</html>", encoding="utf-8")
        (folder / "assets" / "app.js").write_text(f"window.build='{marker}'", encoding="utf-8")
        builds.append(folder)
    main_path = Path(config.__file__).with_name("main.py")
    apps = []
    for folder in builds:
        monkeypatch.setenv("V5_FRONTEND_DIST", str(folder))
        selected = isolated_module(config.__file__, "static_config").FRONTEND_DIST
        monkeypatch.setattr(config, "FRONTEND_DIST", selected)
        apps.append(isolated_module(main_path, "static_app").app)
    # Loading the staged app changed neither the first app's captured path nor
    # the first build. The real lifespan (database/recovery) is not invoked.
    for app, marker in zip(apps, ("old-worker", "staged-worker")):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            for route in ("/", "/cases/fictional/tasks/1"):
                response = await client.get(route)
                assert response.status_code == 200 and response.text == f"<html>{marker}</html>"
                assert "text/html" in response.headers["content-type"]
            asset = await client.get("/assets/app.js")
            assert asset.status_code == 200 and asset.text == f"window.build='{marker}'"
            assert (await client.get("/api/unknown-static-test")).status_code == 404
            assert (await client.get("/%2e%2e/%2e%2e/outside.txt")).status_code == 404
