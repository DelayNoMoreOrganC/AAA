"""Recover a literal source span when only form-fill underscores differ.

This does not repair OCR or normalize field values. Both the untouched source
and a comparison copy must pass the existing semantic validator. No I/O.
"""
import unicodedata

from fact_evidence import normalized_source_text as compact, validated_fact_field
from form_field_policy import policy

VERSION = 'same-page-underscore-alignment-v1'


def recover(field, value, submitted_quote, page_text):
    rule = policy(field)
    if not rule or rule[0] != 'literal':
        return None
    if (not all(isinstance(v, str) and v for v in (value, submitted_quote, page_text))
            or len(value) > 1000 or len(submitted_quote) > 1500 or len(page_text) > 18000):
        return None
    val, quote, page = map(compact, (value, submitted_quote, page_text))
    if '_' in val or val not in quote or quote in page:
        return None
    needle = quote.replace('_', '')
    comparison = page.replace('_', '')
    if needle == quote and comparison == page:
        return None
    start = comparison.find(needle)
    if start < 0 or comparison.find(needle, start + 1) >= 0:
        return None  # A repeated clause is not a unique location.
    # Map the comparison span back to exact original characters. Refuse exotic
    # cross-character normalization rather than inventing source coordinates.
    chars, offsets, full = [], [], []
    for index, char in enumerate(page_text):
        for normalized in unicodedata.normalize('NFKC', char):
            if not normalized.isspace():
                full.append(normalized)
                if normalized != '_':
                    chars.append(normalized)
                    offsets.append(index)
    if ''.join(full) != page or ''.join(chars) != comparison:
        return None
    left, right = offsets[start], offsets[start + len(needle) - 1] + 1
    recovered = page_text[left:right]
    if len(recovered) > 1500 or val not in compact(recovered):
        return None
    accepted = validated_fact_field(field, value, recovered, page_text)
    # Never let underscores conceal a negation, role qualifier or condition in
    # the original source. Keep line structure for field-specific role checks.
    plain_quote = unicodedata.normalize('NFKC', recovered).replace('_', '')
    plain_page = unicodedata.normalize('NFKC', page_text).replace('_', '')
    if not accepted or validated_fact_field(field, value, plain_quote, plain_page) != accepted:
        return None
    return {'quote': recovered, 'accepted_field': accepted, 'alignment': {
        'version': VERSION, 'submitted_quote': submitted_quote,
        'source_char_span': [left, right], 'comparison_only': True,
        'source_text_overwritten': False, 'value_changed': False}}
