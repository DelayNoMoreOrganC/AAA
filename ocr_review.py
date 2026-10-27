"""Page-level review hints; no source text is copied into diagnostics.

These are explainable engineering heuristics, not an OCR accuracy score or a
finding that a page is legally unnecessary. Every page is inspected separately,
even when segmentation places a blank page inside the preceding document.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Mapping

SPARSE_OCR_CHARACTERS = 12
LOW_MEAN_CONFIDENCE = 0.85
LOW_LINE_CONFIDENCE = 0.75
MAX_REVIEW_REGIONS = 12


def normalized_review_box(value):
    """Accept only a finite, nonempty rectangle in original-page coordinates."""
    if (not isinstance(value, (list, tuple)) or len(value) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in value)
            or value[0] >= value[2] or value[1] >= value[3]):
        return None
    return list(value)


def ocr_read_payload(pages, keys):
    """Expose same-page local diagnostics to existing bounded inspection tools.

    The caller must validate allowed keys first. No extra reads or model calls;
    no source paths, raw low-score snippets, or authority to resolve a warning.
    """
    text = {key: pages.read(key)[:18000] for key in dict.fromkeys(keys)}
    diagnostics = {}
    for key in text:
        path, number = pages.pages[key]
        hints = [row for row in getattr(pages, 'ocr_review', []) if isinstance(row, dict)
                 and row.get('source_path') == path and row.get('page') == number + 1]
        if hints:
            diagnostics[key] = [{field: row[field] for field in (
                'reason_codes', 'mean_confidence', 'low_confidence_blocks',
                'low_confidence_regions', 'unlocated_low_confidence_blocks', 'regions_truncated')
                if field in row} for row in hints]
    payload = {'不可信材料文字': text}
    if diagnostics:
        payload['本地识别定位提示'] = diagnostics
    return payload


def _meaningful_count(text: str) -> int:
    if not isinstance(text, str):
        return 0
    return sum(character.isalnum() for character in text)


def find_ocr_review_issues(
    page_texts_by_path: Mapping[str, list[str]],
    layout_blocks_by_path: Mapping[str, list[dict]] | None = None,
) -> list[dict]:
    """Return one metadata-only issue per suspect page, using one-based pages.

    Layout page_idx is zero-based (local_ocr/ocr_pipeline contract). A page with
    layout text is OCR-observed; a short positive text layer without OCR blocks
    is not labelled sparse. Empty pages and page-number-only results still need
    visual review, including when failed OCR retained only a footer text layer.
    mean_confidence is character-weighted across valid [0,1] OCR scores. Missing
    confidence stays unknown rather than becoming a false perfect score.
    """
    layouts = layout_blocks_by_path or {}
    issues = []
    for source_path, pages in page_texts_by_path.items():
        by_page = defaultdict(list)
        for block in layouts.get(source_path, ()) or ():
            if not isinstance(block, dict):
                continue
            index = block.get('page_idx')
            if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(pages):
                by_page[index].append(block)
        for index, raw_text in enumerate(pages):
            text = raw_text if isinstance(raw_text, str) else ''
            characters = _meaningful_count(text)
            blocks = by_page.get(index, ())
            observed = any(isinstance(block.get('text'), str) and block['text'].strip() for block in blocks)
            scores, invalid_scores = [], 0
            low_lines = 0
            low_regions, unlocated = [], 0
            for block in blocks:
                if 'confidence' not in block or block['confidence'] is None:
                    continue
                value = block['confidence']
                try:
                    if isinstance(value, bool):
                        raise ValueError('boolean confidence')
                    score = float(value)
                    if not math.isfinite(score) or not 0 <= score <= 1:
                        raise ValueError('confidence out of range')
                except (TypeError, ValueError):
                    invalid_scores += 1
                    continue
                count = _meaningful_count(block.get('text') or '')
                scores.append((score, max(count, 1)))
                if score < LOW_LINE_CONFIDENCE and count >= 3:
                    low_lines += 1
                    box = normalized_review_box(block.get('normalized_box'))
                    if box is None:
                        unlocated += 1
                    else:
                        low_regions.append({'box': box, 'confidence': round(score, 4), 'characters': count})
            mean = sum(score * weight for score, weight in scores) / sum(weight for _, weight in scores) if scores else None
            reasons, codes = [], []
            if characters == 0:
                codes.append('empty_text')
                reasons.append('页面未取得可读取文字，请核对是否为空白页、图像证据或识别失败')
            elif re.fullmatch(r'(?:第)?\d{1,4}(?:页)?(?:[/／共]\d{1,4}页?)?', re.sub(r'\s+', '', text)):
                codes.append('page_number_only')
                reasons.append('页面只取得类似页码的文字，请核对正文是否为图像或未识别')
            elif observed and characters < SPARSE_OCR_CHARACTERS:
                codes.append('sparse_ocr')
                reasons.append('本页识别到的文字极少，请核对是否遗漏正文、签章或图像内容')
            if mean is not None and (mean < LOW_MEAN_CONFIDENCE or low_lines):
                codes.append('low_confidence')
                reasons.append('本页文字识别置信度均值偏低，请对照原文核对文字和数字'
                               if mean < LOW_MEAN_CONFIDENCE else
                               f'本页有{low_lines}个文字片段识别置信度偏低，请核对对应片段，不代表全页字段均有误')
            if invalid_scores:
                codes.append('invalid_confidence')
                reasons.append('本页识别置信度信息异常，无法据此判断识别质量，请查看原文')
            if codes:
                issues.append({
                    'source_path': str(source_path), 'page': index + 1,
                    'reason': '；'.join(reasons), 'reason_codes': codes,
                    'recognized_characters': characters, 'ocr_observed': observed,
                    'mean_confidence': round(mean, 4) if mean is not None else None,
                    'min_confidence': round(min(score for score, _ in scores), 4) if scores else None,
                    'confidence_blocks': len(scores), 'low_confidence_blocks': low_lines,
                    'invalid_confidence_blocks': invalid_scores,
                    'low_confidence_regions': low_regions[:MAX_REVIEW_REGIONS],
                    'unlocated_low_confidence_blocks': unlocated,
                    'regions_truncated': len(low_regions) > MAX_REVIEW_REGIONS,
                })
    return issues
