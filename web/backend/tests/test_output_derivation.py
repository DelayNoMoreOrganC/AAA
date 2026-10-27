from pathlib import Path
from types import SimpleNamespace
import json

from docx import Document
from docx.oxml.ns import qn

from app.services.output_derivation import derived_page_count, new_render_directory, visible_derivation
from app.services.system_docx_service import render_form_docx
from app.services.browser_pdf_service import render_form_html
from app.services.task_sources import fields_digest
from app.services import output_export


def test_count_is_same_read_only_content_and_never_changes_business_digest(tmp_path):
    fields = {"委托人":"虚构甲", "_preview_custom_values":{"档案卷宗":{"p0-b0-r13-c3":"999页"}}}
    before = fields_digest(fields, "catalog")
    derived = derived_page_count(107)
    docx = render_form_docx("档案卷宗", fields, "虚构律所", str(tmp_path/"cover.docx"), derived_output=derived)
    rows = [row for table in Document(docx).tables for row in table.rows if any("卷内页数" in cell.text for cell in row.cells)]
    assert len(rows) == 1 and rows[0].cells[-1].text.replace("\u200b", "") == "107 页"
    assert not rows[0].cells[-1]._tc.findall(".//"+qn("w:permStart"))
    html = render_form_html("档案卷宗", fields, "虚构律所", derived_output=derived)
    assert "107 页" in html and "999页" not in html
    assert "生成后计算" in render_form_html("档案卷宗", fields, "虚构律所")
    assert fields_digest(fields,"catalog") == before


def test_new_generations_and_exports_do_not_overwrite_old_revision(tmp_path, monkeypatch):
    work = tmp_path/"task"
    old = work/"results"/"r2"
    old.mkdir(parents=True)
    (old/"old.pdf").write_bytes(b"old-pdf")
    first = Path(new_render_directory(work,2,{"result_dir":str(old)}))
    second = Path(new_render_directory(work,2,{"result_dir":str(first)}))
    assert first != second and (old/"old.pdf").read_bytes() == b"old-pdf"
    assert json.loads((first/"previous_generation.json").read_text(encoding="utf-8"))["result_dir"] == str(old)
    for folder in (first,second):
        (folder/"result.pdf").write_bytes(folder.name.encode())
    monkeypatch.setattr(output_export,"output_directory",lambda:tmp_path/"export")
    import workstation_security
    monkeypatch.setattr(workstation_security,"protect_directory",lambda *_:None)
    one=Path(output_export.export_archive(first,"org","case",1))
    two=Path(output_export.export_archive(second,"org","case",1))
    assert one != two and one.parent.name == two.parent.name == "r2"
    assert (one/"result.pdf").read_bytes() == first.name.encode()


def test_preview_derivation_is_not_reused_after_edit_or_for_another_revision():
    manifest={"valid":True,"revision":2,"source_version":"v", "derived_output":derived_page_count(12)}
    task=SimpleNamespace(status="done",artifacts=manifest,revision=2,source_version="v")
    assert visible_derivation(task)["volume_page_count"] == 12
    task.status="awaiting_review"
    assert visible_derivation(task) == {}
    task.status="done";task.revision=3
    assert visible_derivation(task) == {}
