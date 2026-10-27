"""Original forms remain source pages, with independent types and no invented approvals."""
import fitz,pytest
from archive_catalog import catalog_item_for_doc_type
from document_title_review import title_evidence
from pdf_doc_locator import DocumentUnit
from pdf_archive_merger import build_full_archive

@pytest.mark.parametrize('kind,title,body',[
    ('closure_report','结案报告表','委托人：虚构甲\n结案小结：双方达成协议\n承办律师：虚构律师'),
    ('service_list','律师所送达材料清单','当事人：虚构甲\n文件名称：民事判决书\n核收人：'),
    ('quality_card','律师办案质量监督卡','承办律师：虚构甲\n是否按时办理？\n客户评价：'),
    ('client_notice','委托人须知','委托人应知晓法律风险\n承办律师依委托合同办理'),
])
def test_standalone_form_requires_context(kind,title,body):
    evidence=title_evidence(title+'\n'+body,case_type='civil')
    assert evidence['verified'] and evidence['doc_type']==kind
    evidence=title_evidence(title+'\n无其他内容',case_type='civil')
    assert not evidence['verified']
    evidence=title_evidence('证据材料清单\n附件名称：'+title+'\n'+body,case_type='civil')
    assert evidence['doc_type']=='evidence'

def test_court_execution_notice_is_not_lawfirm_closure_form():
    evidence=title_evidence('虚构市人民法院\n执行结案通知书\n(2026)粤0604执123号\n本案已执行完毕。',case_type='civil')
    assert evidence['doc_type']=='execution'

@pytest.mark.parametrize('case_type',['civil','admin','criminal','nonlit','counsel'])
@pytest.mark.parametrize('mode',['draft','body'])
def test_original_forms_preserved_once_with_catalog_links_and_source_pixels(tmp_path,case_type,mode):
    source=tmp_path/'source.pdf';cover=tmp_path/'cover.pdf';generated={}
    kinds=['intake_approval','service_list','closure_report']
    with fitz.open() as d:
        for label in kinds:
            p=d.new_page();p.insert_text((72,72),'ORIGINAL_'+label)
            p.draw_rect(fitz.Rect(70,110,230,160),color=(1,0,0))
        d.save(source)
    for name in ('档案卷宗','立案审批表','送达材料清单','结案报告表'):
        path=tmp_path/(name+'.pdf')
        with fitz.open() as d:
            d.new_page().insert_text((72,72),'COVER' if name=='档案卷宗' else 'UNWANTED_REPLACEMENT');d.save(path)
        generated[name]=str(path)
    units=[DocumentUnit(i,kind,i,i,source_path=str(source),catalog_seq=catalog_item_for_doc_type(case_type,kind).seq) for i,kind in enumerate(kinds)]
    output=tmp_path/'archive.pdf'
    result=build_full_archive(case_type,str(source),generated,units,{},[],str(output),
                             use_original_catalog=True,pagination_mode=mode,log=lambda *_:None)
    assert result.success and result.original_pages_included==3
    with fitz.open(output) as archive,fitz.open(source) as original:
        text=''.join(p.get_text() for p in archive)
        assert 'UNWANTED_REPLACEMENT' not in text
        for i,kind in enumerate(kinds):
            pages=[p for p in archive if 'ORIGINAL_'+kind in p.get_text()]
            assert len(pages)==1
            assert pages[0].get_pixmap(clip=original[i].rect).samples==original[i].get_pixmap().samples
            assert pages[0].get_label()==(str(i+1) if mode=='body' else '')
            assert any(link['page']==pages[0].number for p in archive for link in p.get_links())


@pytest.mark.parametrize('present',[(),('quality_card',),('client_notice',),('quality_card','client_notice')])
@pytest.mark.parametrize('mode',['draft','body'])
def test_quality_components_preserve_original_pages_and_only_add_missing(tmp_path,present,mode):
    source=tmp_path/'source.pdf';generated={}
    kinds=list(present) or ['evidence']
    with fitz.open() as doc:
        for kind in kinds:
            doc.new_page().insert_text((72,72),'ORIGINAL_'+kind)
        doc.save(source)
    missing=[kind for kind in ('quality_card','client_notice') if kind not in present]
    for name,labels in [('档案卷宗',['COVER']),('质量监督卡',['GENERATED_'+kind for kind in missing])]:
        if not labels:continue
        path=tmp_path/(name+'.pdf')
        with fitz.open() as doc:
            for label in labels:doc.new_page().insert_text((72,72),label)
            doc.save(path)
        generated[name]=str(path)
    units=[DocumentUnit(i,kind,i,i,source_path=str(source),catalog_seq=7 if kind=='evidence' else catalog_item_for_doc_type('civil',kind).seq)
           for i,kind in enumerate(kinds)]
    result=build_full_archive('civil',str(source),generated,units,{},[],str(tmp_path/'result.pdf'),
        use_original_catalog=True,pagination_mode=mode,log=lambda *_:None)
    assert result.success and result.original_pages_included==len(kinds)
    with fitz.open(result.output_pdf) as document,fitz.open(source) as original:
        text=''.join(p.get_text() for p in document)
        for i,kind in enumerate(kinds):
            pages=[p for p in document if 'ORIGINAL_'+kind in p.get_text()]
            assert len(pages)==1
            assert pages[0].get_pixmap(clip=original[i].rect).samples==original[i].get_pixmap().samples
        for kind in ('quality_card','client_notice'):
            assert text.count('GENERATED_'+kind)==(kind not in present)
        card=next(p.number for p in document if 'quality_card' in p.get_text())
        notice=next(p.number for p in document if 'client_notice' in p.get_text())
        assert card<notice
