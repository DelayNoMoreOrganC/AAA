"""Trusted output measurements, separate from confirmed business facts."""
from pathlib import Path
import json
import re
import time
import uuid

import fitz
from docx import Document

RENDERER_VERSION = "lawfirm-original-forms-v16-intake-date-convention"
COUNT_SCOPE = "整卷PDF总页数，含封面、目录、系统表"


def derived_page_count(total):
    if type(total) is not int or total <= 0:
        raise ValueError("整卷页数必须是正整数")
    return {"volume_page_count":total, "count_scope":COUNT_SCOPE, "renderer_version":RENDERER_VERSION}


def visible_derivation(task):
    from .delivery_state import has_delivery
    manifest = getattr(task, "artifacts", None) or {}
    if (not has_delivery(task)
            or not manifest.get("valid") or manifest.get("revision") != task.revision
            or manifest.get("source_version") != task.source_version):
        return {}
    data = manifest.get("derived_output") or {}
    return dict(data) if type(data.get("volume_page_count")) is int and data["volume_page_count"] > 0 else {}


def new_render_directory(work, revision, previous=None):
    directory = Path(work) / "results" / f"r{revision}" / ("render-" + uuid.uuid4().hex[:12])
    directory.mkdir(parents=True, exist_ok=False)
    if previous:
        (directory / "previous_generation.json").write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(directory)


def verify_cover_count(output_pdf, cover_docx, count, cover_pages):
    expected = f"{count}页"
    word = Document(cover_docx)
    # Read physical cells: merged grids expose duplicate logical cells and the
    # original cover has further fields after the page-count cell.
    matches = []
    for table in word.tables:
        for row in table._tbl.findall("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tr"):
            cells = row.findall("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tc")
            texts = ["".join(c.xpath(".//w:t/text()")) for c in cells]
            for index, text in enumerate(texts[:-1]):
                if "卷内页数" in re.sub(r"\s+", "", text):
                    matches.append(texts[index + 1])
    if len(matches) != 1 or re.sub(r"[\s\u200b\ufeff]+", "", matches[0]) != expected:
        raise RuntimeError("Word封面卷内页数与实际整卷不一致")
    with fitz.open(output_pdf) as document:
        if len(document) != count:
            raise RuntimeError("回填卷内页数后总页数未收敛，成果未发布")
        text = re.sub(r"[\s\u200b\ufeff]+", "", "".join(document[index].get_text() for index in range(cover_pages)))
        if not re.search(r"(?<!\d)" + re.escape(expected), text):
            raise RuntimeError("PDF封面未显示实际整卷页数")


def finalize_cover_count(analysis, organization_name, docx_paths, first_result, assemble, *, preview_only, log=print):
    """Exactly one second merge; never reextract facts or mutate analysis.fields."""
    from .system_docx_service import render_form_docx
    from .browser_pdf_service import render_form_pdf
    total = first_result.page_count
    derived = derived_page_count(total)
    started = time.monotonic()
    name = "档案卷宗"
    cover_path = analysis.generated_templates[name]
    cover_pages = None
    if preview_only:
        with fitz.open(cover_path) as document:
            cover_pages = len(document)
    render_form_docx(name, analysis.fields, organization_name, docx_paths[name], derived_output=derived)
    if preview_only:
        render_form_pdf(name, analysis.fields, organization_name, cover_path, log=log, derived_output=derived)
        with fitz.open(cover_path) as document:
            if len(document) != cover_pages:
                raise RuntimeError("回填卷内页数改变封面分页，成果未发布")
    result = assemble()
    if not result.success or result.page_count != total:
        raise RuntimeError("回填卷内页数后总页数未收敛，成果未发布")
    # Legacy Word conversion uses its own fixed cover budget; one cover page is
    # its established contract. Browser output is measured, never truncated.
    verify_cover_count(result.output_pdf, docx_paths[name], total, cover_pages or 1)
    derived.update(cover_pages=cover_pages or 1, assembly_passes=2,
                   finalization_seconds=round(time.monotonic()-started, 3))
    return result, derived
