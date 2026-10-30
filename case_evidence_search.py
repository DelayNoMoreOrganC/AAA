"""Bounded case-local lookup and deferred visual reading, never fact acceptance.

Searches only the current CasePages/decisions and already read text. Does not
open files, invoke OCR, contact a model or broaden the document fact scope.
"""
from __future__ import annotations
from dataclasses import dataclass
import unicodedata
import hashlib
from form_cell_contracts import SOURCE_PRIORITY, LITERAL_SOURCES


def compact(text):
    return ''.join(unicodedata.normalize('NFKC', text).split()).casefold()


@dataclass(frozen=True)
class EvidenceSearchPolicy:
    max_searches: int = 6
    max_results: int = 3
    max_followup_pages: int = 6
    max_followup_documents: int = 3

    def __post_init__(self):
        for value, ceiling in ((self.max_searches,24),(self.max_results,5),
                               (self.max_followup_pages,24),(self.max_followup_documents,8)):
            if type(value) is not int or not 0 <= value <= ceiling:
                raise ValueError('INVALID_EVIDENCE_POLICY')


class EvidenceSearchError(ValueError):
    pass


class CaseEvidenceSearch:
    def __init__(self, pages, documents, decisions, *, policy=None):
        self.pages = pages
        self.policy = policy or EvidenceSearchPolicy()
        self.rows = {r['page_id']: r for r in decisions}
        self.documents = {d['id']: d for d in documents}
        self.owners = {}
        for document in documents:
            for key in document['keys']:
                if key not in pages.pages or key not in self.rows or key in self.owners:
                    raise ValueError('INVALID_CASE_EVIDENCE_SCOPE')
                self.owners[key] = document['id']
        if set(self.owners) != set(pages.pages) or len(self.documents) != len(documents):
            raise ValueError('INVALID_CASE_EVIDENCE_SCOPE')
        self.queries, self.events, self.pending = set(), [], {}
        self.reserved_pages, self.reserved_documents = set(), set()
        self.scheduled_pages = set()
        self.attempted_requests = set()
        self.attempt_outcomes = {}

    def search(self, action, document_id):
        field, query, reason = (action.get(k) for k in ('field','query','reason'))
        if (document_id not in self.documents or type(field) is not str
                or field == '合同号' or field not in SOURCE_PRIORITY and field not in LITERAL_SOURCES
                or type(query) is not str or not 2 <= len(query.strip()) <= 120
                or reason not in ('cited_source','field_conflict','missing_basis')):
            raise EvidenceSearchError('INVALID_SEARCH_ARGUMENTS')
        needle = compact(query)
        if len(needle)<2:
            raise EvidenceSearchError('INVALID_SEARCH_ARGUMENTS')
        cache_revision = tuple((key,hashlib.sha256(str(self.pages.texts[self.pages.pages[key][0]][self.pages.pages[key][1]]).encode('utf-8')).hexdigest())
                               for key in sorted(self.pages.read_pages) if key in self.owners)
        signature = (field, needle, cache_revision)
        if signature in self.queries:
            raise EvidenceSearchError('REPEATED_SEARCH')
        if len(self.queries) >= self.policy.max_searches:
            raise EvidenceSearchError('SEARCH_BUDGET_EXHAUSTED')
        self.queries.add(signature)
        matches = []
        for key, row in self.rows.items():
            title = (row.get('observation') or {}).get('visible_title') or row.get('title','')
            title = title if type(title) is str else ''
            rank = 0
            if needle == compact(title): rank = 3
            elif needle in compact(title): rank = 2
            snippet = ''
            if key in self.pages.read_pages:
                path, number = self.pages.pages[key]
                cached = self.pages.texts[path][number]
                text = compact(cached) if isinstance(cached,str) else ''
                pos = text.find(needle)
                if pos >= 0:
                    rank = max(rank,1)
                    snippet = text[max(0,pos-60):pos+len(needle)+100]
            if not rank:continue
            owner = self.owners[key]
            matches.append({'page_id':key,'document_id':owner,'title_candidate':title[:120],
                'matched_in':'title_and_cached_text' if rank>1 and snippet else 'title' if rank>1 else 'cached_text',
                'untrusted_cached_excerpt':snippet,'rank':rank,'current_document':owner==document_id})
        matches.sort(key=lambda item:-item['rank'])  # Stable source order within a rank.
        selected = matches[:self.policy.max_results]
        for match in selected:
            match.pop('rank')
            if match['current_document']:
                match['reading_status'] = 'inspect_within_current_document'
            else:
                key = match['page_id']
                owner = match['document_id']
                if (key not in self.reserved_pages and len(self.reserved_pages)>=self.policy.max_followup_pages
                        or owner not in self.reserved_documents and len(self.reserved_documents)>=self.policy.max_followup_documents):
                    match['reading_status'] = 'source_read_budget_exhausted'
                    continue
                self.reserved_pages.add(key); self.reserved_documents.add(owner)
                request = {'from_document_id':document_id,'field':field,'reason':reason,
                           'page_id':key,'document_id':match['document_id']}
                bucket = self.pending.setdefault(key,[])
                if request not in bucket:bucket.append(request)
                match['reading_status'] = 'queued_for_source_document'
        event = {'document_id':document_id,'field':field,'reason':reason,
                 'matched_page_ids':[m['page_id'] for m in selected], 'result_count':len(selected),
                 'reading_statuses':{m['page_id']:m['reading_status'] for m in selected},
                 'truncated':len(matches)>len(selected)}
        self.events.append(event)  # No client names, query text or material excerpts in audit events.
        return {'matches':selected,'truncated':event['truncated'],
            'scope':'current_case_titles_and_already_read_text_only',
            'not_found_is_not_absence':True,'results_are_verified_facts':False,
            'instruction':'检索命中仅是候选。当前文书页可继续按范围查看；其他文书已排队补读，不能在当前record_fields中引用其他文书页。'}

    def requests_for(self, document_id):
        return [r for entries in self.pending.values() for r in entries if r['document_id']==document_id]

    @staticmethod
    def request_key(request):
        return (request['page_id'],request['field'],request['reason'],request['from_document_id'])

    def reading_scope(self, document_id):
        """Freeze the questions actually supplied to this document's reader.

        Later questions cannot be discharged merely because the reader happened
        to look at that page before they were supplied in its prompt.
        """
        if document_id not in self.documents:
            raise EvidenceSearchError('INVALID_READING_SCOPE')
        return frozenset(self.request_key(r) for r in self.requests_for(document_id))

    def mark_attempted(self, document_id, seen_keys, *, request_scope, completed=True):
        seen_keys = set(seen_keys)
        current = self.reading_scope(document_id)
        if (not isinstance(request_scope, frozenset) or not request_scope <= current
                or not seen_keys <= set(self.documents[document_id]['keys'])
                or type(completed) is not bool):
            raise EvidenceSearchError('INVALID_READING_SCOPE')
        for signature in request_scope:
            if signature[0] in seen_keys:
                self.attempted_requests.add(signature)
                # Completion means a valid extraction submission, not that a
                # fact was found/accepted. An exhausted pass is never success.
                previous = self.attempt_outcomes.get(signature)
                if previous != 'extraction_submitted':
                    self.attempt_outcomes[signature] = 'extraction_submitted' if completed else 'operation_limit'

    def schedule_followups(self, seen_pages):
        """One extra wave, cap pages/documents; no repeat of the same reading task.

        Merely seeing an image before a new field question arose does not prove
        the question was answered. Each newly requested purpose gets at most one
        source-document attempt, not an unlimited loop until a fact is accepted.
        """
        scheduled = {}
        for key, entries in self.pending.items():
            if key in self.scheduled_pages or all(self.request_key(r) in self.attempted_requests for r in entries):continue
            owner = self.owners[key]
            self.scheduled_pages.add(key)
            scheduled.setdefault(owner,[]).append(key)
        return scheduled

    def reading_jobs(self, ordered_documents, seen_pages):
        """Used by the workflow: retain original IDs and add exactly one wave."""
        by_id={document['id']:(unit,document) for unit,document in ordered_documents}
        for unit,document in ordered_documents:
            yield unit,document,None
        for document_id,keys in self.schedule_followups(seen_pages).items():
            unit,document=by_id[document_id]
            yield unit,document,keys

    def report(self, seen_pages):
        return {'policy':vars(self.policy),'searches':list(self.events),
            'followup_pages_reserved':len(self.reserved_pages),
            'requests':[dict(r,status='targeted_read_attempted_not_necessarily_verified' if self.request_key(r) in self.attempted_requests else 'pending_source_read',
                             attempt_outcome=self.attempt_outcomes.get(self.request_key(r), 'not_attempted'),
                             page_previously_seen=key in seen_pages)
                        for key, entries in self.pending.items() for r in entries]}
