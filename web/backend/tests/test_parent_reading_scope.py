"""Server capability scope checks; no source recognition/cloud requests."""
from types import SimpleNamespace as NS
import hashlib
import pytest
from app.services import recognition_checkpoint as checkpoint
from app import config
import json
from app.core.v4_bridge import init_v4_path
init_v4_path()


def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'ORGS_DIR',tmp_path)
    path=tmp_path/'source.pdf';path.write_bytes(b'protocol source')
    manifest=[{'file_id':'f1','path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
               'pages':1,'doc_type':'default','filename':'source.pdf'}]
    task=NS(case_id='case1',parent_task_id=7)
    parent=NS(case_id='case1',id=7)
    return task,parent,manifest


def test_parent_readings_live_only_under_authorized_org_case_task(tmp_path,monkeypatch):
    task,parent,manifest=setup(tmp_path,monkeypatch)
    store=checkpoint.parent_readings(task,parent,'org1',manifest,reader='a'*64)
    assert store.readonly
    assert store.directory==tmp_path/'org1'/'cases'/'case1'/'tasks'/'7'/'page-readings'
    assert store.scope=={'org_id':'org1','case_id':'case1','task_id':7}
    assert not store.directory.exists()


@pytest.mark.parametrize('change',['parent_case','parent_id','path_traversal'])
def test_parent_readings_reject_wrong_parent_or_traversal(tmp_path,monkeypatch,change):
    task,parent,manifest=setup(tmp_path,monkeypatch)
    if change=='parent_case':parent.case_id='other'
    elif change=='parent_id':parent.id=8
    else:task.case_id='../case'
    with pytest.raises(checkpoint.RecognitionCheckpointError):
        checkpoint.parent_readings(task,parent,'org1',manifest,reader='a'*64)


def test_checkpoint_creates_private_reading_capability_without_json_settings(tmp_path,monkeypatch):
    import page_reading_store
    task,parent,manifest=setup(tmp_path,monkeypatch)
    sources,_=checkpoint._manifest(manifest)
    monkeypatch.setattr(page_reading_store,'reader_identity',lambda:'b'*64)
    scope={'org_id':'org1','case_id':'case1','task_id':8,'reading_sources':sources}
    journal=tmp_path/'org1'/'cases'/'case1'/'tasks'/'8'/'recognition-journal'
    capability=checkpoint.RecognitionCheckpoint(journal,json.dumps(scope),tmp_path)
    readings=capability.page_readings()
    assert readings.directory==journal.parent/'page-readings'
    assert not readings.readonly and readings.scope['task_id']==8
    assert readings.reader=='b'*64 and not readings.directory.exists()
