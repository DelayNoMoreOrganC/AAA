"""Six fixed fictional raw files, real import conversion, deterministic recognition."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def analyze(paths,case_type,data):
    import fitz
    import archive_pipeline as pipeline
    from archive_catalog import get_catalog,catalog_item_for_doc_type
    from document_title_review import title_evidence
    from pdf_doc_locator import DocumentUnit
    from case_timeline import collect
    registry=json.loads((ROOT/'artifacts/civil-mixed-v62/registry.json').read_text(encoding='utf8'))['inputs']
    by_hash={r['sha256']:r for r in registry}
    transcript=json.loads((ROOT/'artifacts/civil-loan-v53/source-transcript.json').read_text(encoding='utf8'))
    if case_type!='civil' or len(paths)!=6:raise ValueError('Expected six fixed fictional inputs')
    units=[];cache={};seen=set()
    for value in paths:
        path=Path(value).resolve()
        if not path.is_relative_to(data):raise ValueError('Source outside fixture storage')
        metadata=json.loads((path.parent/'import.json').read_text(encoding='utf8'))
        original=(path.parent/metadata['original']).resolve()
        if original.parent!=path.parent:raise ValueError('Original outside import')
        sha=hashlib.sha256(original.read_bytes()).hexdigest()
        if sha not in by_hash or sha in seen:raise ValueError('Unknown or duplicate fictional input')
        seen.add(sha);row=by_hash[sha]
        with fitz.open(path) as pdf:
            if len(pdf)!=row['pages']:raise ValueError('Imported document page count changed: '+row['name'])
            # DOCX text comes from the real converted PDF. Scan/image text is
            # the fixed authored transcript, explicitly not OCR validation.
            for index,page in enumerate(pdf):
                text=page.get_text(sort=True)
                if row['kind'] in ('contract','evidence','summons','judgment'):
                    title,paragraphs=transcript[row['transcript_indices'][index]]
                    text=title+'\n'+'\n'.join(paragraphs)
                cache[(str(path),index+1)]=text
        title=title_evidence(cache[(str(path),1)],case_type='civil')
        if not title or not title['verified'] or title['doc_type']!=row['kind']:
            raise ValueError('Fictional title mismatch: '+row['name'])
        # This is a supplied recognition segmentation, not model accuracy.
        item=catalog_item_for_doc_type('civil',row['kind'])
        if item is None and row['kind']!='evidence':raise ValueError('Unmapped fixture document')
        units.append(DocumentUnit(len(units),row['kind'],0,row['pages']-1,title['title'],source_path=str(path),
            catalog_seq=item.seq if item else 7,confidence=.95))
    fields={'案号':'（2026）粤0999民初5301号','案件类别':'民事','委托人':'虚构星桥银行股份有限公司',
        '对方当事人':'虚构云禾科技有限公司、虚构林甲、虚构陈乙','案由':'金融借款合同纠纷',
        '律师事务所':'虚构明序律师事务所','承办律师':'虚构律师甲',
        '案件或项目名称':'虚构星桥银行股份有限公司诉虚构云禾科技有限公司、虚构林甲、虚构陈乙的金融借款合同纠纷',
        '_fixture_scope':'Six fixed fictional inputs; authored OCR and identity candidates; real DOCX/image conversion'}
    refs={}
    assert collect(fields,refs,[],page_cache=cache,allowed_sources=set(cache),document_units=units)==2
    fields['_provenance']=refs
    catalog=get_catalog('civil');found=pipeline.compute_found_seqs(catalog,units,{})|{r.seq for r in catalog if r.source=='system'}
    return pipeline.ArchiveAnalysis('civil',None,fields,{},units,found,
        pipeline.compute_missing_items('civil',catalog,found),source_paths=paths)
