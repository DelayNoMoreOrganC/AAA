"""Editable Word forms built from the same layout and values as browser PDF.

No Office automation, HTML conversion, network access, or model calls are used.
Word's read-only protection permits edits only inside the explicitly marked
field ranges; this is an editing aid, not cryptographic tamper protection.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from .analysis_snapshot import SYSTEM_TEMPLATE_NAMES
from .form_layouts import FORM_LAYOUTS, form_title
from .preview_fields import build_preview, sanitize_preview_custom_values, sanitize_preview_styles

_ALIGN = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
          "right": WD_ALIGN_PARAGRAPH.RIGHT, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY}


def _font(run, size=10.5, style=None):
    style = style or {}
    family = style.get("fontFamily", "SimSun")
    run.font.name = family
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), family)
    requested = str(style.get("fontSize", ""))
    match = re.fullmatch(r"([\d.]+)(pt|px)", requested)
    if match:
        size = float(match.group(1)) * (0.75 if match.group(2) == "px" else 1)
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor.from_string(style.get("color", "#000000").lstrip("#"))
    run.bold = style.get("fontWeight") == "bold"
    run.italic = style.get("fontStyle") == "italic"
    run.underline = style.get("textDecoration") == "underline"


def _paragraph(document, text="", *, size=10.5, align="left", after=0, before=0, title=False):
    p = document.add_paragraph(style="Title" if title else None)
    p.alignment = _ALIGN.get(align, WD_ALIGN_PARAGRAPH.LEFT)
    p.paragraph_format.space_before = Mm(before)
    p.paragraph_format.space_after = Mm(after)
    p.paragraph_format.line_spacing = 1.25
    p.paragraph_format.keep_with_next = title
    _font(p.add_run(text), size)
    return p


def _editable_run(p, text, identifier, *, size=10.5, style=None):
    start = OxmlElement("w:permStart")
    start.set(qn("w:id"), str(identifier))
    start.set(qn("w:edGrp"), "everyone")
    p._p.append(start)
    # A zero-width insertion target keeps empty fields editable without adding
    # invented placeholder facts to the visible document.
    run = p.add_run(str(text or "") or "\u200b")
    _font(run, size, style)
    end = OxmlElement("w:permEnd")
    end.set(qn("w:id"), str(identifier))
    p._p.append(end)
    if style and style.get("textAlign") in _ALIGN:
        p.alignment = _ALIGN[style["textAlign"]]


def _new_document():
    document = Document()
    # Some python-docx distributions ship a styled Title with a blue rule.
    # Existing legal forms have plain black headings, so remove inherited rules.
    for border in list(document.styles.element.xpath(".//w:pBdr")):
        border.getparent().remove(border)
    section = document.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.top_margin, section.bottom_margin = Mm(17), Mm(16)
    section.left_margin = section.right_margin = Mm(20)
    normal = document.styles["Normal"]
    normal.font.name = "SimSun"
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = RGBColor(0, 0, 0)
    normal._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "SimSun")
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.line_spacing = 1.25
    protection = OxmlElement("w:documentProtection")
    protection.set(qn("w:edit"), "readOnly")
    protection.set(qn("w:enforcement"), "1")
    document.settings.element.append(protection)
    document.core_properties.author = "GD"
    document.core_properties.last_modified_by = "GD"
    document.core_properties.comments = "由已确认字段生成；固定内容受编辑保护，填写区域允许修改。"
    return document


def _lines(value):
    if isinstance(value, list):
        return [str(v or "") for v in value]
    value = str(value or "")
    return value.splitlines() if "\n" in value or "\r" in value else [v.strip() for v in re.split(r"[、，,；;]+", value)]


def _render_table(document, block, page_index, block_index, values, styles, custom, counter):
    columns = block["columns"]
    table = document.add_table(rows=len(block["rows"]), cols=len(columns))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    total = sum(columns)
    for column, width in zip(table.columns, columns):
        column.width = Mm(170 * width / total)
    properties = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        border = OxmlElement("w:" + side)
        for name, value in (("val", "single"), ("sz", "6"), ("color", "000000")):
            border.set(qn("w:" + name), value)
        borders.append(border)
    properties.append(borders)
    for row_index, definition in enumerate(block["rows"]):
        row = table.rows[row_index]
        # Word/LibreOffice add cell margins to the minimum row height, whereas
        # the browser's border-box row height already includes those margins.
        row.height = Mm(max(4, float(definition["height"]) - 2.2))
        row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        col = 0
        for cell_index, definition_cell in enumerate(definition["cells"]):
            span = int(definition_cell.get("colspan", 1))
            cell = row.cells[col]
            if span > 1:
                cell = cell.merge(row.cells[col + span - 1])
            cell.width = Mm(170 * sum(columns[col:col + span]) / total)
            col += span
            cell.vertical_alignment = (WD_CELL_VERTICAL_ALIGNMENT.TOP if "top-cell" in definition_cell.get("className", "")
                                       else WD_CELL_VERTICAL_ALIGNMENT.CENTER)
            margins = OxmlElement("w:tcMar")
            for side, twips in (("top", "62"), ("bottom", "62"), ("left", "85"), ("right", "85")):
                margin = OxmlElement("w:" + side)
                margin.set(qn("w:w"), twips)
                margin.set(qn("w:type"), "dxa")
                margins.append(margin)
            cell._tc.get_or_add_tcPr().append(margins)
            p = cell.paragraphs[0]
            p.alignment = _ALIGN.get(definition_cell.get("align", "left"), WD_ALIGN_PARAGRAPH.LEFT)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.05 if "vertical-label" in definition_cell.get("className", "") else 1.25
            key = f"p{page_index}-b{block_index}-r{row_index}-c{cell_index}"
            field = definition_cell.get("field")
            lines_field = definition_cell.get("linesField")
            if definition_cell.get("prefix"):
                _font(p.add_run(definition_cell["prefix"]))
            if definition_cell.get("derived"):
                count = values.get("__derived_output__", {}).get(definition_cell["derived"])
                _font(p.add_run(str(count) + definition_cell.get("suffix", "") if type(count) is int and count > 0 else "生成后计算"), size=9)
            elif field or lines_field:
                value = values.get(field, "")
                style_key = f"field:{field}"
                if lines_field:
                    index = int(definition_cell.get("lineIndex", 0))
                    line_values = _lines(values.get(lines_field, ""))
                    value = ("\n".join(line_values[index:]) if definition_cell.get("remainingLines")
                             else line_values[index] if index < len(line_values) else "")
                    style_key = f"line:{lines_field}:{index}"
                counter[0] += 1
                _editable_run(p, value, counter[0], style=styles.get(style_key))
            elif definition_cell.get("organizationName"):
                _font(p.add_run(values.get("__organization__", "")))
            else:
                fixed = definition_cell.get("text", "")
                _font(p.add_run(fixed))
                if definition_cell.get("allowCustomInput") or not fixed.strip():
                    if fixed:
                        p.add_run().add_break()
                    counter[0] += 1
                    _editable_run(p, custom.get(key, ""), counter[0], style=styles.get(f"custom:{key}"))
    return table


def _legacy_render_form_docx(template_name: str, fields: dict[str, Any] | None, organization_name: str, output_path: str, *, derived_output=None) -> str:
    if template_name not in FORM_LAYOUTS:
        raise ValueError(f"unknown template: {template_name}")
    source = dict(fields or {})
    values = {item["key"]: item["value"] for item in build_preview(template_name, source)["fields"]}
    values["__organization__"] = organization_name
    values["__derived_output__"] = dict(derived_output or {})
    styles = sanitize_preview_styles(template_name, (source.get("_preview_styles") or {}).get(template_name, {}))
    custom = sanitize_preview_custom_values(template_name, (source.get("_preview_custom_values") or {}).get(template_name, {}))
    document = _new_document()
    document.core_properties.title = template_name
    counter = [0]
    for page_index, page in enumerate(FORM_LAYOUTS[template_name]):
        if page_index:
            document.add_page_break()
        _paragraph(document, form_title(template_name, page, source), size=18 if template_name == "档案卷宗" else 20,
                   align="center", after=3 if page.get("subtitle") else 5, title=True)
        subtitle = f"{organization_name or '律师事务所'}制" if page.get("subtitleFromOrganization") else page.get("subtitle", "")
        if subtitle:
            _paragraph(document, subtitle, size=9, align="right" if page.get("subtitleFromOrganization") else "center", after=3)
        for block_index, block in enumerate(page["blocks"]):
            kind = block["type"]
            if kind == "table":
                _render_table(document, block, page_index, block_index, values, styles, custom, counter)
            elif kind == "paragraph":
                p = _paragraph(document, after=1)
                for run in block["runs"]:
                    if run.get("field"):
                        counter[0] += 1
                        _editable_run(p, values.get(run["field"], ""), counter[0], style=styles.get(f'field:{run["field"]}'))
                    else:
                        _font(p.add_run(run.get("text", "")))
            elif kind == "questions":
                for index, question in enumerate(block["questions"], 1):
                    # Long fixed questions put the complete answer pair on a
                    # separate line; CJK line breaking may otherwise split a
                    # label from its checkbox, even with non-breaking spaces.
                    separator = "\n　" if len(question) > 40 else "　"
                    _paragraph(document, f"{index}、{question}{separator}是□　　否□", size=10, before=2, after=1)
            else:
                class_name = block.get("className", "")
                size = 8.5 if class_name in ("delivery-note", "quality-note", "complaint-phones") else 10.5
                p = _paragraph(document, block.get("text", ""), size=size, after=2)
                if class_name == "notice-paragraph":
                    p.paragraph_format.first_line_indent = Pt(21)
                    p.paragraph_format.line_spacing = 1.4
                if class_name == "quality-suggestion":
                    p.paragraph_format.space_after = Mm(15)
                if "signature" in class_name:
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                    p.paragraph_format.space_before = Mm(3)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(output)
    return str(output.resolve())


def render_form_docx(template_name: str, fields: dict[str, Any] | None, organization_name: str, output_path: str, *, derived_output=None) -> str:
    """Production output always fills the retained original; no redraw fallback."""
    from .original_template_service import fill_original_docx
    return fill_original_docx(template_name,fields,organization_name,output_path,derived_output=derived_output)


def generate_system_docx(fields, organization_name, work_dir, log=print, *, exclude_templates=(), quality_component=None) -> dict[str, str]:
    output = Path(work_dir) / "docx"
    rendered = {}
    for name in SYSTEM_TEMPLATE_NAMES:
        if name in exclude_templates:continue
        if name=='质量监督卡' and quality_component is not None:
            from .quality_form_components import fill_quality_component_docx
            rendered[name]=fill_quality_component_docx(quality_component,fields,organization_name,output/f"{name}.docx")
        else:
            rendered[name] = render_form_docx(name, fields, organization_name, str(output / f"{name}.docx"))
        log(f"       可编辑 Word：{name}")
    return rendered
