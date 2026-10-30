"""Task dispatcher integration with a transport stub, not model accuracy."""
from copy import deepcopy
from types import SimpleNamespace as NS
import hashlib, json
import pytest

from app.services import task_workflow as workflow, recognition_checkpoint, experience_binding, supplement_identity_context
from tests.test_form_synthesis_integration import make
import archive_pipeline as ap
import form_synthesis as synthesis
from pdf_doc_locator import DocumentUnit


@pytest.mark.parametrize('manual_blank', [False, True])
def test_task_supplement_writes_combined_sources_without_summary_conflict(tmp_path, monkeypatch, manual_blank):
    fields, old, units = make(tmp_path)
    fields['承办律师'] = '原律师'
    # The previous proof predates this unrelated literal fixture addition; its
    # raw reading pool is retained, but its narrative must be regenerated.
    source = tmp_path/'supplement.pdf'; source.write_bytes(b'protocol supplement')
    fresh = {'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
             'pages':1,'file_id':'supplement','doc_type':'default','filename':'supplement.pdf'}
    old[0].update(doc_type='default', filename='first.pdf')
    previous = ap.ArchiveAnalysis('nonlit', old[0]['path'], fields, {}, units, set(), [], source_paths=[old[0]['path']])
    saved = deepcopy(previous)
    manual = {'结案小结':''} if manual_blank else {}
    parent = NS(id=1,case_id='protocol',source_manifest=old,manual_fields=manual,issues=[])
    task = NS(source_manifest=old+[fresh],manual_fields={})
    files = [NS(id=r['file_id'],abs_path=r['path'],doc_type='default') for r in task.source_manifest]
    monkeypatch.setattr(workflow,'snapshot_exists',lambda *_:True)
    monkeypatch.setattr(workflow,'load_analysis',lambda *_:(deepcopy(previous),{}))
    monkeypatch.setattr(workflow,'analysis_reuse_compatible',lambda *_:True)
    monkeypatch.setattr(experience_binding,'bind_config',lambda task,org,config:dict(config))
    monkeypatch.setattr(recognition_checkpoint,'analysis_config',lambda task,parent,org,config,**kw:dict(config))
    monkeypatch.setattr(supplement_identity_context,'build_supplement_identity_context',lambda *a,**k:None)
    messages=[]; analysed=[]
    class Writer:
        def complete(self, msg):
            payload=json.loads(msg[-1]['content']);messages.append(payload)
            sources=payload['sources']
            old_s=next(s for s in sources if '核对草稿' in s['text'])
            new_s=next(s for s in sources if '交付公证书' in s['text'])
            rows={'审（办）结果': {'claims':[{'text':'公证处已出具公证书。',
                'evidence':[{'id':old_s['id'],'quote':old_s['text']}]}],'missing':[]},
                '结案小结':{'claims':[{'text':'律师核对草稿并协助递交申请，公证处已出具公证书。',
                'evidence':[{'id':old_s['id'],'quote':old_s['text']}]},
                {'text':'律师向委托人交付公证书。','evidence':[{'id':new_s['id'],'quote':new_s['text']}]}],'missing':[]}}
            if 'candidates' in payload:rows={k:{**v,'supported':True,'reason':'ok'} for k,v in rows.items()}
            return {'fields':rows}
    def analyze(case_type, *, sources, config, **kwargs):
        analysed.extend(s.path for s in sources)
        unit=DocumentUnit(0,'legal_work',0,0,source_path=str(source),confidence=.95)
        cache={(str(source),1):'补充工作记录：律师向委托人交付公证书。'}
        delta_fields={'结案小结':'新增材料的局部描述','承办律师':'新增律师'}
        status=config['_supplement_synthesis_context'].generate(Writer(),delta_fields,{},[],[unit],cache,set(cache),case_type=case_type)
        return ap.ArchiveAnalysis('nonlit',str(source),{**delta_fields,'_form_synthesis_status':status}, {}, [unit],set(),[],source_paths=[str(source)])
    engine=NS(analyze_archive=analyze,compute_found_seqs=ap.compute_found_seqs,compute_missing_items=ap.compute_missing_items)
    result, _, conflicts = workflow.analyze_with_parent(engine,task,parent,files,
        {'workflow_case_type':'nonlit','extraction':{'mode':'visual_agent'},'vision':{'workflow':'document_two_stage'}},
        'protocol-org',lambda *_:None)
    assert analysed==[str(source)] and len(messages)==2
    assert previous==saved
    assert not any(r['detail'].get('field')=='结案小结' for r in conflicts)
    assert any(r['detail'].get('field')=='承办律师' for r in conflicts)
    assert result.fields['承办律师']=='原律师'
    assert result.fields['_form_synthesis_status']['scope']=='combined_read_sources_after_supplement'
    if manual_blank:assert result.fields['结案小结']==''
    else:
        assert '核对草稿' in result.fields['结案小结'] and '交付公证书' in result.fields['结案小结']
        assert synthesis.current_support(result.fields['_provenance']['结案小结'][-1], result.fields) is not None
    assert synthesis.scope_supported(result.fields,task.source_manifest,result.doc_spans)
