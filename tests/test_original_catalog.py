import fitz
import pytest

@pytest.mark.parametrize("mode", ["draft", "body"])
@pytest.mark.parametrize("case_type", ["civil", "admin", "criminal", "nonlit", "counsel"])
def test_draft_and_body_pagination_preserves_sources_and_directory(tmp_path, mode, case_type):
    from archive_pagination import verify_volume_pagination
    import archive_catalog as ac
    import original_catalog as original_module
    # Use each catalog's actual first manual slot; no real case or model call.
    slot = next(item for item in ac.get_catalog(case_type) if item.source == "manual")
    def pdf(name, pages):
        path = tmp_path / name
        with fitz.open() as document:
            for n in range(pages):
                page = document.new_page(width=300, height=420)
                page.insert_text((30, 60), f"SYNTHETIC {name} {n}")
                page.insert_text((130, 410), "old 99")
            document.save(path)
        return str(path)
    source, cover = pdf("source.pdf", 2), pdf("cover.pdf", 2)
    output = str(tmp_path / "result.pdf")
    unit = DocumentUnit(0, "evidence", 0, 1, catalog_seq=slot.seq, source_path=source)
    result = build_full_archive(case_type, source, {"档案卷宗":cover}, [unit], {}, [], output,
        use_original_catalog=True, pagination_mode=mode, log=lambda *_:None)
    assert result.success and result.original_pages_included == 2
    assert result.pagination == {"mode":mode, "body_start":3}
    with fitz.open(output) as doc, fitz.open(source) as original, fitz.open(cover) as covers:
        verify_volume_pagination(doc, result.pagination)
        assert len(doc) == 5
        for n in range(2):
            assert doc[n].rect == covers[n].rect
            assert doc[n].get_pixmap().samples == covers[n].get_pixmap().samples
            page = doc[n+3]
            assert page.get_pixmap(clip=original[n].rect).samples == original[n].get_pixmap().samples
            assert "old 99" in page.get_text()
            if mode == "draft":
                assert page.rect == original[n].rect
                assert page.get_text() == original[n].get_text()
        variant = original_module.selected_variant(case_type, slot.seq == 15)
        cells = original_module._cells(doc[2], original_module.SOURCES[variant][2])
        cell = cells[original_module.row_mapping(variant)[slot.seq]]
        assert doc[2].get_textbox(cell).strip() == ("1" if mode == "body" else "")
        assert any(link["page"] == 3 and link["from"].intersects(cell) for link in doc[2].get_links())
        assert any(row[2] == 4 for row in doc.get_toc())


import original_catalog as original
from pdf_archive_merger import build_full_archive
from pdf_doc_locator import DocumentUnit


@pytest.mark.parametrize("kind", original.SOURCES)
def test_original_directory_only_fills_page_cells(kind):
    mapping = original.row_mapping(kind)
    body = {0: 0, **{seq: row + 2 for seq, row in mapping.items()}}
    with original._open(kind) as before, original.original_catalog_pdf(kind, body, 1) as after:
        assert len(after) == len(before) == 1
        assert after[0].get_drawings() == before[0].get_drawings()
        assert after[0].get_text().startswith(before[0].get_text())
        cells = original._cells(after[0], original.SOURCES[kind][2])
        for seq, row in mapping.items():
            assert str(body[seq] + 2) in after[0].get_textbox(cells[row]).strip()
        # Raster comparison outside the only writable (rightmost) column.
        left = fitz.Rect(0, 0, min(c.x0 for c in cells.values()) - 1, after[0].rect.height)
        assert after[0].get_pixmap(clip=left).samples == before[0].get_pixmap(clip=left).samples


def test_civil_closing_forms_keep_original_row_numbers():
    assert original.row_mapping("civil")[16] == 15
    assert original.row_mapping("civil")[17] == 16
    assert original.row_mapping("civil")[18] == 17


def test_no_silent_fallback_for_unprovided_directory():
    for kind, starts in [("civil", {100: 2}), ("arbitration", {3: 2})]:
        with pytest.raises(original.OriginalCatalogError):
            original.original_catalog_pdf(kind, starts, 1)


@pytest.mark.parametrize("case_type", ["civil", "admin"])
def test_execution_presence_selects_18_or_17_rows(case_type):
    for has_execution in (False, True):
        starts = {1:1, 3:2, 16:8, 17:10, 18:11}
        if has_execution:
            starts[15] = 7
        with original.original_catalog_pdf(case_type, starts, 1) as document:
            assert len(document) == 1
            text = document[0].get_text()
            assert ("执行申请书" in text) is has_execution
            mapping = original.row_mapping(case_type, has_execution)
            cells = original._cells(document[0], 18 if has_execution else 17)
            assert document[0].get_textbox(cells[mapping[16]]).strip() == "10"
            if has_execution:
                assert document[0].get_textbox(cells[15]).strip() == "9"


def test_source_hash_is_verified(tmp_path, monkeypatch):
    name = original.SOURCES["civil"][0]
    (tmp_path / name).write_bytes(b"changed")
    monkeypatch.setattr(original, "ROOT", tmp_path)
    with pytest.raises(original.OriginalCatalogError):
        original.original_catalog_pdf("civil", {3: 2}, 1)


@pytest.mark.parametrize("case_type,execution", [("civil",False),("civil",True),("admin",False),("admin",True)])
def test_whole_volume_uses_original_directory_and_click_targets(tmp_path, case_type, execution):
    def pdf(name, text, pages=1):
        path = tmp_path / name
        with fitz.open() as d:
            for _ in range(pages):
                d.new_page().insert_text((72, 72), text)
            d.save(path)
        return str(path)
    cover, approval, source = pdf("cover.pdf", "COVER"), pdf("approval.pdf", "APPROVAL"), pdf("source.pdf", "SOURCE", 2 if execution else 1)
    output = str(tmp_path / "result.pdf")
    unit = DocumentUnit(0, "contract", 0, 0, catalog_seq=3, source_path=source)
    units = [unit] + ([DocumentUnit(1,"execution",1,1,catalog_seq=15,source_path=source)] if execution else [])
    result = build_full_archive(case_type, source, {"档案卷宗": cover, "立案审批表": approval},
                                units, {}, [], output, use_original_catalog=True, log=lambda *_: None)
    assert result.success and result.original_pages_included == (2 if execution else 1)
    with fitz.open(output) as document:
        assert len(document) == (5 if execution else 4)
        assert "委托代理合同" in document[1].get_text()
        cells = original._cells(document[1], 18 if execution else 17)
        assert document[1].get_textbox(cells[3]).strip() == "4"
        links = document[1].get_links()
        assert any(link["page"] == 3 and link["from"].intersects(cells[3]) for link in links)
        if execution:
            assert document[1].get_textbox(cells[15]).strip() == "5"
            assert any(link["page"] == 4 and link["from"].intersects(cells[15]) for link in links)
        assert document[3].get_text().startswith("SOURCE")


def test_existing_intake_is_preserved_once_instead_of_generated_replacement(tmp_path):
    source=tmp_path/'source.pdf';cover=tmp_path/'cover.pdf';replacement=tmp_path/'replacement.pdf'
    for path,texts in ((source,['ORIGINAL INTAKE','CONTRACT']), (cover,['COVER']), (replacement,['MUST NOT APPEAR'])):
        with fitz.open() as d:
            for text in texts:d.new_page().insert_text((72,72),text)
            d.save(path)
    units=[DocumentUnit(0,'intake_approval',0,0,catalog_seq=1,source_path=str(source)),
           DocumentUnit(1,'contract',1,1,catalog_seq=3,source_path=str(source))]
    output=str(tmp_path/'result.pdf')
    result=build_full_archive('civil',str(source),{'档案卷宗':str(cover),'立案审批表':str(replacement)},
                             units,{},[],output,use_original_catalog=True,log=lambda *_:None)
    assert result.success and result.original_pages_included==2
    with fitz.open(output) as d,fitz.open(source) as original:
        text=''.join(p.get_text() for p in d)
        assert text.count('ORIGINAL INTAKE')==1 and 'MUST NOT APPEAR' not in text
        assert d[2].get_pixmap(clip=original[0].rect).samples==original[0].get_pixmap().samples
