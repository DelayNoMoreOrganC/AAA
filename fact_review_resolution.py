"""Close a superseded proposal only while its verified replacement is current.

No model output can set these receipts. They are created after local evidence
verification, preserve rejected attempts for audit, and never certify OCR quality.
"""
import hashlib
import json
import os


def _path(value):
    return os.path.normcase(os.path.abspath(value)) if isinstance(value, str) and value else ''


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _digest(ref):
    return hashlib.sha256(json.dumps(ref, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def mark_targeted_resolution(rejected, verified, source_identities):
    """Mark only the original attempts replaced by this one-shot review."""
    sources = {_path(row.get('source_path')): row for row in source_identities.values()
               if isinstance(row, dict)}
    for field, value, ref in verified:
        source = sources.get(_path(ref.get('source_path')), {})
        if ref.get('method') != 'visual_agent_local_evidence' or not _sha(source.get('sha256')):
            continue
        from visual_fact_readback import has_readback, reference_supported
        if has_readback(ref) and not reference_supported(ref, field, value,
                [{'path': source.get('source_path'), 'sha256': source.get('sha256'), 'pages': source.get('page_count')}]):
            continue
        for entry in rejected:
            if (isinstance(entry, dict) and entry.get('reason_code') == 'local_evidence_rejected'
                    and not entry.get('resolution') and entry.get('field') == field
                    and _path(entry.get('source_path')) == _path(ref.get('source_path'))
                    and type(entry.get('page')) is int and entry['page'] == ref.get('page')):
                entry.update(resolution='accepted_after_targeted_review', resolution_evidence={
                    'source_sha256': source['sha256'], 'reference_sha256': _digest(ref)})


def current_targeted_reference(entry, fields, source_manifest):
    """Return the exact current replacement, or None when doubt must reappear."""
    if (not isinstance(entry, dict) or entry.get('resolution') != 'accepted_after_targeted_review'
            or entry.get('reason_code') != 'local_evidence_rejected'):
        return None
    field = entry.get('field')
    if not isinstance(field, str) or not isinstance(fields.get(field), str) or not fields[field].strip():
        return None
    if any(isinstance(row, dict) and row.get('field') == field and row.get('resolved') is not True
           for row in fields.get('_field_conflicts') or []):
        return None
    receipt = entry.get('resolution_evidence')
    if (not isinstance(receipt, dict) or not _sha(receipt.get('source_sha256'))
            or not _sha(receipt.get('reference_sha256'))):
        return None
    page = entry.get('page')
    if type(page) is not int or page < 1:
        return None
    if not any(isinstance(row, dict) and _path(row.get('path')) == _path(entry.get('source_path'))
               and type(row.get('pages')) is int and page <= row['pages']
               and row.get('sha256') == receipt['source_sha256'] for row in source_manifest or []):
        return None
    provenance = fields.get('_provenance') or {}
    refs = provenance.get(field, []) if isinstance(provenance, dict) else []
    refs = [refs] if isinstance(refs, dict) else refs
    for ref in refs if isinstance(refs, list) else []:
        if (isinstance(ref, dict) and ref.get('method') == 'visual_agent_local_evidence'
                and ref.get('value') == fields[field] and ref.get('page') == page
                and _path(ref.get('source_path')) == _path(entry.get('source_path'))
                and isinstance(ref.get('quote'), str) and ref['quote'].strip()):
            from visual_fact_readback import has_readback, reference_supported
            if has_readback(ref) and not reference_supported(ref, field, fields[field], source_manifest):
                continue
            try:
                if _digest(ref) == receipt['reference_sha256']:
                    return ref
            except (ValueError, TypeError):
                continue
    return None
