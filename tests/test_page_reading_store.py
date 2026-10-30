"""Reading persistence/permission protocol; no recognition accuracy benchmark."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest

from agent_trace import source_identity
from page_reading_store import PageReadingStore, PageReadingError, path_key


def setup(tmp_path, *, scope=None, reader='a'*64, directory=None, readonly=False):
    path = tmp_path/'source.pdf'
    if not path.exists(): path.write_bytes(b'protocol bytes, not a case or PDF recognition fixture')
    source = source_identity(str(path), 2)
    sources = [{'path_sha256': path_key(str(path)), 'sha256': source['sha256'], 'pages': 2}]
    store = PageReadingStore(directory or tmp_path/'task1'/'page-readings', tmp_path,
        scope or {'org_id':'org1','case_id':'case1','task_id':1}, sources, reader, readonly=readonly)
    return store, source, [NS(source_path=str(path),start_page=0,end_page=1)]


def save(store, source, *, rotation=0, text='源文字', eligible=True):
    store.save(source, 1, rotation, text=text,
        blocks=[{'page_idx':0,'text':text,'confidence':.3,'normalized_box':[.1,.2,.8,.3]}],
        view={'method':'local_ocr','rotation':rotation})
    if eligible: store.mark_eligible(source,1,rotation)


def test_reopen_preserves_full_text_layout_and_eligibility_without_successful_forms(tmp_path):
    store, source, units = setup(tmp_path);save(store,source)
    reopened, _, _ = setup(tmp_path,readonly=True)
    assert reopened.prior_cache(units)=={(source['source_path'],1):'源文字'}
    row=reopened.read(source,1,0)
    assert row['blocks'][0]['confidence']==.3
    assert row['blocks'][0]['normalized_box']==[.1,.2,.8,.3]
    assert not list(store.directory.glob('*.tmp'))


def test_not_yet_admitted_reading_does_not_enter_supplement_pool(tmp_path):
    store, source, units=setup(tmp_path);save(store,source,eligible=False)
    assert store.read(source,1,0)['text']=='源文字'
    assert store.prior_cache(units)=={}


@pytest.mark.parametrize('part',['org_id','case_id','task_id'])
def test_other_scope_cannot_read_even_if_pointed_at_same_record(tmp_path,part):
    store,source,_=setup(tmp_path);save(store,source)
    scope=deepcopy(store.scope);scope[part]='different'
    other,_,_=setup(tmp_path,scope=scope)
    with pytest.raises(PageReadingError):other.read(source,1,0)


def test_changed_reader_or_rotation_is_a_cache_miss(tmp_path):
    store,source,_=setup(tmp_path);save(store,source)
    other,_,_=setup(tmp_path,reader='b'*64)
    assert other.read(source,1,0) is None
    assert store.read(source,1,90) is None


def test_changed_source_rejected_before_returning_old_text(tmp_path):
    store,source,units=setup(tmp_path);save(store,source)
    Path(source['source_path']).write_bytes(b'replacement')
    with pytest.raises(PageReadingError):store.prior_cache(units)


def test_two_eligible_orientations_are_not_silently_selected(tmp_path):
    store,source,units=setup(tmp_path);save(store,source);save(store,source,rotation=90,text='不同文字')
    assert store.prior_cache(units)=={}
    readonly,_,_=setup(tmp_path,readonly=True)
    child,_,_=setup(tmp_path,directory=tmp_path/'task2'/'page-readings',scope={**store.scope,'task_id':2})
    child.inherit(readonly,units)
    assert child.cache_result(units)==({}, {(source['source_path'],1)})


def test_corruption_is_not_silently_replaced_or_reread(tmp_path):
    store,source,_=setup(tmp_path);save(store,source)
    record=next(store.directory.glob('*.json'))
    body=json.loads(record.read_text(encoding='utf-8'));body['body']['text']='altered'
    record.write_text(json.dumps(body),encoding='utf-8')
    with pytest.raises(PageReadingError):store.read(source,1,0)
    with pytest.raises(PageReadingError):save(store,source)


def test_out_of_scope_page_and_source_are_rejected(tmp_path):
    store,source,_=setup(tmp_path)
    with pytest.raises(PageReadingError):store.read(source,3,0)
    with pytest.raises(PageReadingError):store.read({**source,'source_path':str(tmp_path/'other')},1,0)


def test_readonly_parent_cannot_write(tmp_path):
    store,source,_=setup(tmp_path,readonly=True)
    with pytest.raises(PageReadingError):save(store,source)
    assert not store.directory.exists()


def test_successive_supplements_preserve_earlier_full_readings(tmp_path):
    parent,source,units=setup(tmp_path);save(parent,source)
    readonly,_,_=setup(tmp_path,readonly=True)
    child,_,_=setup(tmp_path,directory=tmp_path/'task2'/'page-readings',scope={**parent.scope,'task_id':2})
    child.inherit(readonly,units)
    reopened,_,_=setup(tmp_path,directory=child.directory,scope=child.scope,readonly=True)
    grandchild,_,_=setup(tmp_path,directory=tmp_path/'task3'/'page-readings',scope={**parent.scope,'task_id':3})
    grandchild.inherit(reopened,units)
    assert grandchild.prior_cache(units)=={(source['source_path'],1):'源文字'}


def test_inheritance_cannot_cross_case(tmp_path):
    parent,source,units=setup(tmp_path,readonly=True)
    child,_,_=setup(tmp_path,directory=tmp_path/'task2',scope={**parent.scope,'case_id':'another'})
    with pytest.raises(PageReadingError):child.inherit(parent,units)


def test_task_reading_directory_cannot_escape_root(tmp_path):
    with pytest.raises(PageReadingError):setup(tmp_path,directory=tmp_path.parent/'escape')


def test_casepages_cached_path_keeps_quality_issues_without_new_reader(tmp_path,monkeypatch):
    from visual_archive_agent import CasePages
    import visual_archive_agent as module
    store,source,_=setup(tmp_path);save(store,source)
    # Initialize the actual read method's state without inventing a case PDF.
    pages=object.__new__(CasePages)
    pages.pages={'f1p1':(source['source_path'],0)};pages.read_pages=set()
    pages.texts={source['source_path']:['','']};pages.source_identities={source['source_path']:source}
    pages.ocr_rotation_hints={};pages.reading_store=store;pages.reading_rotations={}
    pages.reading_cache_hits=0;pages.layout_blocks={};pages.text_views={};pages.ocr_review=[]
    monkeypatch.setattr(module,'create_local_engine',lambda:pytest.fail('must not OCR on cache hit'))
    monkeypatch.setattr(module.fitz,'open',lambda *_:pytest.fail('must not parse on cache hit'))
    assert pages.read('f1p1')=='源文字' and pages.reading_cache_hits==1
    assert pages.layout_blocks[source['source_path'],1][0]['confidence']==.3
    assert pages.ocr_review, 'Persisted low-confidence reading must not lose review warnings'
    assert pages.read('f1p1')=='源文字' and pages.reading_cache_hits==1


def test_actual_reader_saves_before_any_form_generation_and_new_instance_reuses(tmp_path,monkeypatch):
    from visual_archive_agent import CasePages
    import visual_archive_agent as module
    store,source,_=setup(tmp_path)
    def instance():
        pages=object.__new__(CasePages)
        pages.pages={'f1p1':(source['source_path'],0)};pages.read_pages=set()
        pages.texts={source['source_path']:['','']};pages.source_identities={source['source_path']:source}
        pages.ocr_rotation_hints={};pages.reading_store=store;pages.reading_rotations={}
        pages.reading_cache_hits=0;pages.layout_blocks={};pages.text_views={};pages.ocr_review=[]
        pages.ocr_seconds=0
        return pages
    class LocalDocument:
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def __getitem__(self,n):return object()
    monkeypatch.setattr(module.fitz,'open',lambda *_:LocalDocument())
    monkeypatch.setattr(module,'ordered_text_layer',lambda *_:'完整来源文字，仅测试读取协议，不是案件识别。')
    monkeypatch.setattr(module,'_usable_text_layer',lambda *_:True)
    first=instance();text=first.read('f1p1')
    assert store.read(source,1,0)['text']==text
    assert not store.read(source,1,0)['eligible']
    monkeypatch.setattr(module.fitz,'open',lambda *_:pytest.fail('restart must use saved reading'))
    second=instance()
    assert second.read('f1p1')==text and second.reading_cache_hits==1
