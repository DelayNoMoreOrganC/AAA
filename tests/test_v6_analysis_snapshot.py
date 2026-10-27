# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "backend"))

from archive_pipeline import ArchiveAnalysis
from pdf_doc_locator import DocumentUnit
from app.services.analysis_snapshot import load_analysis, save_snapshot, stabilize_templates


def test_snapshot_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        analysis = ArchiveAnalysis(
            case_type="civil",
            original_pdf="C:/test/sample.pdf",
            fields={"委托人": "测试银行", "结案小结": "法院判决测试。"},
            generated_templates={},
            doc_spans=[
                DocumentUnit(doc_id=1, doc_type="judgment", start_page=0, end_page=2, catalog_seq=14, source_path="C:/test/sample.pdf"),
            ],
            found_seqs={14},
            missing_items=[{"seq": 15, "name": "执行文书"}],
            outcome_warnings=["test warning"],
            source_paths=["C:/test/sample.pdf", "C:/test/unsegmented.pdf"],
        )
        fake_docx = os.path.join(td, "docx")
        os.makedirs(fake_docx, exist_ok=True)
        tpl = os.path.join(fake_docx, "立案审批表.docx")
        with open(tpl, "wb") as f:
            f.write(b"PK")
        analysis.generated_templates = {"立案审批表": tpl}
        save_snapshot(td, analysis, base_name="sample", order_mode="catalog")
        restored, data = load_analysis(td)
        assert restored.case_type == "civil"
        assert restored.fields["委托人"] == "测试银行"
        assert data["base_name"] == "sample"
        assert len(restored.doc_spans) == 1
        assert restored.doc_spans[0].catalog_seq == 14
        assert restored.source_paths == ["C:/test/sample.pdf", "C:/test/unsegmented.pdf"]
