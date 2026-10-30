"""Compare source-bound model grouping with human reference boundaries.

No inference, source reads, manual projections, or publication decisions here.
Hashes bind recorded output; they are not proof of model accuracy or authority.
"""
from collections import Counter
import os

from agent_experience import ExperienceError
from agent_trace import TRACE_CURRENT, TRACE_RUNS, SCHEMA, validate_trace_fields


def fail():
    raise ExperienceError('EXPERIENCE_BOUNDARY_RESULT_INVALID')


def references(raw):
    keys = {'baseline_task_id', 'baseline_revision', 'candidate_task_id', 'candidate_revision',
            'expected_applicable', 'reference_reviewed', 'documents'}
    if type(raw) is not dict or set(raw) != keys:
        fail()
    for key in ('baseline_task_id', 'baseline_revision', 'candidate_task_id', 'candidate_revision'):
        if type(raw[key]) is not int or raw[key] < 1:
            fail()
    if (raw['baseline_task_id'] == raw['candidate_task_id'] or raw['reference_reviewed'] is not True
            or type(raw['expected_applicable']) is not bool
            or type(raw['documents']) is not list or not 1 <= len(raw['documents']) <= 128):
        fail()
    seen = set()
    for item in raw['documents']:
        if (type(item) is not dict or set(item) != {'file_id', 'ranges'}
                or type(item['file_id']) is not str or not 1 <= len(item['file_id']) <= 128
                or item['file_id'] in seen or type(item['ranges']) is not list
                or not 1 <= len(item['ranges']) <= 10000):
            fail()
        seen.add(item['file_id'])
        following = 1
        for span in item['ranges']:
            if (type(span) is not list or len(span) != 2 or any(type(n) is not int for n in span)
                    or span[0] != following or span[1] < span[0]):
                fail()
            following = span[1] + 1
    return raw


def _path(value):
    if type(value) is not str or not value:
        fail()
    return os.path.normcase(os.path.abspath(value))


def project(fields, manifest, experience_sha256):
    """Read original scoped model groups, never editable doc_spans/classifications."""
    try:
        validate_trace_fields(fields)
        runs = fields.get(TRACE_RUNS)
        if type(runs) is not list or len(runs) != 1 or runs[0]['run_id'] != fields[TRACE_CURRENT]:
            fail()  # Supplemental/legacy scopes need a separate evaluator.
        run = runs[0]
        body, scope = run['body'], run['body'].get('scope')
        if body['schema'] != SCHEMA or type(scope) is not dict:
            fail()
        payload = body['payload']
        if (payload.get('_request_budget_stop')
                or payload.get('_experience_policy', {}).get('snapshot_sha256') != experience_sha256):
            fail()
        sources = {_path(row['path']): row for row in manifest}
        if len(sources) != len(manifest) or len({r['file_id'] for r in manifest}) != len(manifest):
            fail()
        identities = {_path(key): value for key, value in scope['sources'].items()}
        if set(sources) != set(identities) or len(identities) != len(scope['sources']):
            fail()
        expected_pages = set()
        for path, row in sources.items():
            identity = identities[path]
            if (type(row['pages']) is not int or row['pages'] < 1
                    or identity['sha256'] != row['sha256'] or identity['page_count'] != row['pages']):
                fail()
            expected_pages.update((path, n) for n in range(1, row['pages'] + 1))
        pages = {key: (_path(row['source_path']), row['page']) for key, row in scope['pages'].items()}
        if (any(type(n) is not int for _, n in pages.values()) or set(pages.values()) != expected_pages
                or len(pages) != len(expected_pages)):
            fail()
        covered = []
        ranges = {row['file_id']: [] for row in manifest}
        for document in scope['documents'].values():
            keys = document['page_ids']
            if type(keys) is not list or not keys:
                fail()
            locations = [pages[key] for key in keys]
            path = locations[0][0]
            numbers = [n for _, n in locations]
            if (any(p != path for p, _ in locations)
                    or numbers != list(range(numbers[0], numbers[-1] + 1))):
                fail()
            covered.extend(keys)
            ranges[sources[path]['file_id']].append([numbers[0], numbers[-1]])
        if Counter(covered) != Counter(pages.keys()):
            fail()
        for values in ranges.values():
            values.sort()
        reviews = payload.get('_visual_boundary_review')
        if type(reviews) is not list or any(type(review) is not dict or not review.get('status') for review in reviews):
            fail()
        unresolved = sum(review['status'] != 'resolved' for review in reviews)
        return {'trace_sha256': run['run_id'], 'ranges': ranges, 'unresolved_reviews': unresolved}
    except (KeyError, TypeError, ValueError, AttributeError):
        fail()


def compare(reference, baseline, candidate, manifest):
    labels = {row['file_id']: row['ranges'] for row in references(reference)['documents']}
    counts = {row['file_id']: row['pages'] for row in manifest}
    if set(labels) != set(counts) or any(labels[key][-1][1] != counts[key] for key in labels):
        fail()
    results = []
    for key, expected in sorted(labels.items()):
        # A missing internal cut joins independent documents; an extra cut
        # fragments one document. Counts alone could hide swaps, so retain pages.
        cuts = {span[0] for span in expected[1:]}
        row = {'file_id': key, 'expected_ranges': expected}
        for name, observed in [('baseline', baseline), ('candidate', candidate)]:
            actual = {span[0] for span in observed['ranges'][key] if span[0] != 1}
            row[name] = {'missing_boundaries': sorted(cuts - actual),
                         'extra_boundaries': sorted(actual - cuts), 'matches': actual == cuts}
        results.append(row)
    before = all(row['baseline']['matches'] for row in results)
    after = all(row['candidate']['matches'] for row in results)
    return {'files': results, 'baseline_matches_reference': before,
            'candidate_matches_reference': after,
            'new_errors': any(set(row['candidate'][kind]) - set(row['baseline'][kind])
                             for row in results for kind in ('missing_boundaries', 'extra_boundaries')),
            'baseline_unresolved_reviews': baseline['unresolved_reviews'],
            'candidate_unresolved_reviews': candidate['unresolved_reviews'],
            'improved_to_reference': not before and after and candidate['unresolved_reviews'] == 0}
