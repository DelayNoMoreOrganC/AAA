"""Server-owned writing context for an additive supplement, never model input.

The existing delta client spends its original writing budget on the combined
read sources. No second client, whole-volume OCR, or automatic retry is added.
"""
from copy import deepcopy
from collections import defaultdict

import form_synthesis as synthesis


class SupplementSynthesisContext:
    def __init__(self, *, case_type, fields, units, previous_manifest, current_manifest, manual, pending_conflicts=(), prior_readings=None):
        self.case_type = case_type
        self._fields, self._units = deepcopy(fields), deepcopy(units)
        self._old, self._current = deepcopy(previous_manifest), deepcopy(current_manifest)
        self._manual = deepcopy(manual)
        self._pending_conflicts = deepcopy(list(pending_conflicts))
        self._result = None
        self._failure = None
        self._used = False
        if prior_readings is not None:
            from page_reading_store import PageReadingStore
            if type(prior_readings) is not PageReadingStore or not prior_readings.readonly:
                raise ValueError('SUPPLEMENT_READING_SCOPE_INVALID')
        self._prior_readings = prior_readings
        old = {synthesis._path(r['path']): r for r in self._old}
        current = {synthesis._path(r['path']): r for r in self._current}
        if (not old or len(old) != len(self._old) or len(current) != len(self._current)
                or not set(old) < set(current)
                or any(current[p].get('sha256') != row.get('sha256')
                       or current[p].get('pages') != row.get('pages') for p, row in old.items())):
            raise ValueError('SUPPLEMENT_SYNTHESIS_SCOPE_INVALID')
        for unit in self._units:
            row = old.get(synthesis._path(unit.source_path))
            if row is None or not 0 <= unit.start_page <= unit.end_page < row['pages']:
                raise ValueError('SUPPLEMENT_SYNTHESIS_SCOPE_INVALID')

    def __deepcopy__(self, memo):
        # Like RecognitionCheckpoint, this is an in-process capability, not
        # user settings. The task dispatcher receives the result on this instance.
        return self

    def _prior_cache(self):
        cache = self._bundle_cache()
        if self._prior_readings is not None:
            # Durable full-page readings remain available even when the prior
            # writer failed. They still enter all normal fact/source validators.
            durable, ambiguous = self._prior_readings.cache_result(self._units)
            cache.update(durable)
            for key in ambiguous: cache.pop(key, None)
        return cache

    def _bundle_cache(self):
        bundle = self._fields.get(synthesis.KEY) or {}
        old_hashes = {synthesis._path(r['path']): r['sha256'] for r in self._old}
        if bundle.get('source_hashes') != old_hashes:
            return {}
        refs = (self._fields.get('_provenance') or {}).values()
        if not any(isinstance(ref, dict) and ref.get('binding') == synthesis.BINDING
                   and ref.get('bundle_digest') == synthesis.digest(bundle)
                   for group in refs for ref in (group if isinstance(group, list) else [group])):
            return {}
        paths = {synthesis._path(u.source_path): u.source_path for u in self._units}
        grouped = defaultdict(list)
        partial = {(str(doc['doc_id']), page) for doc in (bundle.get('coverage') or {}).get('documents', [])
                   for page in doc.get('missing_or_partial_pages', [])}
        for row in bundle.get('sources', []):
            path = paths.get(synthesis._path(row.get('source_path', '')))
            if (path and isinstance(row.get('text'), str) and not row.get('evidence_kind')
                    and (str(row.get('doc_id')), row.get('page')) not in partial
                    and any(u.source_path == path and u.start_page < row.get('page', 0) <= u.end_page + 1 for u in self._units)):
                grouped[path, row['page']].append(row['text'])
        # Never concatenate head/tail excerpts and pretend they are a full page.
        return {key: rows[0] for key, rows in grouped.items() if len(rows) == 1}

    def generate(self, client, fields, provenance, conflicts, units, cache, allowed, *, case_type, guard=None):
        if self._used or case_type != self.case_type:
            raise ValueError('SUPPLEMENT_SYNTHESIS_CONTEXT_INVALID')
        self._used = True
        old_paths = {synthesis._path(r['path']) for r in self._old}
        new_paths = {synthesis._path(r['path']) for r in self._current} - old_paths
        if {synthesis._path(u.source_path) for u in units} != new_paths:
            raise ValueError('SUPPLEMENT_SYNTHESIS_SCOPE_INVALID')
        combined_units = deepcopy(self._units)
        next_id = max((u.doc_id for u in combined_units), default=-1) + 1
        for index, unit in enumerate(units):
            cloned = deepcopy(unit); cloned.doc_id = next_id + index
            combined_units.append(cloned)
        combined_cache = self._prior_cache()
        prior_read_pages = len(combined_cache)
        combined_cache.update({key: value for key, value in cache.items() if key in allowed
                               and synthesis._path(key[0]) in new_paths})
        combined = deepcopy(self._fields)
        combined_provenance = deepcopy(combined.get('_provenance') or {})
        combined_conflicts = (deepcopy(combined.get('_field_conflicts') or [])
                              + deepcopy(self._pending_conflicts) + deepcopy(conflicts))
        for key, value in fields.items():
            if key.startswith('_'):
                continue
            old = combined.get(key)
            if old in (None, '', [], {}) or key in synthesis.NARRATIVES:
                combined[key] = deepcopy(value)
            elif value not in (None, '', [], {}) and old != value:
                combined_conflicts.append({'field': key, 'values': [old, value], 'resolved': False})
        for key, refs in provenance.items():
            old = combined_provenance.get(key) or []
            combined_provenance[key] = (old if isinstance(old, list) else [old]) + deepcopy(refs if isinstance(refs, list) else [refs])
        for key, value in self._manual.items():
            if key.startswith('_'):
                continue
            combined[key] = deepcopy(value)
            refs = combined_provenance.setdefault(key, [])
            if isinstance(refs, dict): refs = combined_provenance[key] = [refs]
            refs.append({'method': 'human', 'value': deepcopy(value), 'inherited': True})
        combined['_provenance'] = combined_provenance
        combined['_field_conflicts'] = combined_conflicts
        status = synthesis.generate(client, combined, combined_provenance, combined_conflicts,
            combined_units, combined_cache, set(combined_cache), case_type=case_type,
            guard=guard, manual_fields=self._manual, source_manifest=self._current)
        self._result = {'fields': combined, 'status': status, 'units': combined_units}
        return {**status, 'scope': 'combined_read_sources_after_supplement',
                'prior_read_pages': prior_read_pages, 'new_read_pages': len(combined_cache) - prior_read_pages}

    def failed(self, status):
        self._failure = deepcopy(status)

    def apply(self, fields, units, manifest):
        """Adopt only after the task's literal/manual/classification merge."""
        result = self._result
        if result is None:
            fields['_form_synthesis_status'] = self._failure or {'status': 'supplement_review_pending',
                'fields': {key: 'needs_source_review' for key in synthesis.NARRATIVES if key not in self._manual}}
            return False
        prepared, status = result['fields'], deepcopy(result['status'])
        expected = {synthesis._path(r['path']): r['sha256'] for r in self._current}
        actual = {synthesis._path(r['path']): r['sha256'] for r in manifest}
        if (actual != expected or synthesis._snapshot(fields) != synthesis._snapshot(prepared)
                or synthesis.inventory(units) != synthesis.inventory(result['units'])
                or synthesis._source_hashes(units) != expected):
            fields['_form_synthesis_status'] = {'status': 'supplement_context_changed',
                'fields': {key: 'needs_source_review' for key in synthesis.NARRATIVES if key not in self._manual}}
            return False
        fields['_form_synthesis_status'] = {**status, 'scope': 'combined_read_sources_after_supplement'}
        if status['status'] not in ('generated', 'reused'):
            return False
        bundle = prepared[synthesis.KEY]
        candidate = {**fields, synthesis.KEY: deepcopy(bundle)}
        candidate_provenance = deepcopy(fields.get('_provenance') or {})
        accepted = {}
        for key in synthesis.NARRATIVES:
            if key in self._manual or status['fields'].get(key) not in ('generated', 'reused'):
                continue
            refs = prepared['_provenance'].get(key) or []
            refs = [refs] if isinstance(refs, dict) else refs
            owned = next((ref for ref in reversed(refs) if isinstance(ref, dict)
                          and ref.get('binding') == synthesis.BINDING and ref.get('bundle_digest') == synthesis.digest(bundle)), None)
            if owned is None:
                continue
            candidate[key] = prepared[key]
            history = candidate_provenance.get(key) or []
            candidate_provenance[key] = (history if isinstance(history, list) else [history]) + [deepcopy(owned)]
            accepted[key] = owned
        candidate['_provenance'] = candidate_provenance
        if not accepted or any(synthesis.current_support(ref, candidate) is None for ref in accepted.values()):
            fields['_form_synthesis_status'] = {'status': 'supplement_evidence_changed',
                'fields': {key: 'needs_source_review' for key in synthesis.NARRATIVES if key not in self._manual}}
            return False
        fields[synthesis.KEY] = candidate[synthesis.KEY]
        fields['_provenance'] = candidate_provenance
        for key in accepted: fields[key] = candidate[key]
        return True
