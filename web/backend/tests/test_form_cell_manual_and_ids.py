from app.services.preview_fields import build_preview
from app.services.form_fill_audit import build_form_fill_audit
from app.services.original_template_service import fill_original_docx, NS
from zipfile import ZipFile
from lxml import etree as ET


def values(name, fields):
    return {v['key']:v['value'] for v in build_preview(name,fields)['fields']}


def test_reference_satisfaction_is_not_generated_client_feedback():
    fields={'案件类别':'民事','委托人对服务质量意见':'满意'}
    assert values('结案报告表',fields)['委托人对服务质量意见']==''
    rows=build_form_fill_audit(fields,[])
    client=next(r for r in rows if r['field']=='委托人对服务质量意见')
    assert client['gap']['code']=='human_record'
    assert all(r['value']=='' for r in rows if r['status']=='manual_area')
    assert fields['委托人对服务质量意见']=='满意'


def test_internal_numbers_are_reserved_blank_but_court_numbers_remain():
    fields={'合同号':'[2026]虚构民字1号','案号':'（2026）粤0604民初99号'}
    for form in ('质量监督卡','送达材料清单'):
        assert values(form,fields)['合同号']==''
        assert values(form,{'案号':fields['案号']})['合同号']==''
    assert values('档案卷宗',fields)['法院收案号']==fields['案号']
    assert values('档案卷宗',fields)['合同号']==''
    assert values('立案审批表',fields)['合同号']==''


def test_fee_and_dates_print_only_evidenced_or_explicitly_confirmed_values():
    f={'收费标准':'基础代理费5000元，按实际回款金额另收5%。','结案日期':'2026年10月28日'}
    assert values('立案审批表',f)['收费标准']==''
    assert values('结案报告表',f)['结案日期']==''
    assert f['收费标准']  # Presentation cannot erase retained evidence/history.
    f['_provenance']={'收费标准':[{'method':'human','value':f['收费标准']}],
                      '结案日期':[{'method':'human','value':f['结案日期']}]}
    assert values('立案审批表',f)['收费标准']==f['收费标准']
    assert values('结案报告表',f)['结案日期']==f['结案日期']
    f['_field_conflicts']=[{'field':'收费标准','resolved':False}]
    assert values('立案审批表',f)['收费标准']==''


def test_unambiguous_literal_fee_and_dates_and_optional_blank_diagnosis():
    f={'收费标准':'5000元','收案日期':'2026年1月2日',
       '_provenance':{'收费标准':[{'method':'local_agent','value':'5000元','quote':'委托代理合同。收费标准：5000元。'}],
                      '收案日期':[{'method':'local_agent','value':'2026年1月2日','quote':'立案审批表。收案日期：2026年1月2日。'}]}}
    assert values('立案审批表',f)['收费标准']=='5000元'
    assert values('档案卷宗',f)['收案日期']=='2026年1月2日'
    assert values('立案审批表',f)['立案审批日期']==''  # Receipt date is not approval date.
    for r in build_form_fill_audit({},[]):
        if r['field'] in ('合同号','收费标准','收案日期','结案日期','立案审批日期'):
            assert r['gap']['action']=='retain'


def test_generated_docx_keeps_manual_cells_blank_and_signature_regions(tmp_path):
    f={'案件类别':'民事','委托人对服务质量意见':'满意','结案小结':'虚构案例的工作摘要。'}
    dest=tmp_path/'form.docx'
    fill_original_docx('结案报告表',f,'',dest)
    root=ET.fromstring(ZipFile(dest).read('word/document.xml'))
    assert '满意' not in ''.join(root.xpath('//w:t/text()',namespaces=NS))
    cells=root.xpath('//w:body/w:tbl/w:tr[5]/w:tc[2]',namespaces=NS)
    assert not ''.join(cells[0].xpath('.//w:t/text()',namespaces=NS)).strip('\u200b ')
    assert root.xpath('//w:permStart',namespaces=NS)  # Editable form, not a flattened image.
