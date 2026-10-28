"""Private evidence bindings and actual form projection, offline transport."""
import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace as NS

from app.core.v4_bridge import init_v4_path
init_v4_path()
from form_synthesis import generate, KEY
from form_drafts import derive_form_drafts
from app.services.field_assurance import field_assurance
from app.services.preview_fields import build_preview
from app.services.outcome_state import _has_current_result


def make(tmp_path):
    source=tmp_path/'fictional.pdf'
    text='办理记录：律师核对草稿并协助递交申请。公证处已出具公证书。'
    source.write_bytes(text.encode())
    units=[NS(source_path=str(source),start_page=0,end_page=0,doc_type='legal_work',doc_id=1,confidence=.95)]
    cache={(str(source),1):text}
    class Client:
        def complete(self,messages):
            payload=json.loads(messages[-1]['content'])
            fields={k:{'claims':[{'text':v,'evidence':[{'id':'S1','quote':text}]}],'missing':[]}
                    for k,v in [('结案小结','律师核对草稿并协助递交申请，公证处已出具公证书。'),
                                ('审（办）结果','公证处已出具公证书。')]}
            if 'candidates' in payload:
                fields={k:dict(v,supported=True,reason='ok') for k,v in fields.items()}
            return {'fields':fields}
    fields={'案件类别':'非诉'};provenance={}
    status=generate(Client(),fields,provenance,[],units,cache,set(cache),case_type='nonlit')
    fields.update(_provenance=provenance,_form_synthesis_status=status)
    manifest=[{'file_id':'fictional','path':str(source),'pages':1,'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}]
    return fields,manifest,units


def test_real_form_projection_keeps_distinct_summaries_with_clickable_source(tmp_path):
    fields,manifest,units=make(tmp_path)
    fields=derive_form_drafts(fields,units,source_manifest=manifest)
    for form,key in [('结案报告表','结案小结'),('档案卷宗','审（办）结果')]:
        preview=build_preview(form,fields,source_manifest=manifest)
        row=next(r for r in preview['fields'] if r['key']==key)
        assert row['value']==fields[key]
        assurance=field_assurance(key,fields[key],fields,source_manifest=manifest)
        assert assurance['status']=='derived_draft'
        assert assurance['anchors']==[{'file_id':'fictional','page':1}]
    assert _has_current_result(fields,{},manifest,[]) is True


def test_material_change_invalidates_provenance_and_does_not_fill_from_other_column(tmp_path):
    fields,manifest,units=make(tmp_path)
    changed=deepcopy(manifest);changed[0]['sha256']='new-material'
    assert field_assurance('结案小结',fields['结案小结'],fields,source_manifest=changed)['status']=='unverified'
    assert _has_current_result(fields,{},changed,[]) is False
    fields=derive_form_drafts(fields,units,source_manifest=changed)
    preview=build_preview('结案报告表',fields,source_manifest=changed)
    assert next(r for r in preview['fields'] if r['key']=='结案小结')['value']==''


def test_missing_outcome_does_not_alias_closure_narrative(tmp_path):
    fields,manifest,_=make(tmp_path)
    fields.pop('审（办）结果')
    preview=build_preview('档案卷宗',fields,source_manifest=manifest)
    assert next(r for r in preview['fields'] if r['key']=='审（办）结果')['value']==''
