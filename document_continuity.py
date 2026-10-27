"""Correct over-segmentation from independently read numbered document pages.

Only consecutive pages in one source, beginning at document page one, with a
matching heading, document identity and total count qualify. No new reads or
model calls; model confidence or a shared title alone cannot join documents.
"""
import re
import unicodedata


def page_context(text, evidence):
    if not evidence or not evidence.get('verified'):
        return None
    lines = [re.sub(r'\s+', '', unicodedata.normalize('NFKC', s)) for s in text.splitlines() if s.strip()]
    # Only complete standalone header/footer labels, never a prose reference.
    edges = lines[:3] + lines[-3:]
    pattern = r'第([1-9]\d{0,3})页(?:[,，/、]?共|/)([1-9]\d{0,3})页'
    markers = {tuple(map(int, m.groups())) for line in edges if (m := re.fullmatch(pattern, line))}
    if len(markers) != 1:
        return None
    number, total = next(iter(markers))
    if not 1 <= number <= total <= 2000:
        return None
    identifiers = {m[1] for line in lines[:6]
        if (m := re.fullmatch(r'(?:合同编号|合同号):([A-Za-z0-9\u3400-\u9fff_()/\-]{1,80})', line))}
    if len(identifiers) > 1:
        return None
    identity = ('contract', next(iter(identifiers))) if identifiers else (
        ('case', evidence['_identity']) if evidence.get('_identity') else None)
    if identity is None:
        return None
    return dict(number=number, total=total, identity=identity,
        heading=evidence['title'], doc_type=evidence['doc_type'],
        role=evidence['document_role'], stage=evidence['procedure_stage'])


def reconcile(rows, pages, reviewed):
    output = [dict(row) for row in rows]
    chain, audit = None, []
    for index, row in enumerate(output):
        evidence, status = reviewed.get(index, (None, 'not_reviewed'))
        context = evidence.get('_page_context') if evidence and status == 'read' else None
        location = pages.pages[row['page_id']]
        joined = (chain and context and location == (chain['location'][0], chain['location'][1]+1)
            and context['number'] == chain['context']['number']+1
            and all(context[k] == chain['context'][k] for k in ('total','identity','heading','doc_type','role','stage'))
            and row['doc_type'] == context['doc_type'])
        if joined:
            if row['document_start']:
                row['document_start'] = False
                # Joining must not silently drop a formerly selected first
                # page from field extraction (e.g. fee terms on a middle page).
                row['_preserve_extraction_page'] = True
                audit.append(dict(source_path=location[0], page=location[1]+1,
                    effective_doc_type=row['doc_type'], title=evidence['title'],
                    method='local_document_continuity', reason_code='numbered_continuation_verified',
                    independent_context_verified=True, fields_verified=False))
            chain = dict(context=context, location=location)
        elif context and context['number'] == 1 and row['document_start']:
            chain = dict(context=context, location=location)
        else:
            chain = None
    return output, audit
