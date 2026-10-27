"""Fictional five-file dismissal case with a pre-existing approval form.

Recognition is an explicitly authored adapter, not OCR/model accuracy evidence.
Imported DOCX conversion, source recall, original-form policy and output are real.
"""
import hashlib,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'artifacts/dismissal-original-v79'
CLIENT='虚构星桥银行股份有限公司'
OPPONENTS='虚构云禾科技有限公司、虚构林甲、虚构陈乙'
CASE='（2026）粤0999民初5301号'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def build():
    import fitz
    BASE.mkdir(exist_ok=False)
    old=ROOT/'artifacts/civil-mixed-v62'
    registry=json.loads((old/'registry.json').read_text(encoding='utf8'))
    rows=[r for r in registry['inputs'] if r['kind'] not in ('summons','judgment')]
    assert len(rows)==4
    for row in rows:
        assert sha(old/row['name'])==row['sha256']
        shutil.copy2(old/row['name'],BASE/row['name'])
    p=BASE/'05-民事裁定书_驳回起诉.pdf'
    text=('虚构市示例区人民法院\n民事裁定书\n'+CASE+'\n'
          '原告：'+CLIENT+'。\n被告：'+OPPONENTS+'。\n'
          '本案为金融借款合同纠纷。本院经审查认为本案不符合起诉条件。\n'
          '裁定如下：驳回原告'+CLIENT+'的起诉。\n'
          '如不服本裁定，可依法提起上诉。\n裁判日期：2026年6月30日。\n'
          '完全虚构验收材料，无真实身份或印章。')
    with fitz.open() as d:
        page=d.new_page(width=595,height=842)
        assert page.insert_textbox(fitz.Rect(52,52,543,760),text,fontname='china-s',fontsize=14,lineheight=1.5)>=0
        d.save(p)
    rows.append(dict(name=p.name,kind='ruling',pages=1,sha256=sha(p)))
    (BASE/'registry.json').write_text(json.dumps(dict(fictional=True,inputs=rows),ensure_ascii=False,indent=2),encoding='utf8')
    expected=dict(outcome='驳回原告'+CLIENT+'的起诉',source_pages=8,editable_words=4,archive_pages=14,
        preserved_original='06-已有立案审批表.docx',catalog_rows=17,ruling_catalog_seq=14,
        forbidden_outcomes=['驳回全部诉讼请求','驳回其他诉讼请求','法院判决','已回款','终结本次执行程序','到庭参加诉讼'])
    (BASE/'expected.json').write_text(json.dumps(expected,ensure_ascii=False,indent=2),encoding='utf8')

def analyze(paths,case_type,data):
    import fitz
    import archive_pipeline as pipeline
    from archive_catalog import get_catalog,catalog_item_for_doc_type
    from document_title_review import title_evidence
    from pdf_doc_locator import DocumentUnit
    from source_fact_recall import recall_cached_source_facts
    from fact_evidence import validate_fact
    rows=json.loads((BASE/'registry.json').read_text(encoding='utf8'))['inputs']
    by_hash={r['sha256']:r for r in rows}
    transcript=json.loads((ROOT/'artifacts/civil-loan-v53/source-transcript.json').read_text(encoding='utf8'))
    if case_type!='civil' or len(paths)!=5:raise ValueError('Five fixed fictional inputs required')
    units=[];cache={};seen=set()
    for value in paths:
        path=Path(value).resolve()
        if not path.is_relative_to(data):raise ValueError('Outside isolated fixture storage')
        metadata=json.loads((path.parent/'import.json').read_text(encoding='utf8'))
        original=(path.parent/metadata['original']).resolve()
        if original.parent!=path.parent:raise ValueError('Outside import')
        digest=sha(original)
        if digest not in by_hash or digest in seen:raise ValueError('Unknown or duplicate material')
        seen.add(digest);row=by_hash[digest]
        with fitz.open(path) as pdf:
            assert len(pdf)==row['pages']
            for index,page in enumerate(pdf):
                text=page.get_text(sort=True)
                if row['kind'] in ('contract','evidence'):
                    heading,paragraphs=transcript[row['transcript_indices'][index]]
                    text=heading+'\n'+'\n'.join(paragraphs)
                cache[(str(path),index+1)]=text
        title=title_evidence(cache[(str(path),1)],case_type='civil')
        assert title and title['verified'] and title['doc_type']==row['kind'],row['name']
        item=catalog_item_for_doc_type('civil',row['kind'])
        # Generic evidence has no one-to-one document-type mapping. This
        # authored evidence list and its attachments belong to civil slot 7.
        assert item or row['kind']=='evidence'
        units.append(DocumentUnit(len(units),row['kind'],0,row['pages']-1,title['title'],source_path=str(path),catalog_seq=item.seq if item else 7,confidence=.95))
    fields={'案件类别':'民事','案号':CASE,'委托人':CLIENT,'对方当事人':OPPONENTS,'案由':'金融借款合同纠纷',
        '律师事务所':'虚构明序律师事务所','承办律师':'虚构律师甲'}
    contract=next(u for u in units if u.doc_type=='contract');text=cache[(contract.source_path,1)]
    assert validate_fact('委托人',CLIENT,text,text)
    refs={'委托人':[dict(value=CLIENT,quote=text,source_path=contract.source_path,page=1,method='visual_agent_local_evidence')]}
    conflicts=[];review=[]
    metrics=recall_cached_source_facts(fields,refs,conflicts,page_cache=cache,allowed_sources=set(cache),fact_review=review,document_units=units)
    fields.update(_provenance=refs,_field_conflicts=conflicts,_fact_review=review,_source_fact_recall=metrics)
    fields=pipeline.normalize_fields(fields,strict_evidence=True)
    fields['_fixture_scope']='Authored segmentation/identity/scan transcript; actual DOCX conversion and complete source recall; no model'
    catalog=get_catalog('civil');found=pipeline.compute_found_seqs(catalog,units,{})|{r.seq for r in catalog if r.source=='system'}
    return pipeline.ArchiveAnalysis('civil',None,fields,{},units,found,pipeline.compute_missing_items('civil',catalog,found),source_paths=paths)

if __name__=='__main__':build()
