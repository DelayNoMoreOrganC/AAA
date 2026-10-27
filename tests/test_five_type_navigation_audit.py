"""Checker regressions: valid-range navigation is insufficient evidence."""
from copy import deepcopy

import fitz

from scripts.check_five_type_navigation_20261024 import (
    bookmark_errors, footer_errors, map_source_pages, row_errors, row_slot,
)


def test_link_to_different_valid_page_is_rejected():
    row = {"printed_page_text": ["4"], "links": [{"kind": fitz.LINK_GOTO, "target_page": 5}]}
    assert row_errors(row, [4]) == ["link_targets_different_document_or_continuation"]


def test_same_category_link_must_land_on_first_page():
    row = {"printed_page_text": ["6"], "links": [{"kind": fitz.LINK_GOTO, "target_page": 7}]}
    assert row_errors(row, [6, 7])
    row["links"][0]["target_page"] = 6
    assert not row_errors(row, [6, 7])


def test_printed_page_and_link_are_independent_checks():
    row = {"printed_page_text": ["5"], "links": [{"kind": fitz.LINK_GOTO, "target_page": 4}]}
    assert row_errors(row, [4]) == ["printed_page_does_not_equal_semantic_start"]
    row["printed_page_text"] = ["4"]
    row["links"].append(deepcopy(row["links"][0]))
    assert row_errors(row, [4]) == ["missing_duplicate_or_nonlocal_link"]


def test_absent_material_is_blank_and_not_clickable():
    assert not row_errors({"printed_page_text": [], "links": []}, [])
    assert row_errors({"printed_page_text": ["4"], "links": [{"kind": 1, "target_page": 4}]}, [])


def test_bookmark_swap_within_bounds_is_rejected():
    expected = [("contract", 4), ("judgment", 5)]
    assert not bookmark_errors([[1, "contract", 4], [1, "judgment", 5]], expected)
    assert bookmark_errors([[1, "contract", 5], [1, "judgment", 4]], expected)
    assert bookmark_errors([[1, "contract", 4]], expected)


def test_civil_17_rows_keep_internal_slots_after_execution_omission():
    assert [row_slot("civil", x) for x in (14, 15, 16, 17)] == [14, 16, 17, 18]
    assert row_slot("admin", 15) == 15


def test_footer_checks_total_and_page_even_when_original_has_numbers():
    document = fitz.open()
    page = document.new_page(width=200, height=224)
    page.insert_text((30, 50), "GD 2 / 3")  # Original source number cannot count.
    page.insert_text((30, 218), "GD 1 / 3", fontsize=9)
    assert not footer_errors(page, 1, 3)
    assert footer_errors(page, 2, 3)
    assert footer_errors(page, 1, 4)


def test_full_source_pixels_detect_omission_duplicate_and_changed_page(tmp_path):
    from hashlib import sha256
    source = fitz.open()
    source.new_page(width=200, height=200).insert_text((30, 50), "Synthetic source")
    path = tmp_path / "source.pdf"
    source.save(path)
    item = {"normalized_pdf": str(path), "file": "fixture.pdf", "pages": 1,
            "sha256": sha256(path.read_bytes()).hexdigest()}
    archive = fitz.open()
    page = archive.new_page(width=200, height=224)
    page.show_pdf_page(fitz.Rect(0, 0, 200, 200), source, 0)
    page.insert_text((30, 218), "GD 1 / 1", fontsize=9)
    matches, passed = map_source_pages(archive, [item])
    assert passed and matches[0]["output_pages"] == [1]
    archive.new_page(width=200, height=224).show_pdf_page(fitz.Rect(0, 0, 200, 200), source, 0)
    assert not map_source_pages(archive, [item])[1]
    archive.delete_page(1)
    archive[0].insert_text((30, 80), "Changed content")
    assert not map_source_pages(archive, [item])[1]
