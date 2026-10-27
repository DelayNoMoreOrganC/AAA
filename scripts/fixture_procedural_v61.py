"""Only four hash-locked fictional PDFs; deterministic UI acceptance adapter."""
import hashlib
from pathlib import Path

FIXTURES={
 '4d69ce0fd59485c755c72621c6b5cc0b676a57675fd357b470f1ce63510d408f':('partial-withdraw','5901','ruling'),
 '0362eea6524249ef61918929993d6bf20dfdba1d843b9e7311adedf8cb9b1bc5':('withdraw-refused','5901','ruling'),
 '4551aeb7ef9cfcfdcf2d74a4701be1fe5243a18aa7ac13725cba42fa86351db6':('all-rejected','6001','judgment'),
 '3e058f05c756191f6cf85e3e33dbb920d697dc98c969b0755051ef77da9e9a3f':('partial-award','6001','judgment'),
}

def analyze(paths,case_type,data):
    import fitz
    import archive_pipeline as pipeline
    from archive_catalog import get_catalog,catalog_item_for_doc_type
    from document_title_review import title_evidence
    from pdf_doc_locator import DocumentUnit
    from case_timeline import collect
    if case_type!='civil' or len(paths)!=1 or not Path(paths[0]).resolve().is_relative_to(data):
        raise ValueError('Only one fixed fictional civil PDF is permitted')
    digest=hashlib.sha256(Path(paths[0]).read_bytes()).hexdigest()
    if digest not in FIXTURES:raise ValueError('Not a registered fictional source')
    label,number,kind=FIXTURES[digest]
    with fitz.open(paths[0]) as pdf:
        texts=[page.get_text() for page in pdf]
    assert len(texts)==2
    units=[]
    for i,text in enumerate(texts):
        title=title_evidence(text,case_type=case_type)
        assert title['verified'] and title['doc_type']==('contract' if i==0 else kind)
        units.append(DocumentUnit(i,title['doc_type'],i,i,title['title'],source_path=paths[0],
            catalog_seq=catalog_item_for_doc_type(case_type,title['doc_type']).seq,confidence=.95))
    # Identity candidates are authored fixture values, not model-derived facts.
    # Rebuild the real source-bound synthesis from the actual uploaded text.
    fields={'案号':f'(2026)粤0999民初{number}号','案件类别':'民事','委托人':'虚构甲银行',
        '对方当事人':'虚构乙公司、虚构丙','案由':'金融借款合同纠纷','律师事务所':'虚构甲律师事务所',
        '案件或项目名称':'虚构甲银行诉虚构乙公司、虚构丙的金融借款合同纠纷',
        '_fixture_scope':f'Fictional identity candidates + title-rule segmentation; no OCR/model: {label}'}
    refs={};cache={(paths[0],i+1):text for i,text in enumerate(texts)}
    assert collect(fields,refs,[],page_cache=cache,allowed_sources=set(cache),document_units=units)==2
    fields['_provenance']=refs
    catalog=get_catalog(case_type)
    found=pipeline.compute_found_seqs(catalog,units,{})|{item.seq for item in catalog if item.source=='system'}
    return pipeline.ArchiveAnalysis(case_type,paths[0],fields,{},units,found,
        pipeline.compute_missing_items(case_type,catalog,found),source_paths=paths)
