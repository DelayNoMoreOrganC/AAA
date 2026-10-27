"""Fictional full-catalog inputs with deliberately over-split model page candidates."""
from pathlib import Path
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'artifacts/document-continuity-v73'
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from fixture_execution_v64 import ROWS,TRIAL,EXEC,CLIENT,OTHER


def build():
    import fitz
    BASE.mkdir(exist_ok=True)
    output=BASE/'虚构连续合同归档验收.pdf'
    if output.exists():raise ValueError('Do not overwrite fixture')
    with fitz.open(ROOT/'artifacts/civil-execution-v64/虚构金融借款全目录及终本.pdf') as original, fitz.open() as pdf:
        pdf.insert_pdf(original,from_page=0,to_page=5)
        for n,body in enumerate(['借款人虚构乙公司，贷款人虚构甲银行；借款本金1000元。','本页列示虚构还款约定和利息条款。','本页为虚构其他约定；不证明已签署或实际履行。'],1):
            page=pdf.new_page(width=595,height=842)
            text='借款合同\n合同编号：SYNTHETIC-73\n'+body+'\n完全虚构验收材料，无真实身份或印章。'
            assert page.insert_textbox(fitz.Rect(52,52,543,740),text,fontname='china-s',fontsize=14,lineheight=1.5)>=0
            page.insert_text((240,795),f'第{n}页 共3页',fontname='china-s',fontsize=12)
        pdf.insert_pdf(original,from_page=6,to_page=13)
        pdf.save(output)
    (BASE/'registry.json').write_text(json.dumps(dict(sha256=hashlib.sha256(output.read_bytes()).hexdigest(),pages=17)),encoding='utf8')


def analyze(paths,case_type,data):
    import fitz
    import archive_pipeline as pipeline
    from archive_catalog import get_catalog
    from document_title_review import review_visual_titles
    from pdf_doc_locator import DocumentUnit
    from source_fact_recall import recall_cached_source_facts
    from fact_evidence import validate_fact
    if case_type!='civil' or len(paths)!=1 or not Path(paths[0]).resolve().is_relative_to(data):raise ValueError('Fixture scope')
    if hashlib.sha256(Path(paths[0]).read_bytes()).hexdigest()!=json.loads((BASE/'registry.json').read_text())['sha256']:raise ValueError('Unknown input')
    with fitz.open(paths[0]) as pdf:texts=[p.get_text(sort=True) for p in pdf]
    rows=ROWS[:6]+[(7,'evidence','借款合同','')]*3+ROWS[6:]
    class Pages:
        def __init__(self):self.pages={f'p{i+1}':(paths[0],i) for i in range(len(texts))};self.reads=[]
        def read(self,key):self.reads.append(key);return texts[self.pages[key][1]]
    pages=Pages()
    raw=[dict(page_id=k,doc_type=rows[i][1],title=rows[i][2],confidence=.95,document_start=True,
        document_role='standard',procedure_stage='enforcement' if rows[i][1]=='execution' else 'trial') for i,k in enumerate(pages.pages)]
    decisions,audit=review_visual_titles(raw,pages,case_type='civil')
    units=[]
    for i,r in enumerate(decisions):
        if r['document_start']:units.append(DocumentUnit(len(units),r['doc_type'],i,i,r['title'],rows[i][0],paths[0],confidence=r['confidence']))
        else:units[-1].end_page=i
    assert [(u.start_page,u.end_page) for u in units if u.title=='借款合同']==[(6,8)]
    fields={'案号':TRIAL,'执行案号':EXEC,'案件类别':'民事','委托人':CLIENT,'对方当事人':OTHER,'案由':'金融借款合同纠纷',
        '律师事务所':'虚构明序律师事务所','承办律师':'虚构律师甲','案件或项目名称':'虚构甲银行诉虚构乙公司、虚构丙的金融借款合同纠纷'}
    cache={(paths[0],i+1):text for i,text in enumerate(texts)};refs={};conflicts=[];reviews=[]
    for field,value in [('委托人',CLIENT),('收费标准','基础代理费5000元，按实际回款金额另收2%。'),('案号',TRIAL)]:
        page=16 if field=='案号' else 2;text=cache[(paths[0],page)]
        assert validate_fact(field,value,text,text)
        fields[field]=value;refs[field]=[dict(value=value,quote=text,source_path=paths[0],page=page,method='visual_agent_local_evidence')]
    recall_cached_source_facts(fields,refs,conflicts,page_cache=cache,allowed_sources=set(cache),fact_review=reviews,document_units=units)
    fields.update(_provenance=refs,_field_conflicts=conflicts,_fact_review=reviews,
        _fixture_scope='Authored per-page classifications, actual continuity recheck and source recall; no real model')
    fields=pipeline.normalize_fields(fields,strict_evidence=True)
    # Production attaches classification metadata after field normalization.
    # Preserve structured audit records instead of sanitizing them as values.
    fields['_visual_classification_review']=audit
    catalog=get_catalog('civil');found=pipeline.compute_found_seqs(catalog,units,{})|{r.seq for r in catalog if r.source=='system'}
    result=pipeline.ArchiveAnalysis('civil',paths[0],fields,{},units,found,pipeline.compute_missing_items('civil',catalog,found),source_paths=paths)
    (data/'continuity-observed.json').write_text(json.dumps(dict(before_units=len(raw),after_units=len(units),reads=len(pages.reads),merged_pages=pages.title_review_metrics['merged_continuation_pages'],new_cloud_calls=0),indent=2),encoding='utf8')
    return result

if __name__=='__main__':build()
