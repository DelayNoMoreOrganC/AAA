import json
from pathlib import Path
from zipfile import ZipFile

import fitz
import pytest

from app.services.artifact_manifest import REQUIRED_ARTIFACT_KEYS, verify_artifact_manifest
from app.services.system_docx_service import generate_system_docx


@pytest.fixture
def complete_outputs(tmp_path):
    docs = generate_system_docx({"委托人": "虚构甲"}, "虚构律所", tmp_path, log=lambda *_a: None)
    files = {f"docx:{name}": path for name, path in docs.items()}
    pdf = tmp_path / "归档.pdf"
    with fitz.open() as document:
        document.new_page().insert_text((50, 50), "Fictional archive")
        document.save(pdf)
    quality = tmp_path / "归档质检清单.json"
    quality.write_text(json.dumps({"source_page_conservation": "passed", "source_pages": 1}), encoding="utf-8")
    html = tmp_path / "归档质检清单.html"
    html.write_text("<!doctype html><html><body>虚构质检</body></html>", encoding="utf-8")
    files.update(archive_pdf=str(pdf), quality_json=str(quality), quality_html=str(html))
    package = tmp_path / "成果.zip"
    with ZipFile(package, "w") as zipped:
        for path in files.values():
            zipped.write(path, Path(path).relative_to(tmp_path).as_posix())
    files["package_zip"] = str(package)
    return tmp_path, files


def _verify(root, files, **kwargs):
    return verify_artifact_manifest(root, files, expected_source_pages=1, source_pages_included=1, **kwargs)


@pytest.mark.parametrize('wrong',['whole_template','no_provenance'])
def test_partial_quality_delivery_cannot_smuggle_full_template_or_omit_provenance(complete_outputs,wrong):
    root,files=complete_outputs
    source=root/'original-card.pdf'
    with fitz.open() as document:
        document.new_page().insert_text((72,72),'Original quality card');document.save(source)
    files['source_component_pdf:质量监督卡']=str(source)
    quality=json.loads(Path(files['quality_json']).read_text(encoding='utf8'))
    if wrong=='whole_template':
        quality['derived_output']={'original_form_components':{'质量监督卡':[
            {'component':'quality_card','file_id':'s','page':1,'page_end':1}]},'generated_quality_component':'client_notice'}
    Path(files['quality_json']).write_text(json.dumps(quality),encoding='utf8')
    with ZipFile(files['package_zip'],'w') as package:
        for key,path in files.items():
            if key!='package_zip':package.write(path,Path(path).relative_to(root).as_posix())
    result=_verify(root,files)
    assert not result['valid']
    assert any('质量表' in error for error in result['errors'])


def test_complete_output_and_zip_bytes_pass(complete_outputs):
    root, files = complete_outputs
    report = _verify(root, files)
    assert report["valid"] is True, report["errors"]
    assert len(report["artifacts"]) == len(REQUIRED_ARTIFACT_KEYS)


@pytest.mark.parametrize('fault',[None,'missing','duplicate','fake_total'])
def test_page_locations_are_verified_against_sources_and_actual_output(complete_outputs,fault):
    root,files=complete_outputs
    quality=json.loads(Path(files['quality_json']).read_text(encoding='utf8'))
    row={'source_index':1,'source_filename':'source.pdf','source_sha256':'a'*64,'source_page':1,'archive_page':1,'body_page':None}
    quality.update(source_page_locations_version='source-pages-v1',source_page_locations=[row],output_pages=1,
        sources=[{'filename':'source.pdf','processed_sha256':'a'*64,'pages':1}],pagination={'mode':'draft','body_start':0})
    if fault=='missing':quality['source_page_locations']=[]
    if fault=='duplicate':quality['source_page_locations'].append(dict(row))
    if fault=='fake_total':quality['output_pages']=2;row['archive_page']=2
    Path(files['quality_json']).write_text(json.dumps(quality),encoding='utf8')
    with ZipFile(files['package_zip'],'w') as package:
        for key,path in files.items():
            if key!='package_zip':package.write(path,Path(path).relative_to(root).as_posix())
    result=_verify(root,files)
    assert result['valid'] is (fault is None),result['errors']


def test_original_approval_replaces_only_generated_approval_and_must_be_valid(complete_outputs):
    root,files=complete_outputs
    files.pop('docx:立案审批表')
    path=root/'立案审批表_原件.pdf'
    with fitz.open() as d:
        d.new_page().insert_text((50,50),'Original approval');d.save(path)
    files['source_pdf:立案审批表']=str(path)
    with ZipFile(files['package_zip'],'w') as z:
        for k,p in files.items():
            if k!='package_zip':z.write(p,Path(p).name)
    assert _verify(root,files)['valid']
    path.write_bytes(b'')
    assert not _verify(root,files)['valid']


def test_generated_and_original_versions_cannot_both_claim_one_form(complete_outputs):
    root,files=complete_outputs
    path=root/'provided.pdf'
    with fitz.open() as d:d.new_page();d.save(path)
    files['source_pdf:结案报告表']=str(path)
    assert any('成果重复' in e for e in _verify(root,files)['errors'])


def test_source_pdf_is_validated_even_with_wrong_extension(complete_outputs):
    root,files=complete_outputs
    files.pop('docx:送达材料清单')
    path=root/'provided.bin';path.write_bytes(b'not a pdf')
    files['source_pdf:送达材料清单']=str(path)
    assert not _verify(root,files)['valid']


@pytest.mark.parametrize("key", sorted(REQUIRED_ARTIFACT_KEYS))
def test_each_missing_promised_file_prevents_completion(complete_outputs, key):
    root, files = complete_outputs
    Path(files[key]).unlink()
    report = _verify(root, files)
    assert report["valid"] is False
    assert any(key in error for error in report["errors"])


def test_empty_manifest_and_all_missing_files_never_pass(tmp_path):
    assert not _verify(tmp_path, {})["valid"]
    absent = {key: str(tmp_path / f"missing-{index}") for index, key in enumerate(REQUIRED_ARTIFACT_KEYS)}
    report = _verify(tmp_path, absent)
    assert not report["valid"] and len(report["errors"]) == len(REQUIRED_ARTIFACT_KEYS)


def test_registered_duplicate_file_is_not_five_word_deliverables(complete_outputs):
    root, files = complete_outputs
    files["docx:结案报告表"] = files["docx:档案卷宗"]
    assert not _verify(root, files)["valid"]


def test_corrupt_word_and_stale_zip_fail(complete_outputs):
    root, files = complete_outputs
    Path(files["docx:档案卷宗"]).write_bytes(b"not a DOCX")
    assert not _verify(root, files)["valid"]


def test_zip_missing_one_word_fails_even_when_file_exists(complete_outputs):
    root, files = complete_outputs
    with ZipFile(files["package_zip"], "w") as zipped:
        for key, path in files.items():
            if key not in ("package_zip", "docx:立案审批表"):
                zipped.write(path, Path(path).name)
    assert not _verify(root, files)["valid"]


def test_stale_zip_with_old_confirmed_content_is_rejected(complete_outputs):
    root, files = complete_outputs
    Path(files["quality_html"]).write_text("<html><body>本次已修改的核对值</body></html>", encoding="utf-8")
    report = _verify(root, files)
    assert not report["valid"]
    assert any("不一致" in error and "quality_html" in error for error in report["errors"])


def test_source_count_or_unverified_quality_prevents_completion(complete_outputs):
    root, files = complete_outputs
    assert not verify_artifact_manifest(root, files, expected_source_pages=2, source_pages_included=1)["valid"]
    Path(files["quality_json"]).write_text('{"source_page_conservation":"not_verified","source_pages":1}', encoding="utf-8")
    assert not _verify(root, files)["valid"]


def test_file_outside_revision_directory_is_rejected(complete_outputs, tmp_path):
    root, files = complete_outputs
    outside = root.parent / "outside-qa.html"
    outside.write_text("<html></html>", encoding="utf-8")
    files["quality_html"] = str(outside)
    assert not _verify(root, files)["valid"]


def test_zip_windows_drive_entry_is_rejected(complete_outputs):
    root, files = complete_outputs
    with ZipFile(files["package_zip"], "a") as zipped:
        zipped.writestr("C:/outside.txt", "unexpected")
    report = _verify(root, files)
    assert not report["valid"]
    assert any("不安全路径" in error for error in report["errors"])


def test_required_continuous_pagination_cannot_be_omitted(complete_outputs):
    root, files = complete_outputs
    report = verify_artifact_manifest(root, files, expected_source_pages=1, source_pages_included=1, require_pagination=True)
    assert not report["valid"]
    assert any("连续页码" in error for error in report["errors"])
