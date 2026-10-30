"""An idle-looking older process must not authorize paid regression of new code."""
from types import SimpleNamespace

import pytest

from app.core.v4_bridge import init_v4_path
init_v4_path()
import recognition_identity as identity


@pytest.mark.parametrize('module', ['visual_fact_readback.py', 'visual_synthesis_sources.py', 'supplement_synthesis.py'])
def test_visual_proof_policy_changes_are_part_of_production_fingerprint(tmp_path, monkeypatch, module):
    assert module in identity.RECOGNITION_FILES
    monkeypatch.setattr(identity, 'RECOGNITION_FILES', ('case_outcome.py', module))
    (tmp_path / 'case_outcome.py').write_text('STRICT_EVIDENCE_VERSION = "strict-fields-v4"', encoding='utf-8')
    (tmp_path / module).write_text('POLICY = 1', encoding='utf-8')
    before = identity.recognition_identity(tmp_path)
    (tmp_path / module).write_text('POLICY = 2', encoding='utf-8')
    assert identity.recognition_identity(tmp_path)['recognition_signature'] != before['recognition_signature']


def test_fingerprint_ignores_runtime_and_ui_but_changes_for_recognition(tmp_path, monkeypatch):
    monkeypatch.setattr(identity, "RECOGNITION_FILES", ("case_outcome.py", "reader.py"))
    (tmp_path / "case_outcome.py").write_text('STRICT_EVIDENCE_VERSION = "strict-fields-v4"', encoding="utf-8")
    (tmp_path / "reader.py").write_text("reader = 1", encoding="utf-8")
    before = identity.recognition_identity(tmp_path)
    (tmp_path / "credentials.json").write_text('DO_NOT_READ_PRIVATE_SENTINEL', encoding="utf-8")
    (tmp_path / "interface.vue").write_text('another UI', encoding="utf-8")
    assert identity.recognition_identity(tmp_path) == before
    (tmp_path / "reader.py").write_text("reader = 2", encoding="utf-8")
    assert identity.recognition_identity(tmp_path)["recognition_signature"] != before["recognition_signature"]
    (tmp_path / "reader.py").unlink()
    with pytest.raises(FileNotFoundError):
        identity.recognition_identity(tmp_path)


@pytest.mark.asyncio
async def test_health_uses_startup_identity_and_unknown_count_is_not_zero(monkeypatch):
    from app import main
    frozen = {"recognition_signature": "a" * 64, "normalization_version": "strict-fields-v3"}
    monkeypatch.setattr(main.app.state, "recognition_identity", frozen, raising=False)
    monkeypatch.setattr(main, "load", lambda *_: pytest.fail("health must not relabel running code from disk"))
    def unavailable():
        raise OSError("PRIVATE_DATABASE_PATH")
    monkeypatch.setattr(main.database, "AsyncSessionLocal", unavailable)
    output = await main.health()
    assert output["recognition_signature"] == "a" * 64
    assert output["normalization_version"] == "strict-fields-v3"
    assert output["active_archive_tasks"] is None
    assert "PRIVATE_DATABASE_PATH" not in str(output)
    assert type(output["processing_busy"]) is bool
