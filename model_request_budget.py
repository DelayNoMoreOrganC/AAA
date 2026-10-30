"""Task-wide durable dispatch counter; contains no prompts or credentials.

Reservations are conservative: a crash after reservation may consume a slot
without a provider call. Never decrement or infer refunds from an exception.
The caller supplies a validated task-private directory and frozen policy.
"""
from pathlib import Path
import json

from recognition_journal import (RecognitionJournalError, _atomic_write, _canonical,
                                 _hash, _io_path, _regular, _scope_lock)


class TaskRequestBudget:
    def __init__(self, directory, *, scope, limit, journal_directory):
        if limit is not None and (type(limit) is not int or not 0 <= limit <= 100000):
            raise RecognitionJournalError('CONFIG_INVALID')
        if not isinstance(scope, dict) or not scope:
            raise RecognitionJournalError('CONFIG_INVALID')
        self.directory = _io_path(directory)
        self.journal_directory = _io_path(journal_directory)
        self.identity = {'version':1,'scope_sha256':_hash(_canonical(scope,limit=128000,code='CONFIG_INVALID')),
                         'max_requests':limit}
        self._last = None

    def _read(self):
        path = self.directory/'budget.json'
        if path.is_symlink(): raise RecognitionJournalError('RECORD_INVALID')
        if not path.exists():
            # Do not silently recreate a deleted counter for an existing run.
            if (list(self.directory.glob('.*.tmp')) or
                    any(self.journal_directory.glob('*/r-*.json'))):
                raise RecognitionJournalError('RECORD_INVALID')
            return {**self.identity,'reserved_requests':0}
        if _regular(path) > 16384:
            raise RecognitionJournalError('RECORD_INVALID')
        record = json.loads(path.read_text(encoding='utf-8'))
        payload = record['payload']
        if (set(payload) != {*self.identity,'reserved_requests'} or
                any(type(payload.get(key)) is not type(value) or payload.get(key) != value for key,value in self.identity.items()) or
                type(payload['reserved_requests']) is not int or not 0 <= payload['reserved_requests'] <= 100000000 or
                record['sha256'] != _hash(_canonical(payload,limit=16384,code='RECORD_INVALID'))):
            raise RecognitionJournalError('RECORD_INVALID')
        return payload

    def reserve(self, *, preserve_requests=0):
        """Reserve before transport, shared across segments, scopes and restarts."""
        if type(preserve_requests) is not int or not 0 <= preserve_requests <= 100000:
            raise RecognitionJournalError('CONFIG_INVALID')
        try:
            if self.directory.is_symlink() or self.directory.exists() and not self.directory.is_dir():
                raise RecognitionJournalError('RECORD_INVALID')
            self.directory.mkdir(parents=True,exist_ok=True)
            with _scope_lock(self.directory/'.lock'):
                payload = self._read()
                limit = payload['max_requests']
                # Keep the scheduler branch stable after later writing consumed
                # the reserved slots. It may need to replay that completed
                # writer after restart; ordinary dispatch still enforces zero.
                if preserve_requests and limit is not None and limit - payload['reserved_requests'] <= preserve_requests:
                    self._last = payload
                    raise RecognitionJournalError('REQUEST_BUDGET_RESERVED')
                if limit is not None and payload['reserved_requests'] >= limit:
                    self._last = payload
                    raise RecognitionJournalError('REQUEST_BUDGET_EXHAUSTED')
                payload['reserved_requests'] += 1
                body = _canonical(payload,limit=16384,code='RECORD_INVALID')
                _atomic_write(self.directory/'budget.json',_canonical(
                    {'payload':payload,'sha256':_hash(body)},limit=16384,code='RECORD_INVALID'))
                self._last = payload
                return self.summary
        except RecognitionJournalError:
            raise
        except (OSError,ValueError,TypeError,KeyError):
            raise RecognitionJournalError('RECORD_INVALID') from None

    @property
    def summary(self):
        return dict(self._last) if self._last else None
