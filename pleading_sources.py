"""Complete pleading bundles. Multiple versions never mean first/last wins."""
import math
from copy import deepcopy
from document_title_review import title_evidence


def collect(units, cache, allowed):
    candidates = [u for u in units if u.doc_type == 'complaint']
    if not 1 <= len(candidates) <= 8:
        return []
    result, seen = [], set()
    for unit in candidates:
        score = unit.confidence
        if (type(score) not in (int, float) or not math.isfinite(score) or score < .75
                or not 0 <= unit.start_page <= unit.end_page < unit.start_page + 8):
            return []
        keys = [(unit.source_path, n+1) for n in range(unit.start_page, unit.end_page+1)]
        if any(k in seen or k not in allowed or not isinstance(cache.get(k), str)
               or not 0 < len(cache[k].strip()) <= 18000 for k in keys):
            return []
        title = title_evidence(cache[keys[0]])
        if not title or not title['verified'] or title['doc_type'] != 'complaint':
            return []
        seen.update(keys)
        result.append({'doc_id': str(unit.doc_id), 'pages': [
            {'source_path': path, 'page': n, 'quote': cache[(path,n)]} for path,n in keys]})
    return result


def pack(documents):
    return deepcopy(documents[0]) if len(documents) == 1 else {
        **deepcopy(documents[0]), 'documents': deepcopy(documents)}


def unpack(source):
    if not isinstance(source, dict):
        return []
    documents = source.get('documents')
    if documents is None:
        return [source]
    if (not isinstance(documents, list) or not 2 <= len(documents) <= 8
            or any(not isinstance(d, dict) or 'documents' in d for d in documents)
            or any(source.get(k) != documents[0].get(k) for k in ('doc_id','pages'))):
        return []
    seen = set()
    for document in documents:
        for page in document.get('pages', []):
            key = (page.get('source_path'), page.get('page'))
            if key in seen:
                return []
            seen.add(key)
    return documents


def references(source):
    return [deepcopy(p) for d in unpack(source) for p in d.get('pages', [])]
