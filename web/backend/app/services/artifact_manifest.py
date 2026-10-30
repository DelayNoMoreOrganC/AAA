"""Verify every promised deliverable and the bytes actually inside its ZIP."""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from .analysis_snapshot import SYSTEM_TEMPLATE_NAMES

REQUIRED_ARTIFACT_KEYS = frozenset({
    "archive_pdf", "quality_json", "quality_html", "package_zip",
    *(f"docx:{name}" for name in SYSTEM_TEMPLATE_NAMES),
})


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def required_artifact_keys(files):
    from ..core.v4_bridge import load
    FORM_TYPES=load('source_form_policy').FORM_TYPES
    keys=set(REQUIRED_ARTIFACT_KEYS)
    for name in (*FORM_TYPES,'质量监督卡'):
        if 'source_pdf:'+name in files:
            keys.remove('docx:'+name);keys.add('source_pdf:'+name)
    if 'source_component_pdf:质量监督卡' in files and 'source_pdf:质量监督卡' not in files:
        keys.add('source_component_pdf:质量监督卡')
    return keys


def verify_artifact_manifest(output_dir, required_files, *, expected_source_pages=None, source_pages_included=None, require_pagination=False, pagination=None) -> dict:
    root = Path(output_dir).resolve()
    errors, artifacts, actual = [], [], {}
    files = dict(required_files or {})
    for key in sorted(files.keys()-required_artifact_keys(files)):
        errors.append(f"成果重复或未支持：{key}")
    for key in sorted(required_artifact_keys(files) - files.keys()):
        errors.append(f"未登记必需成果：{key}")
    if not isinstance(expected_source_pages, int) or isinstance(expected_source_pages, bool) or expected_source_pages <= 0:
        errors.append("未提供有效源材料总页数")
    elif type(source_pages_included) is not int or source_pages_included != expected_source_pages:
        errors.append(f"源页数量不一致：应有 {expected_source_pages} 页，实际 {source_pages_included} 页")
    quality = None
    registered_paths = set()
    for key, value in files.items():
        try:
            if not value:
                raise ValueError("路径为空")
            path = Path(value).resolve()
            if not path.is_relative_to(root):
                raise ValueError("成果路径超出本次输出目录")
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError("文件不存在或为空")
            if path in registered_paths:
                raise ValueError("不同成果指向同一文件")
            registered_paths.add(path)
            item = {"key": key, "path": str(path), "relative_path": path.relative_to(root).as_posix(),
                    "size": path.stat().st_size, "sha256": _sha256(path)}
            if key == "archive_pdf" or key.startswith(('source_pdf:','source_component_pdf:')) or path.suffix.lower() == ".pdf":
                import fitz
                with fitz.open(path) as document:
                    if document.needs_pass or document.page_count == 0:
                        raise ValueError("PDF无法读取或没有页面")
                    item["pages"] = document.page_count
                    if key == "archive_pdf" and require_pagination:
                        total = document.page_count
                        if pagination is not None and not isinstance(pagination, dict):
                            raise ValueError("归档页码规则无效")
                        if pagination is None or pagination.get("mode") == "legacy":
                            for index, page in enumerate(document, 1):
                                if page.get_label() != str(index) or not re.search(r"GD\s+" + str(index) + r"\s*/\s*" + str(total) + r"\s*$", page.get_text()):
                                    raise ValueError(f"完整PDF第{index}页缺少一致的连续页码或页面标签")
                        else:
                            from archive_pagination import verify_volume_pagination
                            verify_volume_pagination(document, pagination)
                        item["pagination_verified"] = True
            elif key.startswith("docx:") or path.suffix.lower() == ".docx":
                with zipfile.ZipFile(path) as document:
                    bad = document.testzip()
                    if bad:
                        raise ValueError(f"Word压缩内容损坏：{bad}")
                    xml = ElementTree.fromstring(document.read("word/document.xml"))
                    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                    tables = xml.findall(".//w:tbl", ns)
                    if not tables or not any("".join(table.itertext()).strip() for table in tables):
                        if key!='docx:质量监督卡' or 'source_component_pdf:质量监督卡' not in files:
                            raise ValueError("Word没有有效表格内容")
                        from .quality_form_components import _select_xml, TEMPLATE
                        from .original_template_service import template_metadata,TEMPLATES,FILES
                        template_metadata(TEMPLATE)
                        with zipfile.ZipFile(TEMPLATES/'word-converted'/(FILES[TEMPLATE]+'.docx')) as source:
                            if document.read('word/document.xml')!=_select_xml(source.read('word/document.xml'),'client_notice'):
                                raise ValueError('须知组件与原模板不一致')
                    item["tables"] = len(tables)
            elif key == "quality_json":
                quality = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(quality, dict) or quality.get("source_page_conservation") != "passed":
                    raise ValueError("质检单未记录页守恒通过")
                if quality.get("source_pages") != expected_source_pages:
                    raise ValueError("质检单源页数与实际预期不一致")
                if quality.get('source_page_locations_version') is not None:
                    from .source_page_locations import VERSION, validate_locations
                    if quality['source_page_locations_version'] != VERSION:
                        raise ValueError('源页去向版本无法核验')
                    validate_locations(quality.get('source_page_locations'),quality.get('sources'),
                        quality.get('output_pages'),quality.get('pagination'))
                    if len(quality['source_page_locations']) != expected_source_pages:
                        raise ValueError('源页去向数量与本次上传材料不一致')
            elif key == "quality_html":
                if "<html" not in path.read_text(encoding="utf-8").lower():
                    raise ValueError("质检HTML不可解析")
            elif key == "package_zip":
                with zipfile.ZipFile(path) as package:
                    if package.testzip():
                        raise ValueError("成果包损坏")
            artifacts.append(item)
            actual[key] = (path, item)
        except (OSError, ValueError, TypeError, KeyError, RuntimeError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            errors.append(f"{key}：{exc}")
    if isinstance(quality,dict) and quality.get('source_page_locations_version') is not None and 'archive_pdf' in actual:
        if quality.get('output_pages') != actual['archive_pdf'][1].get('pages'):
            errors.append('源页去向记录的成卷页数与实际PDF不一致')
        if pagination is not None and quality.get('pagination') != pagination:
            errors.append('源页去向记录的页码规则与本次成果不一致')
    if 'source_component_pdf:质量监督卡' in files:
        details=quality.get('derived_output') if isinstance(quality,dict) else {}
        details=details if isinstance(details,dict) else {}
        components=details.get('original_form_components')
        refs=components.get('质量监督卡') if isinstance(components,dict) else []
        refs=refs if isinstance(refs,list) else []
        from ..core.v4_bridge import load
        missing=load('source_form_policy').missing_quality_components(refs)
        if len(missing)!=1 or details.get('generated_quality_component')!=missing[0]:
            errors.append('质量表组件来源与补填记录不一致')
        elif 'docx:质量监督卡' in actual:
            from .quality_form_components import COMPONENTS
            with zipfile.ZipFile(actual['docx:质量监督卡'][0]) as package:
                xml=ElementTree.fromstring(package.read('word/document.xml'))
                ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                headings=[''.join(''.join(p.itertext()).split()) for p in xml.findall('./w:body/w:p',ns)]
                expected=COMPONENTS[missing[0]]['title']
                other=COMPONENTS[next(k for k in COMPONENTS if k!=missing[0])]['title']
                if expected not in headings or other in headings:
                    errors.append('质量表未按缺失组件生成')
    if "package_zip" in actual:
        try:
            with zipfile.ZipFile(actual["package_zip"][0]) as package:
                names = package.namelist()
                if len(names) != len(set(names)):
                    errors.append("成果ZIP存在重复条目")
                if any(PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts or "\\" in name or ":" in name for name in names):
                    errors.append("成果ZIP含不安全路径")
                for key, (path, item) in actual.items():
                    if key == "package_zip":
                        continue
                    relative = item["relative_path"]
                    # Support both a directory-preserving package and the
                    # existing flat download package, without ambiguity.
                    candidates = [name for name in names if name == relative or name == path.name]
                    if len(candidates) != 1:
                        errors.append(f"成果ZIP缺少或重复：{key}")
                    else:
                        with package.open(candidates[0]) as stream:
                            digest = hashlib.sha256()
                            for block in iter(lambda: stream.read(1024 * 1024), b""):
                                digest.update(block)
                        if digest.hexdigest() != item["sha256"]:
                            errors.append(f"成果ZIP内容与本次文件不一致：{key}")
        except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile) as exc:
            errors.append(f"成果ZIP验证失败：{exc}")
    return {"valid": not errors, "artifacts": artifacts, "errors": errors,
            "expected_source_pages": expected_source_pages, "source_pages_included": source_pages_included,
            "rule_readiness": quality.get("rule_readiness") if isinstance(quality, dict) else None}
