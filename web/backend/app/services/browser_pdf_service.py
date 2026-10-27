"""Render the five editable browser forms to PDF without Microsoft Word."""
from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import fitz

from ..config import get_settings
from .analysis_snapshot import SYSTEM_TEMPLATE_NAMES
from .preview_fields import (
    build_preview,
    sanitize_preview_custom_values,
    sanitize_preview_styles,
)


from .form_layouts import FORM_LAYOUTS, form_title


CSS = r"""
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: #fff; color: #000; }
.form-page { position: relative; width: 210mm; min-height: 297mm; padding: 17mm 20mm 16mm; break-after: page; font-family: SimSun, "Songti SC", "Noto Serif CJK SC", serif; font-size: 10.5pt; }
.form-page:last-child { break-after: auto; }
h1 { margin: 0 0 7mm; text-align: center; font-size: 20pt; font-weight: 500; letter-spacing: .42em; line-height: 1.25; }
h1.archive-title { font-size: 18pt; letter-spacing: .16em; }
h1.notice-title { margin-bottom: 2mm; font-size: 18pt; }
.page-subtitle { margin: -4mm 0 3mm; text-align: right; font-size: 9pt; white-space: pre-line; }
.quality-card .page-subtitle { margin: 0 8mm 6mm; text-align: center; line-height: 1.5; }
table { width: 100%; table-layout: fixed; border-collapse: collapse; border: 1.2px solid #000; break-inside: auto; }
tr { break-inside: avoid; }
td { position: relative; padding: 0; border: 1px solid #000; vertical-align: middle; white-space: pre-line; overflow-wrap: anywhere; }
td.top-cell { vertical-align: top; }
.cell-value, .fixed-text { display: block; min-height: 7mm; padding: 1.1mm 1.5mm; line-height: 1.35; white-space: pre-wrap; word-break: break-word; }
.vertical-label .fixed-text { line-height: 1.05; }
.prefix-field { display: flex; min-height: 7mm; align-items: stretch; }
.cell-prefix { flex: none; padding: 1.3mm 0 1.3mm 1.5mm; line-height: 1.35; white-space: nowrap; }
.prefix-field .cell-value { flex: 1; padding-left: .5mm; }
.custom-prompt { padding-bottom: .5mm; }
.custom-value { min-height: 5mm; padding-top: 0; }
.delivery-meta { display: flex; align-items: baseline; width: 55%; margin: 0 0 1.5mm; line-height: 7mm; }
.delivery-meta.case-number { margin-top: -2mm; }
.line-value { display: inline-block; flex: 1; min-height: 7mm; padding: 0 1mm; border-bottom: .3px solid #777; white-space: pre-wrap; }
.delivery-note { margin: 0 0 3mm; text-align: right; font-size: 8.5pt; }
.quality-questions { margin: 4mm 0 0; padding-left: 6mm; font-size: 10pt; line-height: 1.45; }
.quality-questions li { position: relative; min-height: 8mm; padding: 0 26mm 0 1mm; }
.checkboxes { position: absolute; top: 0; right: 0; white-space: nowrap; }
.quality-evaluation, .quality-suggestion, .quality-signature, .quality-note { white-space: pre-line; font-size: 9.5pt; line-height: 1.45; }
.quality-evaluation { margin: 2mm 0 3mm; } .quality-suggestion { min-height: 22mm; margin: 0; }
.quality-signature { margin: 0 0 4mm; text-align: right; } .quality-note { margin: 0; text-indent: 2em; }
.notice-paragraph { margin: 0 0 2.2mm; text-align: justify; text-indent: 2em; font-size: 10.5pt; line-height: 1.55; }
.notice-signature { margin: 6mm 0 7mm; text-align: right; white-space: pre; }
.complaint-phones { margin: 0; line-height: 1.7; white-space: pre-line; }
.page-number { position: absolute; right: 0; bottom: 8mm; left: 0; text-align: center; font-size: 9pt; }
"""


def _escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _style_text(style: dict[str, str]) -> str:
    names = {
        "fontFamily": "font-family", "fontSize": "font-size", "fontWeight": "font-weight",
        "fontStyle": "font-style", "textDecoration": "text-decoration",
        "textAlign": "text-align", "color": "color",
    }
    return ";".join(f"{names[key]}:{_escape(value)}" for key, value in style.items() if key in names)


def _line_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item or "") for item in value]
    text = str(value or "")
    return text.splitlines() if "\n" in text or "\r" in text else [part.strip() for part in re.split(r"[、，,；;]+", text)]


def _render_cell(cell: dict, value_map: dict[str, Any], styles: dict, custom_values: dict, key: str) -> str:
    align = cell.get("align", "left")
    classes = cell.get("className", "")
    attrs = [f'colspan="{int(cell.get("colspan", 1))}"', f'class="{_escape(classes)}"', f'style="text-align:{align}"']
    field = cell.get("field")
    lines_field = cell.get("linesField")
    style_key = ""
    if lines_field:
        style_key = f"line:{lines_field}:{int(cell.get('lineIndex', 0))}"
        lines = _line_values(value_map.get(lines_field, ""))
        index = int(cell.get("lineIndex", 0))
        value = ("\n".join(lines[index:]) if cell.get("remainingLines")
                 else lines[index] if index < len(lines) else "")
    elif field:
        style_key = f"field:{field}"
        value = value_map.get(field, "")
    else:
        value = ""
    style = _style_text(styles.get(style_key, {})) if style_key else ""
    value_html = f'<span class="cell-value" style="{style}">{_escape(value)}</span>'

    if cell.get("derived"):
        count = value_map.get("__derived_output__", {}).get(cell["derived"])
        display = str(count) + cell.get("suffix", "") if type(count) is int and count > 0 else "生成后计算"
        content = f'<span class="fixed-text" style="font-size:9pt">{_escape(display)}</span>'
    elif cell.get("prefix"):
        content = f'<div class="prefix-field"><span class="cell-prefix">{_escape(cell["prefix"])}</span>{value_html}</div>'
    elif field or lines_field:
        content = value_html
    elif cell.get("organizationName"):
        content = f'<span class="fixed-text">{_escape(value_map.get("__organization__", ""))}</span>'
    else:
        fixed = _escape(cell.get("text", ""))
        custom = custom_values.get(key, "")
        if custom:
            custom_style = _style_text(styles.get(f"custom:{key}", {}))
            content = f'<span class="fixed-text custom-prompt">{fixed}</span><span class="cell-value custom-value" style="{custom_style}">{_escape(custom)}</span>'
        else:
            content = f'<span class="fixed-text">{fixed}</span>'
    return f"<td {' '.join(attrs)}>{content}</td>"


def _render_block(block: dict, page_index: int, block_index: int, value_map: dict, styles: dict, custom_values: dict) -> str:
    kind = block["type"]
    if kind == "table":
        cols = "".join(f'<col style="width:{float(width)}%">' for width in block["columns"])
        rows = []
        for row_index, row in enumerate(block["rows"]):
            cells = "".join(
                _render_cell(cell, value_map, styles, custom_values, f"p{page_index}-b{block_index}-r{row_index}-c{cell_index}")
                for cell_index, cell in enumerate(row["cells"])
            )
            rows.append(f'<tr style="height:{float(row["height"])}mm">{cells}</tr>')
        return f'<table class="{_escape(block.get("className", ""))}"><colgroup>{cols}</colgroup><tbody>{"".join(rows)}</tbody></table>'
    if kind == "paragraph":
        runs = []
        for run in block["runs"]:
            if run.get("field"):
                field = run["field"]
                runs.append(f'<span class="line-value" style="{_style_text(styles.get(f"field:{field}", {}))}">{_escape(value_map.get(field, ""))}</span>')
            else:
                runs.append(_escape(run.get("text", "")))
        return f'<p class="{_escape(block.get("className", ""))}">{"".join(runs)}</p>'
    if kind == "questions":
        items = "".join(f'<li><span>{_escape(question)}</span><span class="checkboxes">是□　　否□</span></li>' for question in block["questions"])
        return f'<ol class="quality-questions">{items}</ol>'
    return f'<p class="{_escape(block.get("className", ""))}">{_escape(block.get("text", ""))}</p>'


def render_form_html(template_name: str, fields: dict[str, Any] | None, organization_name: str = "", *, derived_output=None) -> str:
    if template_name not in FORM_LAYOUTS:
        raise ValueError("未知系统表模板")
    source = dict(fields or {})
    preview = build_preview(template_name, source)
    value_map = {item["key"]: item["value"] for item in preview["fields"]}
    value_map["__organization__"] = organization_name
    value_map["__derived_output__"] = dict(derived_output or {})
    styles_by_template = source.get("_preview_styles") or {}
    custom_by_template = source.get("_preview_custom_values") or {}
    styles = sanitize_preview_styles(template_name, styles_by_template.get(template_name) or {})
    if template_name == "档案卷宗" and "field:审（办）结果" not in styles and "field:结案小结" in styles:
        styles["field:审（办）结果"] = dict(styles["field:结案小结"])
    custom_values = sanitize_preview_custom_values(template_name, custom_by_template.get(template_name) or {})

    pages = []
    layout_pages = FORM_LAYOUTS[template_name]
    for page_index, page in enumerate(layout_pages):
        title = f'<h1 class="{_escape(page.get("titleClass", ""))}">{_escape(form_title(template_name, page, source))}</h1>' if page.get("title") else ""
        subtitle_text = f"{organization_name or '律师事务所'}制" if page.get("subtitleFromOrganization") else page.get("subtitle", "")
        subtitle = f'<div class="page-subtitle">{_escape(subtitle_text)}</div>' if subtitle_text else ""
        blocks = "".join(_render_block(block, page_index, block_index, value_map, styles, custom_values) for block_index, block in enumerate(page["blocks"]))
        number = f'<div class="page-number">{page_index + 1}</div>' if len(layout_pages) > 1 else ""
        quality_class = " quality-card" if template_name == "质量监督卡" else ""
        pages.append(f'<section class="form-page{quality_class}">{title}{subtitle}{blocks}{number}</section>')

    return "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><style>" + CSS + "</style></head><body>" + "".join(pages) + "</body></html>"


def browser_pdf_dir(work_dir: str) -> str:
    return os.path.join(work_dir, "browser_pdf")


class BrowserPdfError(RuntimeError):
    """Only fixed diagnostic codes and a numeric process exit code are public."""


def _validate_long_inventory(path, template_name, fields):
    """Fail explicitly if the expanded fifth row loses content during print."""
    if template_name != "送达材料清单":
        return
    preview = build_preview(template_name, fields or {})
    value = next((entry["value"] for entry in preview["fields"] if entry["key"] == "法院文件清单"), "")
    lines = _line_values(value)
    if len(lines) <= 5:
        return
    def compact(text):
        return re.sub(r"[\s\u200b\ufeff]+", "", unicodedata.normalize("NFKC", text))
    expected = Counter(compact(line) for line in lines if compact(line))
    with fitz.open(path) as document:
        rendered = compact("".join(page.get_text() for page in document))
    if any(rendered.count(line) < count for line, count in expected.items()):
        raise BrowserPdfError("法院文件清单未完整呈现，请调整表格后重新生成 [BROWSER_INVENTORY_INCOMPLETE]")


def _render_form_pdf(template_name: str, fields: dict[str, Any] | None, organization_name: str, output_pdf: str, log=print, *, derived_output=None) -> str:
    chromium = get_settings().chromium_executable
    if not chromium:
        raise BrowserPdfError("未找到 Chrome/Chromium；请安装浏览器或配置 V5_CHROMIUM_PATH [BROWSER_NOT_FOUND]")
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise BrowserPdfError("浏览器 PDF 服务须以非 root 账号运行，以保留浏览器沙箱保护 [BROWSER_SANDBOX_REQUIRED]")
    output = Path(output_pdf).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    html_path = output.with_suffix(".html")
    html_path.write_text(render_form_html(template_name, fields, organization_name, derived_output=derived_output), encoding="utf-8")
    profile_dir = tempfile.mkdtemp(prefix="gd_chrome_")
    temp_pdf = output.with_suffix(".tmp.pdf")
    temp_pdf.unlink(missing_ok=True)
    command = [
        chromium,
        "--headless=new",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-sync",
        "--metrics-recording-only",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-pdf-header-footer",
        "--allow-file-access-from-files",
        f"--user-data-dir={profile_dir}",
        f"--print-to-pdf={temp_pdf}",
        html_path.as_uri(),
    ]
    process = None
    try:
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except OSError:
            raise BrowserPdfError("浏览器启动失败 [BROWSER_START_FAILED]") from None
        valid_pdf = False
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if temp_pdf.is_file() and temp_pdf.stat().st_size > 1000:
                try:
                    with fitz.open(temp_pdf) as document:
                        if document.page_count > 0 and all(
                            abs(page.rect.width - 595.28) <= 3
                            and abs(page.rect.height - 841.89) <= 3
                            for page in document
                        ):
                            valid_pdf = True
                            break
                except (RuntimeError, ValueError):
                    pass
            if process.poll() is not None:
                break
            time.sleep(0.2)
        if not valid_pdf:
            exit_code = process.poll()
            if exit_code is None:
                raise BrowserPdfError("等待有效 A4 PDF 超时 [BROWSER_RENDER_TIMEOUT]")
            # Never include subprocess output, command arguments, URIs or paths.
            code = "BROWSER_INVALID_PDF" if exit_code == 0 else "BROWSER_EXITED"
            safe_exit = exit_code if type(exit_code) is int else "unknown"
            raise BrowserPdfError(f"浏览器未生成有效 A4 PDF [{code}; exit_code={safe_exit}]")
        _validate_long_inventory(temp_pdf, template_name, fields)
        os.replace(temp_pdf, output)
        log(f"       浏览器 PDF: {template_name}")
        return str(output)
    finally:
        cleanup_failed = False
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=3)
            except (OSError, subprocess.SubprocessError):
                try:
                    process.kill()
                    process.wait(timeout=3)
                except (OSError, subprocess.SubprocessError):
                    cleanup_failed = True
        try:
            temp_pdf.unlink(missing_ok=True)
        except OSError:
            pass
        shutil.rmtree(profile_dir, ignore_errors=True)
        if cleanup_failed:
            raise BrowserPdfError("浏览器进程清理失败 [BROWSER_CLEANUP_FAILED]") from None


def _legacy_render_form_pdf(template_name: str, fields: dict[str, Any] | None, organization_name: str, output_pdf: str, log=print, *, derived_output=None) -> str:
    try:
        return _render_form_pdf(template_name, fields, organization_name, output_pdf,
                                log=log, derived_output=derived_output)
    except BrowserPdfError:
        raise
    except Exception:
        # File-system and library exceptions can include source paths or content.
        # Keep the failure observable without exposing their message or chain.
        raise BrowserPdfError("浏览器 PDF 生成失败 [BROWSER_RENDER_FAILED]") from None


def render_form_pdf(template_name: str, fields: dict[str, Any] | None, organization_name: str, output_pdf: str, log=print, *, derived_output=None) -> str:
    """Original DOCX -> native PDF. HTML is never an output fallback."""
    from .original_template_service import render_original_pdf
    result=render_original_pdf(template_name,fields,organization_name,output_pdf,derived_output=derived_output)
    log(f"       浏览器 PDF: {template_name}")
    return result


def render_system_form_pdfs(fields: dict[str, Any] | None, organization_name: str, work_dir: str, log=print, *, exclude_templates=(), quality_component=None) -> dict[str, str]:
    output_dir = browser_pdf_dir(work_dir)
    os.makedirs(output_dir, exist_ok=True)
    rendered: dict[str, str] = {}
    for template_name in SYSTEM_TEMPLATE_NAMES:
        if template_name in exclude_templates:continue
        if template_name=='质量监督卡' and quality_component is not None:
            from .quality_form_components import render_quality_component_pdf
            rendered[template_name]=render_quality_component_pdf(quality_component,fields,organization_name,
                os.path.join(output_dir,f"{template_name}.pdf"))
            continue
        rendered[template_name] = render_form_pdf(
            template_name,
            fields,
            organization_name,
            os.path.join(output_dir, f"{template_name}.pdf"),
            log=log,
        )
    return rendered
