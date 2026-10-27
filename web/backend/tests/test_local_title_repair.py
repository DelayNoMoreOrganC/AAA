from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('title_repair',ROOT/'scripts/prepare_local_repair.py')
repair=importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)

@pytest.fixture
def sample(tmp_path):
    cache=tmp_path/'page.txt'
    cache.write_text('虚构区人民法院\n受理案件通知书\n(2026)虚0101民初1号\n虚构公司：\n起诉至本院。本院依法适用简易程序对本案进行审理，现通知如下。',encoding='utf-8')
    manifest=[dict(file_id='f',path=str(tmp_path/'source.pdf'),sha256='a'*64,pages=1)]
    old=dict(source_path=manifest[0]['path'],page=1,method='local_title_context_review',independent_title_verified=False)
    before={'_visual_classification_review':[old,dict(reason_code='catalog_mapping_uncertain')]}
    entry=dict(file_id='f',page=1,source_sha256='a'*64,cache_path=str(cache),cache_sha256=repair.digest(cache))
    unit=SimpleNamespace(source_path=manifest[0]['path'],start_page=0,end_page=0,doc_type='unknown',title='受理案件通知书',confidence=.5,manual_catalog_seq=None)
    return before,[entry],manifest,[unit],tmp_path

def test_replay_uses_local_production_validator_and_preserves_mapping_review(sample):
    before,entries,manifest,units,root=sample
    original=deepcopy(before)
    result=repair.replay_title_reviews(*sample)
    assert before==original
    assert result[0]['reason_code']=='catalog_mapping_uncertain'
    assert result[1]['independent_title_verified'] is True
    assert units[0].doc_type=='unknown' and units[0].confidence==.5

@pytest.mark.parametrize('field,value',[
    ('file_id','other'),('page',2),('page',True),('source_sha256','b'*64),
    ('cache_sha256','b'*64),('cache_path','missing.txt'),
])
def test_replay_refuses_changed_source_or_cache(sample,field,value):
    sample[1][0][field]=value
    with pytest.raises(ValueError):repair.replay_title_reviews(*sample)

def test_replay_refuses_ambiguous_span_manual_type_or_duplicate(sample):
    sample[3][0].manual_catalog_seq=7
    with pytest.raises(ValueError):repair.replay_title_reviews(*sample)
    sample[3][0].manual_catalog_seq=None
    sample[3][0].end_page=1
    with pytest.raises(ValueError):repair.replay_title_reviews(*sample)
    sample[3][0].end_page=0
    sample[1].append(deepcopy(sample[1][0]))
    with pytest.raises(ValueError):repair.replay_title_reviews(*sample)

def test_replay_refuses_text_that_does_not_support_notice(sample):
    cache=Path(sample[1][0]['cache_path']);cache.write_text('虚构区人民法院\n受理案件通知书\n本院拟适用简易程序。',encoding='utf-8')
    sample[1][0]['cache_sha256']=repair.digest(cache)
    with pytest.raises(ValueError,match='not_supported'):repair.replay_title_reviews(*sample)
