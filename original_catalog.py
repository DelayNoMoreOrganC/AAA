"""Fill only page-number cells of the firm's supplied, immutable PDF catalogs.

Internal sequence IDs are stable identifiers, not printed row numbers. Civil
and administrative volumes use 17 rows without execution materials, 18 with
them. Existing execution materials alone activate that row; an execution-stage
label or a skipped/missing slot must not create it.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import fitz

ROOT = Path(__file__).resolve().parent / "templates" / "workstation-originals" / "source"
SOURCES = {
    "civil": ("民事案卷目录（含送达材料清单）.pdf", "2125bc489cb0f15c93a3c7439bc8a2f973a33bd6e747dd1716b419c94b3079e7", 17),
    "admin": ("行政案卷目录 （含送达材料清单）.pdf", "5d2464743e6709bc188e773ef6d756d00cca199522bf5af37b05c543b5a342c5", 17),
    "criminal": ("刑事案卷目录（含送达材料清单）.pdf", "bf5828b7d9073365a5de40033c83a7773dfc962eba39fd88a75cb3c8aa0c7e22", 18),
    "nonlit": ("非诉案卷目录（含送达材料清单）.pdf", "028759ca2f4698a03d06232157b7a9c724f5f9b29e3060dffe83a21c6b18381e", 10),
    "counsel": ("顾问案卷目录 （含送达材料清单）.pdf", "95a0a80a49c1fd541c927b2ea35b243740a637c4cad4a6e674bc0fac9f745fbd", 9),
    "civil_execution": ("../prepared/民事案卷目录（含执行材料）.pdf", "cfaa27c09134d0b14f2f5a9ddc0de26741fe940b9259c166d83cdc28c73b2f72", 18),
    "admin_execution": ("../prepared/行政案卷目录（含执行材料）.pdf", "f9d5614b7c5f7168ae1cbf5dc76ce052192496d8b4a21814f4a01f035e39ef96", 18),
}


class OriginalCatalogError(ValueError):
    def __init__(self):
        super().__init__("原目录模板缺失、校验失败或存在未对应的归档项目")


def selected_variant(case_type, has_execution=False):
    return case_type + "_execution" if has_execution and case_type in ("civil", "admin") else case_type


def row_mapping(case_type, has_execution=False):
    case_type = selected_variant(case_type, has_execution)
    if case_type not in SOURCES:
        raise OriginalCatalogError()
    mapping = {i: i for i in range(1, SOURCES[case_type][2] + 1)}
    if case_type in ("civil", "admin"):
        mapping = {i: i for i in range(1, 15)} | {16: 15, 17: 16, 18: 17}
    return mapping


def _open(case_type):
    if case_type not in SOURCES:
        raise OriginalCatalogError()
    name, digest, _ = SOURCES[case_type]
    try:
        payload = (ROOT / name).read_bytes()
        if hashlib.sha256(payload).hexdigest() != digest:
            raise OriginalCatalogError()
        document = fitz.open(stream=payload, filetype="pdf")
        if len(document) != 1:
            document.close()
            raise OriginalCatalogError()
        return document
    except (OSError, fitz.FileDataError):
        raise OriginalCatalogError() from None


def _cells(page, count):
    vertical, horizontal = set(), set()
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if rect.width < 2 and rect.height > 100:
            vertical.add(round(rect.x0, 2))
        if rect.height < 2 and rect.width > 300:
            horizontal.add(round(rect.y0, 2))
    xs, ys = sorted(vertical), sorted(horizontal)
    if len(xs) != 4:
        raise OriginalCatalogError()
    rows = {}
    for word in page.get_text("words"):
        if not word[4].isdigit() or not xs[0] < word[0] < xs[1]:
            continue
        row = int(word[4])
        if not 1 <= row <= count:
            continue
        center = (word[1] + word[3]) / 2
        lower = [y for y in ys if y < center]
        upper = [y for y in ys if y > center]
        if not lower or not upper or row in rows:
            raise OriginalCatalogError()
        rows[row] = fitz.Rect(xs[-2], max(lower), xs[-1], min(upper))
    if set(rows) != set(range(1, count + 1)):
        raise OriginalCatalogError()
    return rows


def original_catalog_pdf(case_type, body_starts, cover_end_idx, *, pagination_mode="legacy"):
    case_type = selected_variant(case_type, 15 in body_starts)
    mapping = row_mapping(case_type)
    if set(body_starts) - {0} - set(mapping):
        raise OriginalCatalogError()
    document = _open(case_type)
    try:
        page = document[0]
        cells = _cells(page, SOURCES[case_type][2])
        for seq, body_index in body_starts.items():
            if seq == 0 or pagination_mode == "draft":
                continue
            if pagination_mode == "body" and body_index < cover_end_idx:
                continue
            printed = body_index-cover_end_idx+1 if pagination_mode == "body" else body_index + (1 if body_index < cover_end_idx else 2)
            cell = cells[mapping[seq]]
            value = str(printed)
            size = 11
            width = fitz.get_text_length(value, fontname="tiro", fontsize=size)
            if width > cell.width - 6:
                raise OriginalCatalogError()
            page.insert_text((cell.x0 + (cell.width - width) / 2,
                              cell.y0 + (cell.height + size * .65) / 2), value,
                             fontname="tiro", fontsize=size, color=(0, 0, 0))
        return document
    except Exception:
        document.close()
        raise


def navigation_rows(case_type, body_starts, cover_end_idx):
    case_type = selected_variant(case_type, 15 in body_starts)
    mapping = row_mapping(case_type)
    with _open(case_type) as source:
        cells = _cells(source[0], SOURCES[case_type][2])
    return [(cells[mapping[seq]], body_index if body_index < cover_end_idx else body_index + 1)
            for seq, body_index in body_starts.items() if seq != 0 and seq in mapping]


def source_metadata(case_type, has_execution=False):
    case_type = selected_variant(case_type, has_execution)
    name, digest, _ = SOURCES[case_type]
    return {"renderer": "lawfirm-original-pdf-v1", "source_name": name,
            "source_sha256": digest, "pages": 1, "legal_status": "user_supplied_template_not_regulatory_verification"}
