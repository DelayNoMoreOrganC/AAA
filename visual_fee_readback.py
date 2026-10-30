"""Two independent notice-page readings inside the existing single review.

Only the fee derivation may consume these observations. They never replace OCR
or become a general-purpose source of facts. Agreement is not an accuracy claim.
"""
from copy import deepcopy
import hashlib
import json
import os

from source_fee_notice import compact, has_explicit_fixed_choice

VERSION = 'fee-notice-image-readback-v1'
FIELD = '收费标准'
MAX_TEXT = 8000


def _digest(body):
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _text(value):
    return compact(value).replace('_', '')


def _reading(action, key):
    rows = action.get('page_readbacks')
    if not isinstance(rows, list) or len(rows) > 3:
        return None
    if sum(len(r.get('text', '')) for r in rows if isinstance(r, dict)
           and isinstance(r.get('text'), str)) > 12000:
        return None
    matches = [r for r in rows if isinstance(r, dict) and r.get('page_id') == key]
    if len(matches) != 1:
        return None
    row = matches[0]
    text = row.get('text')
    if (row.get('full_page_complete') is not True or row.get('legibility') != 'clear'
            or not isinstance(text, str) or not 0 < len(text) <= MAX_TEXT
            or not _text(text).startswith('委托代理通知书')):
        return None
    # Probe the choice, not case identity. Identity is checked after all document
    # passes, using accepted case fields, before a fee can be committed.
    return text if has_explicit_fixed_choice(text) else None


def proposal_scope(action, key, pages):
    """Freeze only a caller-scoped notice first page; no reads or model calls."""
    text = _reading(action, key)
    if text is None or key not in pages.pages:
        return {}
    path, number = pages.pages[key]
    cached = getattr(pages, 'texts', {}).get(path, [])
    if number < len(cached) and isinstance(cached[number], str):
        if has_explicit_fixed_choice(cached[number]) and _text(cached[number]) == _text(text):
            return {}  # The normal cached-source path already preserves choices.
    source = getattr(pages, 'source_identities', {}).get(path, {})
    if not _sha(source.get('sha256')):
        return {}
    return {(FIELD, key): {'first_text': text, 'source_path': path,
                          'page': number + 1, 'source_sha256': source['sha256']}}


def receipts(action, frozen, pages):
    result = []
    for (field, key), first in frozen.items():
        second = _reading(action, key)
        if field != FIELD or second is None or _text(second) != _text(first['first_text']):
            continue
        path, number = pages.pages[key]
        source = getattr(pages, 'source_identities', {}).get(path, {})
        if (path != first['source_path'] or number + 1 != first['page']
                or source.get('sha256') != first['source_sha256']):
            continue
        body = {**deepcopy(first), 'second_text': second, 'version': VERSION,
                'source_text_overwritten': False, 'accuracy_verified': False}
        result.append({'body': body, 'sha256': _digest(body)})
    return result


def supported(receipt, *, path, page, quote, source_sha256):
    if not isinstance(receipt, dict) or not isinstance(receipt.get('body'), dict):
        return False
    body = receipt['body']
    try:
        if receipt.get('sha256') != _digest(body):
            return False
    except (ValueError, TypeError):
        return False
    first, second = body.get('first_text'), body.get('second_text')
    if (body.get('version') != VERSION or body.get('source_text_overwritten') is not False
            or body.get('accuracy_verified') is not False or not _sha(source_sha256)
            or body.get('source_sha256') != source_sha256
            or type(page) is not int or page < 1 or body.get('page') != page
            or not isinstance(path, str) or not path or body.get('source_path') != path
            or not all(isinstance(t, str) and 0 < len(t) <= MAX_TEXT for t in (first, second))
            or second != quote or _text(first) != _text(second)):
        return False
    return bool(_reading({'page_readbacks': [{'page_id': 'p', 'text': second,
        'full_page_complete': True, 'legibility': 'clear'}]}, 'p'))


def current_reference_supported(ref, source_manifest=None):
    if not supported(ref.get('notice_visual_readback'), path=ref.get('source_path'),
            page=ref.get('page'), quote=ref.get('quote'), source_sha256=ref.get('source_sha256')):
        return False
    if source_manifest is None:
        return True
    path = os.path.normcase(os.path.abspath(ref['source_path']))
    return any(isinstance(row, dict) and isinstance(row.get('path'), str)
        and os.path.normcase(os.path.abspath(row['path'])) == path
        and row.get('sha256') == ref['source_sha256'] and type(row.get('pages')) is int
        and row['pages'] >= ref['page'] for row in source_manifest)
