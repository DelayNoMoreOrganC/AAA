from types import SimpleNamespace as NS
import pytest
from app.services.source_forms import original_form_refs,original_form_sources,quality_component_refs,form_fields_preserved

def unit(kind='closure_report',seq=18,start=0,end=0):
    return NS(doc_type=kind,catalog_seq=seq,start_page=start,end_page=end,source_path='synthetic.pdf')
SCOPE=[dict(file_id='s',path='synthetic.pdf',pages=3)]

def test_source_forms_are_bound_to_case_catalog_and_current_manifest():
    assert original_form_refs([unit()],SCOPE,'civil')['结案报告表'][0]['file_id']=='s'
    assert original_form_refs([unit()],SCOPE,'nonlit')=={}
    assert original_form_refs([unit(seq=10)],SCOPE,'nonlit')['结案报告表']
    assert original_form_refs([unit(kind='execution')],SCOPE,'civil')=={}
    with pytest.raises(ValueError):original_form_refs([unit()],[], 'civil')

@pytest.mark.parametrize('start,end',[(True,1),(0,3),(-1,0),(2,1)])
def test_invalid_range_is_not_allowed_to_suppress_generated_form(start,end):
    with pytest.raises(ValueError):original_form_refs([unit(start=start,end=end)],SCOPE,'civil')

def test_overlapping_form_pages_are_not_silently_exported_twice():
    with pytest.raises(ValueError):original_form_refs([unit(end=1),unit('service_list',17,start=1,end=2)],SCOPE,'civil')

def test_legacy_intake_projection_remains_supported_but_cannot_suppress_other_forms():
    fields={'_source_intake_approval':[dict(file_id='s',page=1,page_end=1)]}
    assert original_form_sources(fields,'立案审批表')
    assert not original_form_sources(fields,'结案报告表')


@pytest.mark.parametrize('kinds',[(),('quality_card',),('client_notice',),('quality_card','client_notice')])
def test_combined_form_requires_both_component_sources(kinds):
    units=[unit(kind,16,start=i,end=i) for i,kind in enumerate(kinds)]
    complete=original_form_refs(units,SCOPE,'civil')
    parts=quality_component_refs(units,SCOPE,'civil')
    assert ('质量监督卡' in complete)==(len(kinds)==2)
    assert [r['component'] for r in parts]==list(kinds)
    fields={'_original_forms':complete,'_original_form_components':{'质量监督卡':parts}}
    assert form_fields_preserved(fields,'质量监督卡')==('quality_card' in kinds)


def test_components_cannot_claim_the_same_source_page():
    with pytest.raises(ValueError,match='重叠'):
        original_form_refs([unit('quality_card',16),unit('client_notice',16)],SCOPE,'civil')
