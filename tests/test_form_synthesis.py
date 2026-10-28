from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace as NS
import pytest

from form_field_policy import NARRATIVES, policy
from form_synthesis import (generate, collect_sources, validate_candidate, current_support,
                            scope_supported, discard_stale, prepare_candidate, finalize_review, KEY, BINDING)
from form_drafts import derive_form_drafts


def fixture(tmp_path):
    path = str(tmp_path / 'fictional.pdf')
    text = '甲方虚构甲委托虚构律所协助办理遗嘱公证手续，并就该事项提供法律咨询。'
    end = '办理记录：律师核对遗嘱草稿并协助递交公证申请。公证处已出具公证书。'
    data = (text + end).encode()
    (tmp_path / 'fictional.pdf').write_bytes(data)
    units = [NS(source_path=path, start_page=n, end_page=n, doc_type=kind,
                doc_id=n+1, confidence=.95) for n, kind in enumerate(('contract','legal_work'))]
    cache = {(path,1):text, (path,2):end}
    manifest = [{'file_id':'fictional', 'path':path, 'pages':2, 'sha256':hashlib.sha256(data).hexdigest()}]
    return units, cache, manifest


class Model:
    def __init__(self, reject=()):
        self.calls = []
        self.reject = reject
    def complete(self, messages):
        self.calls.append(messages)
        payload = json.loads(messages[-1]['content'])
        if 'candidates' in payload:
            return {'fields':{k:{'supported':k not in self.reject,
                                 'reason':'unsupported_claim' if k in self.reject else 'ok',
                                 **payload['candidates'][k]}
                              for k in payload['candidates']}}
        sources = payload['sources']
        texts = {'案情简介': '委托事项为办理遗嘱公证及相关法律咨询。',
                 '案件或项目名称':'遗嘱公证法律服务',
                 '审（办）结果':'公证处已出具公证书。',
                 '结案小结':'受托协助办理遗嘱公证。律师核对草稿并协助递交申请，公证处已出具公证书。'}
        return {'fields':{k:{'claims':[{'text':texts[k], 'evidence':[
            {'id':s['id'], 'quote':s['text']} for s in sources
            if k not in ('案情简介','案件或项目名称') or s['kind']=='contract']}], 'missing':[]}
            for k in payload['rules']}}


def run(tmp_path, reject=(), manual=()):
    units, cache, manifest = fixture(tmp_path)
    fields, provenance = {'委托人':'虚构甲'}, {}
    client = Model(reject)
    guards = []
    status = generate(client, fields, provenance, [], units, cache, set(cache),
                      case_type='nonlit', guard=lambda: guards.append(1), manual_fields=manual)
    fields['_provenance'] = provenance
    return fields, status, client, guards, units, manifest


def test_two_calls_separate_writing_and_review_and_independent_columns(tmp_path):
    fields,status,client,guards,units,manifest=run(tmp_path)
    assert len(client.calls) == len(guards) == status['requests'] == 2
    assert fields['结案小结'] != fields['审（办）结果']
    assert all(status['fields'][k]=='generated' for k in NARRATIVES)
    for field in NARRATIVES:
        assert current_support(fields['_provenance'][field][-1],fields) is not None
    assert scope_supported(fields,manifest,units)
    assert 'source_path' not in client.calls[0][-1]['content']
    rendered=derive_form_drafts(fields, units, source_manifest=manifest)
    assert all(rendered[k]==fields[k] for k in NARRATIVES)


def test_partial_rejection_and_manual_blank_are_not_overwritten(tmp_path):
    fields,status,client,*_=run(tmp_path,reject=('结案小结',),manual={'案情简介':''})
    assert '案情简介' not in fields and '结案小结' not in fields
    assert fields['审（办）结果']
    assert status['fields']['结案小结']=='semantic_review_rejected'
    assert len(client.calls)==2


def test_quotes_numbers_and_intake_time_perspective(tmp_path):
    units,cache,_=fixture(tmp_path)
    sources,_=collect_sources(units,cache,set(cache))
    row={'claims':[{'text':'已收到10000元。','evidence':[{'id':'S1','quote':sources[0]['text']}]}],'missing':[]}
    assert validate_candidate('结案小结',row,sources) is None
    row['claims'][0]={'text':'已完成公证。','evidence':[{'id':'S2','quote':sources[1]['text']}]}
    assert validate_candidate('案情简介',row,sources) is None
    row['claims'][0]['evidence'][0]['quote']='这是不存在的原文证据。'
    assert validate_candidate('审（办）结果',row,sources) is None


def test_changed_identity_material_or_classification_invalidates_without_model_call(tmp_path):
    fields,_,client,_,units,manifest=run(tmp_path)
    before=deepcopy(fields)
    fields['委托人']='虚构乙'
    assert current_support(fields['_provenance']['结案小结'][-1],fields) is None
    discard_stale(fields,{},manifest,units)
    assert fields['结案小结']==''
    fields=deepcopy(before)
    changed=deepcopy(manifest);changed[0]['sha256']='other'
    discard_stale(fields,{},changed,units)
    assert fields['审（办）结果']==''
    fields=deepcopy(before)
    changed_units=deepcopy(units);changed_units[1].doc_type='evidence'
    discard_stale(fields,{'结案小结':'人工保留'},manifest,changed_units)
    assert fields['结案小结']==before['结案小结'] and fields['案情简介']==''
    assert len(client.calls)==2


def test_provided_answer_forms_are_excluded_and_missing_sources_are_disclosed(tmp_path):
    units,cache,_=fixture(tmp_path)
    units[1].doc_type='closure_report'
    rows,coverage=collect_sources(units,cache,{(units[0].source_path,2)})
    assert not rows and coverage['excluded_or_partial']==1


def test_source_budget_distributes_across_documents_and_preserves_page_identity(tmp_path):
    units,cache,_=fixture(tmp_path)
    rows,coverage=collect_sources(units,cache,set(cache),max_chars=5)
    assert rows==[] and coverage['excluded_or_partial']==2


def test_no_calls_when_identity_conflicts_or_no_source(tmp_path):
    units,cache,_=fixture(tmp_path)
    client=Model()
    status=generate(client,{}, {}, [{'field':'委托人'}],units,cache,set(cache),case_type='nonlit')
    assert status['status']=='identity_conflict' and not client.calls


def test_every_physical_template_cell_has_a_policy():
    # Parse the literal registry without importing backend or touching its DB.
    import ast
    from pathlib import Path
    module=ast.parse(Path('web/backend/app/services/original_template_service.py').read_text(encoding='utf8'))
    slots=next(ast.literal_eval(n.value) for n in module.body if isinstance(n,ast.Assign)
               and any(isinstance(t,ast.Name) and t.id=='SLOTS' for t in n.targets))
    assert all(policy(row[0]) for rows in slots.values() for row in rows)
    assert policy('主任审批意见')[0]=='human'
    assert policy('__volume_pages')[0]=='system'


def test_unique_exact_quote_can_repair_page_but_not_an_ambiguous_quote(tmp_path):
    units,cache,_=fixture(tmp_path)
    sources,_=collect_sources(units,cache,set(cache))
    row={'claims':[{'text':'公证处已出具公证书。','note':'ignored inert metadata',
                    'evidence':[{'id':'WRONG','quote':sources[1]['text']}]}], 'missing':[]}
    fixed=prepare_candidate(row,sources)
    assert fixed['claims'][0]['evidence'][0]['id']=='S2'
    assert 'note' not in fixed['claims'][0]
    assert validate_candidate('审（办）结果',fixed,sources)
    duplicate=dict(sources[1],id='S3')
    ambiguous=prepare_candidate(row,[*sources,duplicate])
    assert ambiguous['claims'][0]['evidence'][0]['id']=='WRONG'
    assert validate_candidate('审（办）结果',ambiguous,[*sources,duplicate]) is None


def test_reviewer_can_rescue_a_long_draft_but_final_output_still_requires_evidence(tmp_path):
    units,cache,_=fixture(tmp_path)
    class EditingModel(Model):
        def complete(self,messages):
            response=super().complete(messages)
            if 'candidates' not in json.loads(messages[-1]['content']):
                response['fields']['结案小结']['claims'][0]['text']='无依据的空话。'*100
            else:
                response['fields']['结案小结']['claims'][0]['text']='律师核对草稿并协助递交申请，公证处已出具公证书。'
            return response
    fields={};client=EditingModel()
    status=generate(client,fields,{},[],units,cache,set(cache),case_type='nonlit')
    assert status['fields']['结案小结']=='generated'
    assert len(fields['结案小结'])<100 and len(client.calls)==2


def test_valid_intake_sentence_survives_a_post_intake_sentence_but_negative_review_does_not(tmp_path):
    units,cache,_=fixture(tmp_path)
    sources,_=collect_sources(units,cache,set(cache))
    decision={'supported':True,'reason':'ok','missing':[], 'claims':[
        {'text':'受托办理遗嘱公证及相关法律咨询。','evidence':[{'id':'S1','quote':sources[0]['text']}]},
        {'text':'公证处已出具公证书。','evidence':[{'id':'S2','quote':sources[1]['text']}]}]}
    kept=finalize_review('案情简介',decision,sources)
    assert kept['value']=='受托办理遗嘱公证及相关法律咨询。' and kept['missing']==[]
    decision['supported']=False
    assert finalize_review('案情简介',decision,sources) is None


def test_bad_amount_remains_unverified_instead_of_erasing_other_work(tmp_path):
    units,cache,_=fixture(tmp_path)
    sources,_=collect_sources(units,cache,set(cache))
    decision={'supported':True,'reason':'ok','missing':[], 'claims':[
        {'text':'律师核对草稿并协助递交申请。','evidence':[{'id':'S2','quote':sources[1]['text']}]},
        {'text':'已收10000元。','evidence':[{'id':'S1','quote':sources[0]['text']}]}]}
    kept=finalize_review('结案小结',decision,sources)
    assert '10000' not in kept['value'] and kept['missing']==['needs_source_review']


def test_numeric_substring_does_not_prove_an_amount():
    sources=[{'id':'S1','kind':'contract','text':'本案已收律师费10000元。'}]
    row={'claims':[{'text':'已收100元。','evidence':[{'id':'S1','quote':sources[0]['text']}]}], 'missing':[]}
    assert validate_candidate('结案小结',row,sources) is None


def test_absence_diagnostics_stay_outside_the_form_body(tmp_path):
    units,cache,_=fixture(tmp_path)
    sources,_=collect_sources(units,cache,set(cache))
    decision={'supported':True,'reason':'ok','missing':[], 'claims':[
        {'text':'公证处已出具公证书。','evidence':[{'id':'S2','quote':sources[1]['text']}]},
        {'text':'现有材料未见律师具体咨询记录。','evidence':[{'id':'S1','quote':sources[0]['text']}]}]}
    row=finalize_review('结案小结',decision,sources)
    assert row['value']=='公证处已出具公证书。' and row['missing']==['missing_work']
