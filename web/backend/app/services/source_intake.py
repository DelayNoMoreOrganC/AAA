"""Keep the provided intake approval intact; a filled replacement is not approval."""
from pathlib import Path
import os
import fitz

def original_intake_refs(units, manifest):
    scope={os.path.normcase(os.path.abspath(r['path'])):r for r in manifest or [] if r.get('path')}
    result=[]
    for u in units or []:
        if u.doc_type!='intake_approval' or u.catalog_seq!=1:continue
        row=scope.get(os.path.normcase(os.path.abspath(u.source_path)))
        if not row or not 0<=u.start_page<=u.end_page<row['pages']:raise ValueError('原始审批表来源范围不一致')
        result.append(dict(file_id=row['file_id'],filename=row.get('filename','原始审批表'),page=u.start_page+1,page_end=u.end_page+1))
    return result

def export_original_intake(units, output_dir, manifest):
    refs=original_intake_refs(units,manifest)
    if not refs:raise ValueError('未找到原始审批表')
    result=fitz.open()
    try:
        for u in units:
            if u.doc_type!='intake_approval' or u.catalog_seq!=1:continue
            with fitz.open(u.source_path) as source:result.insert_pdf(source,from_page=u.start_page,to_page=u.end_page)
        path=Path(output_dir)/'立案审批表_原件.pdf'
        result.save(path)
        return str(path)
    finally:result.close()
