from types import SimpleNamespace as NS
from copy import deepcopy
import fitz,pytest
from app.services.source_intake import original_intake_refs,export_original_intake
from app.services.form_fill_audit import build_form_fill_audit

def test_original_approval_export_has_only_scoped_original_pages(tmp_path):
    path=tmp_path/'input.pdf'
    with fitz.open() as d:
        for s in ('ORIGINAL APPROVAL','OTHER SOURCE'):d.new_page().insert_text((40,50),s)
        d.save(path)
    units=[NS(doc_type='intake_approval',catalog_seq=1,start_page=0,end_page=0,source_path=str(path)),
           NS(doc_type='evidence',catalog_seq=7,start_page=1,end_page=1,source_path=str(path))]
    scope=[dict(file_id='f',path=str(path),pages=2)]
    refs=original_intake_refs(units,scope)
    assert refs[0]['page']==1 and refs[0]['page_end']==1
    output=export_original_intake(units,tmp_path,scope)
    with fitz.open(output) as d,fitz.open(path) as source:
        assert len(d)==1 and d[0].get_pixmap().samples==source[0].get_pixmap().samples
    rows=build_form_fill_audit({'_source_intake_approval':refs},scope)
    assert not any(r['template']=='立案审批表' for r in rows)
    with pytest.raises(ValueError):original_intake_refs(units,[])
    bad=deepcopy(units);bad[0].end_page=2
    with pytest.raises(ValueError):original_intake_refs(bad,scope)
