"""Opt-in real-browser archive integration, using a fabricated analysis fixture.

The prefilled analysis intentionally bypasses OCR and model extraction. This test
measures rendering, persistence, merge/navigation and source-page conservation;
it is NOT an AI extraction accuracy test and uses no client information.
"""
import hashlib
import json
import os
from pathlib import Path
import sys

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import archive_catalog as ac
import archive_pipeline as pipeline
import catalog_toc
from pdf_doc_locator import DocumentUnit
from app.config import get_settings
from app.services.analysis_snapshot import SYSTEM_TEMPLATE_NAMES, load_analysis, save_snapshot
from app.services.browser_pdf_service import render_system_form_pdfs


@pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_PDF_TESTS") != "1" or not get_settings().chromium_executable,
    reason="set RUN_BROWSER_PDF_TESTS=1 and use an installed Chromium/Edge",
)
def test_real_browser_forms_snapshot_and_archive_roundtrip(tmp_path, monkeypatch):
    assert get_settings().preview_only, "Run this integration test with V5_PREVIEW_ONLY=true"

    def forbidden(*args, **kwargs):
        raise AssertionError("This fabricated fixture must not call AI, OCR or Word")

    monkeypatch.setattr(pipeline, "_deepseek_request", forbidden)
    monkeypatch.setattr(pipeline, "ingest_archive_sources", forbidden)
    monkeypatch.setattr(catalog_toc, "catalog_toc_to_pdf", forbidden)
    source = tmp_path / "fictional_source.pdf"
    labels = [f"FICTIONAL_SOURCE_PAGE_{number}" for number in range(4)]
    with fitz.open() as document:
        for label in labels:
            page = document.new_page(width=595.28, height=841.89)
            page.insert_text((72, 72), label)
        document.save(source)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    fields = {
        "案件类别": "民事", "委托人": "示例委托人甲（完全虚构）", "当事人": "示例委托人甲（完全虚构）",
        "对方当事人": "示例相对方乙（完全虚构）", "案由": "虚构合同纠纷",
        "法院收案号": "（2026）虚构测试民初001号", "承办律师": "示例律师甲",
        "结案小结": "仅供归档流程测试，内容为预先构造的虚构数据，并非 AI 识别结果。",
        "委托人对服务质量意见": "测试夹具无客户反馈，不预填满意结论。",
        "法院文件清单": "虚构判决书", "_preview_custom_values": {"立案审批表": {"p0-b0-r6-c0": "虚构测试核对意见。"}},
    }
    units = [
        DocumentUnit(0, "judgment", 0, 1, title="虚构判决书", catalog_seq=14, source_path=str(source)),
        DocumentUnit(1, "contract", 2, 3, title="虚构委托合同", catalog_seq=3, source_path=str(source)),
    ]
    found = {0, 1, 3, 14, 16, 17, 18}
    missing = [{"seq": item.seq, "name": item.name} for item in ac.get_effective_catalog("civil", found) if item.seq not in found]
    fields["_review_decisions"] = {str(item["seq"]): {"action": "not_applicable", "reason": "虚构测试夹具不含此材料"} for item in missing}
    analysis = pipeline.ArchiveAnalysis("civil", str(source), fields, {}, units, found, missing, source_paths=[str(source)])
    work = tmp_path / "snapshot"
    save_snapshot(str(work), analysis, base_name="fictional", order_mode="catalog", skipped=[item["seq"] for item in missing])
    restored, snapshot = load_analysis(str(work))
    restored.generated_templates = render_system_form_pdfs(restored.fields, "虚构示例律师事务所", str(work))
    assert set(restored.generated_templates) == set(SYSTEM_TEMPLATE_NAMES)
    rendered_pages = {}
    for name, path in restored.generated_templates.items():
        with fitz.open(path) as form:
            rendered_pages[name] = form.page_count
            assert form.page_count >= 1
            assert all(abs(page.rect.width - 595.28) <= 3 and abs(page.rect.height - 841.89) <= 3 for page in form)
    save_snapshot(str(work), restored, base_name="fictional", order_mode="catalog", skipped=snapshot["skipped"])
    restored, snapshot = load_analysis(str(work))
    output = tmp_path / "fictional_archive.pdf"
    logs = []
    result = pipeline.assemble_archive(
        restored, str(output), skipped=snapshot["skipped"],
        config={"output": {"preview_only": True}, "archive": {"order_mode": "catalog"}}, log=logs.append,
    )
    assert result.success, "\n".join(logs)
    assert result.original_pages_included == 4
    assert result.order_issues == []
    assert len(result.missing) == len(missing)
    assert len({item["seq"] for item in result.missing}) == len(result.missing)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    with fitz.open(output) as document:
        inserted_names = {item.templates[0] for item in ac.get_catalog("civil") if item.source == "system" and item.seq in {0, 1, *ac.get_back_system_seqs("civil")}}
        assert document.page_count == sum(rendered_pages[name] for name in inserted_names) + 4 + 1
        all_text = "\n".join(page.get_text() for page in document)
        assert all(all_text.count(label) == 1 for label in labels)
        bookmarks = {title: page - 1 for _level, title, page in document.get_toc()}
        assert "卷内目录" in bookmarks
        assert "律师所送达材料清单" in bookmarks
        assert labels[2] in document[bookmarks["委托代理合同"]].get_text()
        assert labels[0] in document[bookmarks["裁定书、判决书、调解书"]].get_text()
        links = document[bookmarks["卷内目录"]].get_links()
        assert {link["page"] for link in links} == set(bookmarks.values())
        report = {
            "fixture_notice": "虚构分析快照，绕过OCR/模型，仅验证工程闭环", "browser": get_settings().chromium_executable,
            "form_pages": rendered_pages, "archive_pages": document.page_count, "source_pages_included": result.original_pages_included,
            "bookmark_count": len(bookmarks), "directory_link_count": len(links), "source_sha256_unchanged": True,
            "all_five_system_forms_in_archive": inserted_names == set(SYSTEM_TEMPLATE_NAMES),
        }
    (tmp_path / "integration_result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (tmp_path / "merge.log").write_text("\n".join(logs), encoding="utf-8")
    print("Integration artifacts:", tmp_path)
