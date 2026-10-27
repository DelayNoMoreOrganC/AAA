"""Recheck an existing intake-date default against completely read additions.

No extra reads or model requests. Retained contract pages remain bound to their
unchanged parent files; newly read pages are never supplied as old-page text.
"""
from copy import deepcopy
import os
import re

from document_title_review import title_evidence
from intake_contract_date import FIELD, KEY, IDENTITY, BINDING, LABEL, RISK, compact, current_support, dates, digest

RECEIPT = '_intake_date_supplement_read'
ENGAGEMENT_TITLES = {'委托代理合同', '委托合同', '法律服务合同'}


def path(value):
    return os.path.normcase(os.path.abspath(value)) if isinstance(value, str) and value else ''


def scope(rows):
    if not isinstance(rows, list) or not rows:
        return None
    out = {}
    for row in rows:
        if (not isinstance(row, dict) or not path(row.get('path')) or path(row['path']) in out
                or type(row.get('pages')) is not int or row['pages'] < 1
                or not isinstance(row.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', row['sha256'])
                or not isinstance(row.get('file_id'), str) or not row['file_id']):
            return None
        out[path(row['path'])] = {k: row[k] for k in ('file_id', 'path', 'sha256', 'pages')}
    return out


def collect(fields, page_cache, allowed_sources, document_units, supplied):
    """Record only a fully observed, frozen new-file scope for later recheck."""
    fields.pop(RECEIPT, None)
    if not isinstance(supplied, dict) or not isinstance(supplied.get('binding'), dict):
        return
    rows = scope(supplied.get('date_added_scope'))
    if not rows or sum(r['pages'] for r in rows.values()) > 500:
        return
    expected = {(r['path'], n) for r in rows.values() for n in range(1, r['pages'] + 1)}
    if set(allowed_sources) != expected or not expected <= page_cache.keys():
        return
    documents, seen = [], set()
    for unit in document_units:
        keys = [(unit.source_path, n + 1) for n in range(unit.start_page, unit.end_page + 1)]
        if not keys or any(k in seen or k not in expected for k in keys):
            return
        if any(not isinstance(page_cache[k], str) or not 0 < len(page_cache[k].strip()) <= 18000 for k in keys):
            return
        seen.update(keys)
        documents.append(dict(pages=[dict(source_path=p, page=n, quote=page_cache[(p, n)]) for p, n in keys]))
    if seen != expected:
        return
    fields[RECEIPT] = dict(binding=deepcopy(supplied['binding']), sources=list(rows.values()), documents=documents)


def refresh(fields, previous, delta, supplied, manual_fields, current_manifest, conflicts=()):
    """Preserve only a revalidated default; leave ordinary invalidation intact otherwise."""
    if not isinstance(supplied, dict) or delta.get('_ocr_review'):
        return False
    for key in (FIELD, '收案日期'):
        refs = (previous.get('_provenance') or {}).get(key) or []
        refs = [refs] if isinstance(refs, dict) else refs
        if key in manual_fields or any(r.get('method') == 'human' for r in refs):
            return False
    if fields.get('收案日期') or any(fields.get(k) != previous.get(k) for k in IDENTITY):
        return False
    all_conflicts = list(fields.get('_field_conflicts') or []) + [r.get('detail', r) for r in conflicts]
    if any(r.get('field') in (*IDENTITY, FIELD) and not r.get('resolved') for r in all_conflicts):
        return False
    receipt = delta.get(RECEIPT)
    old, added, current = (scope(supplied.get(k)) for k in ('date_previous_scope', 'date_added_scope', 'date_current_scope'))
    if (not all((old, added, current)) or set(old) & set(added) or {**old, **added} != current
            or current != scope(current_manifest) or not isinstance(receipt, dict)
            or receipt.get('binding') != supplied.get('binding') or scope(receipt.get('sources')) != added):
        return False
    previous_refs = (previous.get('_provenance') or {}).get(FIELD) or []
    previous_refs = [previous_refs] if isinstance(previous_refs, dict) else previous_refs
    original = next((r for r in previous_refs if current_support(r, previous) is not None), None)
    if original is None:
        return False
    from intake_contract_date import scope_supported
    if not scope_supported(previous, list(old.values())):
        return False
    bundle = deepcopy(previous[KEY])
    documents = receipt.get('documents')
    if not isinstance(documents, list) or not documents:
        return False
    expected = {(r['path'], n) for r in added.values() for n in range(1, r['pages'] + 1)}
    seen, new_contracts = set(), []
    for document in documents:
        pages = document.get('pages') if isinstance(document, dict) else None
        if not isinstance(pages, list) or not pages:
            return False
        for page in pages:
            if not isinstance(page, dict):
                return False
            key = (page.get('source_path'), page.get('page'))
            if key not in expected or key in seen or not isinstance(page.get('quote'), str) or not 0 < len(page['quote']) <= 18000:
                return False
            seen.add(key)
        title = title_evidence(pages[0]['quote'])
        if not title or not title.get('verified'):
            return False
        if title.get('title') in ENGAGEMENT_TITLES:
            if dates(document, bundle['identity']) is None:
                return False
            new_contracts.append(deepcopy(document))
        else:
            # A known first-page title alone cannot exclude an embedded
            # engagement, correction or signing-date statement on later pages.
            for page in pages:
                text = compact(page['quote'])
                embedded = any(compact(line) in ENGAGEMENT_TITLES for line in page['quote'].splitlines())
                page_title = title_evidence(page['quote']) or {}
                if (RISK.search(text) or re.search(LABEL, page['quote']) or embedded
                        or page_title.get('title') in ENGAGEMENT_TITLES
                        or re.search(r'(?:更正|变更|调整|修正).{0,24}(?:委托|合同|日期)|(?:委托|合同|日期).{0,24}(?:更正|变更|调整|修正|有误)', text)
                        or re.search(r'(?:本合同于|双方于.{0,24}签订本合同)', text)):
                    return False
    if seen != expected:
        return False
    bundle['documents'] += new_contracts
    choices = [choice for document in bundle['documents'] for choice in (dates(document, bundle['identity']) or [])]
    values = sorted({r['value'] for r in choices})
    if len(values) != 1 or values[0] != previous.get(FIELD):
        fields.setdefault('_field_conflicts', []).append(dict(field=FIELD, values=values,
            reason_code='engagement_dates_conflict', sources=deepcopy(choices),
            reason='新增委托合同与原合同签订日期不同，请核对适用合同'))
        fields[FIELD] = ''
        return False
    bundle['source_scope'] = [dict(source_path=r['path'], pages=r['pages']) for r in current.values()]
    bundle['scope_certificates'] = list(current.values())
    # Keep why this expanded source scope was accepted, not just a new digest.
    bundle.setdefault('supplement_checks', []).append(deepcopy(receipt))
    fields[KEY] = bundle
    fields[FIELD] = values[0]
    new_ref = {**deepcopy(original), 'bundle_digest': digest(bundle)}
    refs = fields.setdefault('_provenance', {}).setdefault(FIELD, [])
    if new_ref not in refs:
        refs.append(new_ref)
    return True
