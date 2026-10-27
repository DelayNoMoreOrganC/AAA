from types import SimpleNamespace

import pytest

from app.core import config_adapter


@pytest.mark.asyncio
async def test_workstation_never_inherits_legacy_matcher_diagnostics(monkeypatch):
    async def settings(*args):
        return {**config_adapter.DEFAULTS, "debug": {"match_details": True}}
    monkeypatch.setattr(config_adapter, "load_user_settings", settings)
    monkeypatch.setattr(config_adapter, "get_settings", lambda: SimpleNamespace(preview_only=True))
    config = await config_adapter.build_v4_config(None, "fictional-user")
    assert config["debug"] == {"match_details": False}
