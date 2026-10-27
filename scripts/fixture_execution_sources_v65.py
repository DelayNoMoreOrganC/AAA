"""Same v64 bytes, but exercise production source recall, not just timeline."""
from pathlib import Path
import re
from fixture_execution_v64 import analyze as limited_analyze

def analyze(paths,case_type,data):
    import fitz
    from source_fact_recall import recall_cached_source_facts
    from fact_evidence import validate_fact
    a=limited_analyze(paths,case_type,data)
    with fitz.open(paths[0]) as pdf:cache={(paths[0],i+1):p.get_text(sort=True) for i,p in enumerate(pdf)}
    refs=a.fields['_provenance'];contract=cache[(paths[0],2)]
    # These candidates replace model extraction only. The exact source and the
    # production evidence validator must accept them before source recall runs.
    fee='基础代理费5000元，按实际回款金额另收2%。'
    for field,value in [('委托人','虚构甲银行'),('收费标准',fee)]:
        assert validate_fact(field,value,contract,contract),(field,'candidate rejected')
        a.fields[field]=value
        refs[field]=[dict(field=field,value=value,quote=contract,source_path=paths[0],page=2,method='visual_agent_local_evidence',candidate_origin='authored_fixture_candidate')]
    conflicts=[];review=[]
    metrics=recall_cached_source_facts(a.fields,refs,conflicts,page_cache=cache,allowed_sources=set(cache),fact_review=review,document_units=a.doc_spans)
    a.fields.update(_provenance=refs,_field_conflicts=conflicts,_fact_review=review,_source_fact_recall=metrics,
        _fixture_scope='Same authored recognition candidates; actual complete production source recall; no model accuracy evidence')
    assert a.fields.get('_intake_complaint_source')
    assert a.fields.get('立案审批日期')=='2026年1月5日'
    return a
