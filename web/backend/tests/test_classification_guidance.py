from types import SimpleNamespace as NS
from app.services.classification_guidance import guidance
from app.services.document_classification import classification_options
from app.services.archive_rules import material_completeness
import pytest

def fixture(score=.95,kind='ruling',seq=14):
    u=NS(title='民事裁定书',doc_type=kind,catalog_seq=seq,doc_id=1,start_page=0,end_page=0,source_path='fiction.pdf',confidence=score,manual_catalog_seq=None)
    a=NS(case_type='civil',fields={},low_confidence_items=[],doc_spans=[u])
    return u,a

def test_model_score_alone_is_not_independently_confirmed():
    u,a=fixture();o=classification_options('civil')
    assert guidance(u,a,o)['match_tier']=='suggested'
    a.fields['_visual_classification_review']=[dict(page=1,source_path='fiction.pdf',effective_doc_type='ruling',independent_title_verified=True)]
    assert guidance(u,a,o)['match_tier']=='confirmed'
    a.low_confidence_items=[dict(doc_id=1)]
    assert guidance(u,a,o)['match_tier']=='pending'


@pytest.mark.parametrize('records', [None, 'not an audit', {'independent_title_verified': True},
    [None, 1, "{'independent_title_verified': True}"]])
def test_malformed_audit_never_confirms_or_breaks_document_review(records):
    u,a=fixture()
    a.fields['_visual_classification_review']=records
    assert guidance(u,a,classification_options('civil'))['match_tier']=='suggested'


def test_valid_audit_survives_mixed_legacy_records():
    u,a=fixture()
    a.fields['_visual_classification_review']=[None, 'legacy', dict(page=1,
        source_path='fiction.pdf',effective_doc_type='ruling',independent_title_verified=True)]
    assert guidance(u,a,classification_options('civil'))['match_tier']=='confirmed'

@pytest.mark.parametrize('score',[.79,None,float('nan'),True,1.2])
def test_low_or_invalid_scores_are_pending(score):
    u,a=fixture(score)
    assert guidance(u,a,classification_options('civil'))['match_tier']=='pending'

def test_letter_suggestion_does_not_substitute_for_authorization():
    u,a=fixture(kind='unknown',seq=7);u.title='广东虚构律师事务所函'
    g=guidance(u,a,classification_options('civil'))
    assert g['suggestions'][0]['doc_type']=='firm_letter' and g['suggestions'][0]['catalog_seq']==7
    assert not any(o['doc_type']=='firm_letter' for o in classification_options('arbitration'))
    u.doc_type='firm_letter';u.catalog_seq=7
    checks=material_completeness(a,source_manifest=[dict(path='fiction.pdf',file_id='f',pages=1)])['checks']
    assert next(r for r in checks if r['id']=='material:poa')['material_found'] is False
