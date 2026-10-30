"""Export reproducible technical checks without claiming legal compliance."""
import hashlib
import html
import json
from datetime import datetime, timezone
from pathlib import Path

import fitz

from .archive_rules import get_catalog_rules, get_rule_readiness, material_completeness


def write_quality_report(work, analysis, files, output_pdf, mode, skipped, *, verification=None, stage=None, derived_output=None, draft=False, review_issues=None):
    sources = []
    for item in files:
        path = Path(item.abs_path)
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        with fitz.open(path) as document:
            count = document.page_count
        sources.append({"filename": item.filename, "processed_sha256": digest.hexdigest(), "pages": count,
                        "path": str(path.resolve())})
    with fitz.open(output_pdf) as document:
        total = document.page_count
        bookmarks = len(document.get_toc())
        links = sum(len(page.get_links()) for page in document)
    source_pages = sum(item["pages"] for item in sources)
    verified = verification if isinstance(verification, dict) else vars(verification) if verification is not None else {}
    conservation = (verified.get("success") is True and source_pages > 0
                    and verified.get("original_pages_included") == source_pages)
    from .source_page_locations import VERSION as LOCATIONS_VERSION, project_locations
    locations = project_locations(verified.get('source_page_locations'), files, sources, total, verified.get('pagination'))
    rules = get_rule_readiness(analysis.case_type, stage)
    material_report = material_completeness(analysis, stage, [
        {"file_id": getattr(item, "id", None), "path": source["path"], "filename": source["filename"], "pages": source["pages"]}
        for item, source in zip(files, sources)])
    source_lookup = {item["path"]: item for item in sources}
    document_provenance = []
    for unit in getattr(analysis, "doc_spans", []) or []:
        path = str(Path(getattr(unit, "source_path", "") or "").resolve())
        original = source_lookup.get(path)
        start, end = getattr(unit, "start_page", None), getattr(unit, "end_page", None)
        bounds_ok = original is not None and type(start) is int and type(end) is int and 0 <= start <= end < original["pages"]
        document_provenance.append({"title": getattr(unit, "title", ""), "doc_type": getattr(unit, "doc_type", ""),
            "catalog_seq": getattr(unit, "catalog_seq", None), "source_filename": original["filename"] if original else Path(path).name,
            "source_pages": [start + 1, end + 1] if bounds_ok else None, "source_anchor_valid": bounds_ok})
    classification_audit = []
    records = (analysis.fields or {}).get("_document_classifications") or {}
    if records:
        from .document_classification import indexed_units
        manifest = [{"file_id": getattr(item, "id", None), "path": source["path"],
                     "sha256": source["processed_sha256"], "pages": source["pages"]}
                    for item, source in zip(files, sources)]
        try:
            units = indexed_units(analysis, manifest)
        except (ValueError, TypeError, KeyError, AttributeError):
            units = {}
        names = {getattr(item, "id", None): item.filename for item in files}
        for key, entry in records.items():
            if not isinstance(entry, dict):
                continue
            unit = units.get(key, (None,))[0]
            applied = (unit is not None and getattr(unit, "manual_catalog_seq", None) == entry.get("catalog_seq")
                       and getattr(unit, "doc_type", None) == entry.get("doc_type"))
            start, end = entry.get("start_page"), entry.get("end_page")
            classification_audit.append({
                "source_filename": names.get(entry.get("file_id"), "历史材料已变更"),
                "source_pages": [start + 1, end + 1] if type(start) is int and type(end) is int and 0 <= start <= end else None,
                "original_doc_type": entry.get("original_doc_type"), "original_catalog_seq": entry.get("original_catalog_seq"),
                "doc_type": entry.get("doc_type"), "catalog_seq": entry.get("catalog_seq"),
                "reason": entry.get("reason", ""), "edited_at": entry.get("edited_at", ""),
                "revision": entry.get("revision"), "applied_to_current_volume": applied,
            })
    public_fields = {key: value for key, value in (analysis.fields or {}).items() if not str(key).startswith("_")}
    from .form_fill_audit import build_form_fill_audit, render_form_fill_audit, content_preflight
    field_manifest = [{"file_id": getattr(item, "id", None), "path": source["path"],
                       "filename": source["filename"], "pages": source["pages"],
                       "sha256": source["processed_sha256"], "doc_type": getattr(item, "doc_type", "default")}
                      for item, source in zip(files, sources)]
    field_audit = build_form_fill_audit(analysis.fields, field_manifest,
        issues=review_issues or (), derived_output=derived_output)
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "processing_mode": mode,
        "sources": sources,
        "source_pages": source_pages,
        "output_pages": total,
        "pagination": verified.get("pagination"),
        "pagination_convention": "电子版按用户确认：草稿不新增页码；定稿从目录后正文起底部居中编号。与所提供2004年佛山办法第18条的纸质正面右上角、背面左上角位置要求不同。",
        "derived_output": dict(derived_output or {}),
        "bookmarks": bookmarks,
        "links": links,
        "source_page_conservation": "passed" if conservation else "not_verified",
        "source_page_locations_version": LOCATIONS_VERSION if locations is not None else None,
        "source_page_locations": locations,
        "original_pages_included": verified.get("original_pages_included"),
        "document_provenance": document_provenance,
        "document_classification_audit": classification_audit,
        "document_order": (analysis.fields or {}).get("_document_order"),
        "confirmed_values_sha256": hashlib.sha256(json.dumps(public_fields, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest(),
        "field_provenance_status": "字段填写、当前有效来源及留空原因见对照表；有来源不等于事实已独立证实",
        "form_fill_audit_version": "original-form-fields-v1",
        "form_fill_audit": field_audit,
        "content_preflight": content_preflight(field_audit),
        "missing_items": list(analysis.missing_items or []),
        "missing_items_scope": "catalog_occupancy_only_not_material_completeness",
        "material_completeness": material_report,
        "review_decisions": (analysis.fields or {}).get("_review_decisions", {}),
        "skipped_catalog_items": list(skipped),
        "outcome_warnings": list(getattr(analysis, "outcome_warnings", []) or []),
        "rules_status": "现有目录模板；广东各业务类型适用标准仍待核验",
        "rule_readiness": rules,
        "catalog_rules": get_catalog_rules(analysis.case_type, stage),
        "delivery_classification": "draft" if draft or not rules["formal_ready"] else "reviewed",
        "automatically_generated_draft": bool(draft),
        "unresolved_review_items": list(review_issues or []) if draft else [],
        "values_status": "自动整理，尚未经人工最终确认" if draft else "已确认修订",
        "human_review": "自动检查不代替承办律师确认事实、材料完整性及归档适用标准",
    }
    root = Path(work)
    (root / "归档质检清单.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    esc = lambda value: html.escape(str(value))
    rows = "".join(f'<tr><td>{esc(item["filename"])}</td><td>{item["pages"]}</td><td><code>{item["processed_sha256"]}</code></td></tr>' for item in sources)
    by_seq = {item["seq"]:item for item in report["catalog_rules"]}
    requirement_names = {"required":"必要材料", "conditional":"条件必要", "optional":"可选材料"}
    issues = "".join(f'<li>{esc(item.get("name", item.get("seq")))}（{esc(requirement_names.get(by_seq.get(item.get("seq"), {}).get("requirement"), "适用性待核验"))}）：{esc(report["review_decisions"].get(str(item.get("seq")), {}).get("reason") or "当前材料中未找到，请按实际办理情况补充；不代表该项已被确认不适用")}</li>' for item in report["missing_items"])
    material_rows = []
    for item in material_report["checks"]:
        if item["check_kind"] != "source_material" or item["status"] == "recognized" or item["applicable"] is False:
            continue
        label = requirement_names.get(item["requirement"], "适用性待核验") if item["legal_requirement_verified"] else "适用性待核验"
        anchors = "；".join(f'{source["filename"]} 第 {source["page_start"]}—{source["page_end"]} 页' for source in item["related_sources"])
        material_rows.append(f'<li>{esc(item["name"])}（{esc(label)}）：{esc(item["message"])}' + (f'；相关材料：{esc(anchors)}' if anchors else '') + '</li>')
    material_html = ''.join(material_rows) or '<li>未列出待补充文书；不代表签署、送达和附件完整性已经核验。</li>'
    unknown_html = ''.join(f'<li>{esc(source["filename"])} 第 {source["page_start"]}—{source["page_end"]} 页：尚未明确类别；保留入卷不等于已确认属于证据。</li>' for source in material_report["unclassified_sources"])
    review_html = "".join(f'<li>{esc(item.get("title") or item.get("message") or item.get("kind"))}</li>' for item in report["unresolved_review_items"] if item.get("blocking"))
    classification_rows = "".join(
        f'<tr><td>{esc(item["source_filename"])}<br>页 {esc(item["source_pages"])}</td>'
        f'<td>{esc(item["original_catalog_seq"])} / {esc(item["original_doc_type"])} → {esc(item["catalog_seq"])} / {esc(item["doc_type"])}</td>'
        f'<td>{esc(item["reason"])}<br>{esc(item["edited_at"])}</td><td>{"已应用" if item["applied_to_current_volume"] else "未应用，请核对历史记录"}</td></tr>'
        for item in classification_audit)
    classification_html = ('<table><tr><th>原材料与页段</th><th>分类调整</th><th>核对原因与时间</th><th>本卷状态</th></tr>' + classification_rows + '</table>') if classification_rows else '<p>无人工文书分类记录；自动分类仍需对照原件核对。</p>'
    from urllib.parse import quote
    output_link = esc(quote(Path(output_pdf).name))
    location_rows = ''.join(f'<tr><td>{esc(row["source_filename"])}</td><td>{row["source_page"]}</td>'
        f'<td><a href="{output_link}#page={row["archive_page"]}">{row["archive_page"]}</a></td>'
        f'<td>{row["body_page"] if row["body_page"] is not None else "—"}</td></tr>' for row in (locations or []))
    locations_html = ('<details><summary>源页去向（原件每页对应成卷位置）</summary><p>成卷页为PDF实际页序；草稿不新增正文页码。此表说明摆放位置，不证明分类或内容识别正确。</p>'
        '<table><tr><th>原材料</th><th>原页</th><th>成卷页</th><th>正文页码</th></tr>'+location_rows+'</table></details>') if locations is not None else '<p>历史结果未记录逐页去向。</p>'
    original = (derived_output or {}).get("template_evidence") or {}
    template_html = ('<h2>原表版式核对</h2><p>使用律所提供的原目录和原表，仅填写对应位置；已有立案审批表、结案报告表及律师所送达材料清单保留原件，不重复补填。质量监督卡与委托人须知分别保留已有组件，只补缺失部分；保留原件不证明已告知或已签署。生成表格的框格与页数已校验；原模板哈希记录在本清单 JSON 中。模板来源核验不等于现行规范核验。</p>'
                     if original.get("format_verification") == "original_frames_and_page_counts_verified" else '')
    body = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>归档质检清单</title>
    <style>body{{font:16px/1.7 sans-serif;max-width:1000px;margin:40px auto;padding:20px;color:#243c33}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccd8d0;padding:10px;text-align:left}}code{{font-size:11px;word-break:break-all}}.notice{{background:#fff4df;padding:16px}}</style>
    <h1>归档质检清单</h1><p>生成时间：{esc(report["created_at"])} · 处理模式：{esc(mode)}</p>{locations_html}
    <p>源材料 {len(sources)} 份 / {report["source_pages"]} 页；归档 {total} 页（含系统表与目录）；电子书签 {bookmarks} 个；链接 {links} 个。</p>
    <p>源页数量、范围与重复入卷检查：{'通过' if conservation else '未核验，不能作为完成依据'}。</p><p>{esc(report['pagination_convention'])}</p><table><tr><th>材料</th><th>页数</th><th>处理文件 SHA-256</th></tr>{rows}</table>
    {template_html}{render_form_fill_audit(field_audit)}<h2>补充材料清单</h2><p>{esc(material_report['notice'])}</p><ul>{material_html}</ul>
    <p>生成的立案审批、质量监督、送达清单和结案表不证明已审批、签署或实际送达。</p>
    <ul>{unknown_html}</ul><details><summary>目录空位记录（不是材料齐备结论）</summary><ul>{issues or '<li>无目录空位记录</li>'}</ul></details>
    <h2>待核对内容</h2><ul>{review_html or '<li>无额外自动核对异常</li>'}</ul>
    <p>{esc(report['values_status'])}；草稿未替你确认缺件、事实冲突或律师审批。</p>
    <h2>人工文书分类记录</h2>{classification_html}
    <h2>事实核对提醒</h2><p>{esc('；'.join(report['outcome_warnings']) or '请对照原始材料核对系统提取与人工填写的事实。')}</p>
    <p>{esc(report['field_provenance_status'])}</p><p>规则版本：{esc(rules['version'])}；当前成果状态：草稿。</p>
    <p class="notice">{esc(report["rules_status"])}。{esc(report["human_review"])}</p></html>'''
    (root / "归档质检清单.html").write_text(body, encoding="utf-8")
    return report
