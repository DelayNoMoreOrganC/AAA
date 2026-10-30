"""Task-private, content-addressed response chains; never executes actions.

The caller supplies a private task directory and complete semantic scope, and
must run its request guard before *every* complete(), including a replay.  A new
wrapper starts at the root of the chain. Changed messages create a preserved
branch. Only a trusted workflow's exhausted segment and a new explicit retry
token can select a new attempt; no attempt or model budget is added in a run.

Dispatch is reserved durably before transport. A crash or transport failure can
leave an uncertain reservation: restart may replay completed responses but must
not resend it without a new explicit server-owned resume token. This is not
exactly-once billing: that explicit retry may still incur another charge. Hashes detect damaged
records, not malicious rewriting of an entire private journal.  Directory ACLs,
retention, encryption, scope identity and administrative recovery are callers'
responsibilities.  Responses are sensitive task data even though prompts,
images, credentials and raw scope values are never persisted here.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import threading
import uuid


_ERRORS = {
    "CONFIG_INVALID": "识别续办记录配置无效，已停止请求，请检查任务配置。",
    "REQUEST_INVALID": "识别请求无法生成稳定校验摘要，已停止请求。",
    "RECORD_INVALID": "识别续办记录损坏或校验不符，已保留记录并停止请求，请人工检查。",
    "SEQUENCE_MISMATCH": "识别续办记录与当前请求顺序或内容不符，已停止请求，请显式建立新的识别范围。",
    "READ_FAILED": "无法读取识别续办记录，已停止请求，请检查任务存储。",
    "WRITE_FAILED": "识别响应未能安全写入续办记录，已停止处理，请检查任务存储。",
    "LOCKED": "本任务识别续办记录正在使用，请稍后重试。",
    "LIMIT_EXCEEDED": "识别续办记录超过安全大小或数量限制，已停止请求，请人工检查。",
    "REQUEST_UNCERTAIN": "上次模型请求结果未知；如使用云端，可能已产生费用。已停止自动重发，确认需要重新请求后请手动续跑；已有识别结果保留。",
    "REQUEST_BUDGET_EXHAUSTED": "本任务模型请求额度已用尽，已停止新增调用，已有识别记录保留。请联系管理员核对任务额度；重复点击不会增加额度。",
    "REQUEST_BUDGET_RESERVED": "本次请求未发送，剩余额度保留给后续处理；当前未完成部分仍须保留待核状态。",
}
_COUNTERS = (
    "model_requests", "model_failed_requests", "prompt_tokens",
    "completion_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens",
)
_NUMERIC = _COUNTERS + ("model_seconds",)
_ZERO = "0" * 64
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_RECORD = re.compile(r"([rs])-([0-9a-f]{64})\.json\Z")
_TEMPORARY = re.compile(r"\.[rs]-[0-9a-f]{64}-[0-9a-f]{32}\.tmp\Z")
MAX_SCOPE_BYTES = 128_000
MAX_MESSAGES_BYTES = 96_000_000


class RecognitionJournalError(RuntimeError):
    """Only fixed codes and fixed Chinese text cross this boundary."""

    def __init__(self, code="RECORD_INVALID"):
        self.code = code if type(code) is str and code in _ERRORS else "RECORD_INVALID"
        super().__init__(_ERRORS[self.code])


def _canonical(value, *, limit, code):
    """Reject coercions (non-string keys, NaN, arbitrary objects) before hashing."""
    remaining = 200_000

    def visit(item, depth=0):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 64:
            raise RecognitionJournalError(code)
        kind = type(item)
        if item is None or kind in (str, bool, int):
            return
        if kind is float and math.isfinite(item):
            return
        if kind is list:
            for child in item:
                visit(child, depth + 1)
            return
        if kind is dict and all(type(key) is str for key in item):
            for child in item.values():
                visit(child, depth + 1)
            return
        raise RecognitionJournalError(code)

    try:
        visit(value)
        chunks, length = [], 0
        for part in json.JSONEncoder(ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).iterencode(value):
            data = part.encode("utf-8")
            length += len(data)
            if length > limit:
                raise RecognitionJournalError("LIMIT_EXCEEDED")
            chunks.append(data)
        return b"".join(chunks)
    except RecognitionJournalError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        raise RecognitionJournalError(code) from None


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _safe_metrics(client):
    raw = getattr(client, "metrics", None)
    if type(raw) is not dict:
        return {}
    result = {}
    for key in _NUMERIC:
        value = raw.get(key)
        valid = (type(value) is int if key in _COUNTERS else type(value) in (int, float))
        if valid and 0 <= value <= 10**15 and math.isfinite(value):
            result[key] = value
    return result


def _delta(before, after):
    return {key: after[key] - before.get(key, 0) for key in _NUMERIC
            if key in after and after[key] >= before.get(key, 0)}


def _regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise RecognitionJournalError("RECORD_INVALID")
    return info.st_size


def _io_path(path):
    """Windows long paths, including UNC, without changing OS-wide settings."""
    path = Path(path).absolute()
    if os.name != "nt":
        return path
    value = str(path)
    if value.startswith("\\\\?\\"):
        return path
    if value.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + value[2:])
    return Path("\\\\?\\" + value)


@contextmanager
def _scope_lock(path):
    """Per-complete OS lock. A leftover lock file is not a stale held lock."""
    handle, acquired = None, False
    try:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise RecognitionJournalError("RECORD_INVALID")
        handle = path.open("a+b")
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError:
            raise RecognitionJournalError("LOCKED") from None
    except RecognitionJournalError:
        if handle is not None:
            handle.close()
        raise
    except OSError:
        if handle is not None:
            handle.close()
        raise RecognitionJournalError("READ_FAILED") from None
    try:
        yield
    finally:
        if handle is not None:
            if acquired:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                finally:
                    handle.close()
            else:
                handle.close()


def _atomic_write(path, body):
    temporary = path.with_name("." + path.stem + "-" + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        # Windows has no portable directory-fsync interface. The file is fsynced
        # before atomic replacement; this is not a full power-loss guarantee.
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except OSError:
        # Keep unfinished bytes. A durable dispatch reservation prevents a new
        # wrapper from silently resending an unknown response.
        raise RecognitionJournalError("WRITE_FAILED") from None


class RecognitionJournal:
    def __init__(self, directory, *, max_records=10_000,
                 max_record_bytes=2_000_000, max_total_bytes=256_000_000):
        try:
            self.directory = _io_path(directory)
        except (TypeError, ValueError):
            raise RecognitionJournalError("CONFIG_INVALID") from None
        values = (max_records, max_record_bytes, max_total_bytes)
        if any(type(value) is not int or value <= 0 for value in values) or max_records > 99_999_999:
            raise RecognitionJournalError("CONFIG_INVALID")
        self.max_records, self.max_record_bytes, self.max_total_bytes = values

    def wrap(self, client, *, scope, retry_token=None, request_budget=None):
        if type(scope) is not dict or not scope or not callable(getattr(client, "complete", None)):
            raise RecognitionJournalError("CONFIG_INVALID")
        if retry_token is not None and (type(retry_token) is not str
                                       or not re.fullmatch(r"[0-9a-f]{32}", retry_token)):
            raise RecognitionJournalError("CONFIG_INVALID")
        scope_sha256 = _hash(_canonical(scope, limit=MAX_SCOPE_BYTES, code="CONFIG_INVALID"))
        return JournalClient(client, self, scope_sha256, retry_token, request_budget)


def _digest(value):
    return _hash(_canonical(value, limit=MAX_SCOPE_BYTES, code="CONFIG_INVALID"))


def _response_identity(scope, previous, messages):
    return {"version": 2, "kind": "response", "scope_sha256": scope,
            "previous_sha256": previous, "messages_sha256": messages}


def _segment_identity(scope, previous, identity):
    return {"version": 2, "kind": "segment", "scope_sha256": scope,
            "entry_sha256": previous, "identity_sha256": identity}


def _attempt_seed(scope, segment, generation):
    return _digest({"scope_sha256": scope, "segment_key": segment, "generation": generation})


class JournalClient:
    def __init__(self, client, journal, scope_sha256, retry_token=None, request_budget=None):
        self._client, self._journal = client, journal
        self.scope_sha256 = scope_sha256
        self._directory = journal.directory / scope_sha256
        self._previous = _ZERO
        self._retry_hash = _hash(retry_token.encode("ascii")) if retry_token else None
        self._active = None
        self._begun = set()
        self._reused = {"reused_" + key: 0 for key in _NUMERIC}
        self._thread_lock = threading.Lock()
        self._blocked = None
        self._uncommitted = 0
        self._uncertain_requests = 0
        self._dispatch_reservations = 0
        if request_budget is not None:
            from model_request_budget import TaskRequestBudget
            if type(request_budget) is not TaskRequestBudget:
                raise RecognitionJournalError('CONFIG_INVALID')
        self._request_budget = request_budget

    @property
    def metrics(self):
        result = _safe_metrics(self._client)
        raw = getattr(self._client, "metrics", {})
        model = raw.get("returned_model") if type(raw) is dict else None
        if type(model) is str and re.fullmatch(r"(?:deepseek-|glm-)[A-Za-z0-9_.:-]{1,55}", model):
            result["returned_model"] = model
        elif type(raw) is dict and raw.get("returned_model") == "":
            result["returned_model"] = ""
        if self._request_budget is not None and self._request_budget.summary is not None:
            result['task_request_budget'] = self._request_budget.summary
        return {**result, **self._reused, "uncommitted_records_present": self._uncommitted,
                "uncertain_requests_present":self._uncertain_requests,
                "dispatch_reservations":self._dispatch_reservations}

    @contextmanager
    def _locked(self):
        if self._blocked:
            raise RecognitionJournalError(self._blocked)
        if not self._thread_lock.acquire(blocking=False):
            raise RecognitionJournalError("LOCKED")
        try:
            try:
                for directory in (self._journal.directory, self._directory):
                    if directory.is_symlink() or (hasattr(directory, "is_junction") and directory.is_junction()):
                        raise RecognitionJournalError("CONFIG_INVALID")
                    directory.mkdir(parents=True, exist_ok=True)
            except OSError:
                raise RecognitionJournalError("WRITE_FAILED") from None
            with _scope_lock(self._directory / ".lock"):
                yield
        finally:
            self._thread_lock.release()

    def _read(self, path):
        try:
            with path.open("rb") as handle:
                raw = handle.read(self._journal.max_record_bytes + 1)
            if len(raw) > self._journal.max_record_bytes:
                raise RecognitionJournalError("LIMIT_EXCEEDED")
            def pairs(items):
                result = {}
                for key, value in items:
                    if key in result:
                        raise ValueError()
                    result[key] = value
                return result
            envelope = json.loads(raw, object_pairs_hook=pairs)
            if type(envelope) is not dict or set(envelope) != {"payload", "sha256"}:
                raise ValueError()
            payload, digest = envelope["payload"], envelope["sha256"]
            if type(digest) is not str or not _HEX.fullmatch(digest):
                raise ValueError()
            if digest != _hash(_canonical(payload, limit=self._journal.max_record_bytes, code="RECORD_INVALID")):
                raise ValueError()
            if (type(payload) is not dict or type(payload.get("version")) is not int
                    or payload["version"] != 2 or payload.get("scope_sha256") != self.scope_sha256):
                raise ValueError()
            match = _RECORD.fullmatch(path.name)
            if match is None:
                raise ValueError()
            prefix, key = match.groups()
            if prefix == "r":
                expected = _response_identity(self.scope_sha256, payload.get("previous_sha256"),
                                              payload.get("messages_sha256"))
                mandatory = set(expected) | {"request_key", "outcome", "usage"}
                if set(payload) - mandatory - {"dispatch_tokens"} or not mandatory <= set(payload):
                    raise ValueError()
                if any(type(payload[name]) is not str or not _HEX.fullmatch(payload[name])
                       for name in ("previous_sha256", "messages_sha256", "request_key")):
                    raise ValueError()
                if payload["kind"] != "response" or payload["request_key"] != key or _digest(expected) != key:
                    raise ValueError()
                outcome, usage = payload["outcome"], payload["usage"]
                if type(outcome) is not dict or type(usage) is not dict or set(usage) - set(_NUMERIC):
                    raise ValueError()
                tokens = payload.get('dispatch_tokens')
                if tokens is not None and (type(tokens) is not list or not 1 <= len(tokens) <= 128
                        or any(type(t) is not str or not _HEX.fullmatch(t) for t in tokens)
                        or len(set(tokens)) != len(tokens)):
                    raise ValueError()
                if outcome.get("kind") == "action":
                    if set(outcome) != {"kind", "action"} or type(outcome["action"]) is not dict:
                        raise ValueError()
                elif outcome == {'kind':'in_flight'}:
                    if not tokens or usage:
                        raise ValueError()
                elif outcome != {"kind": "format_error", "code": "INVALID_RESPONSE"}:
                    raise ValueError()
                if _safe_metrics(type("Usage", (), {"metrics": usage})()) != usage:
                    raise ValueError()
            else:
                expected = _segment_identity(self.scope_sha256, payload.get("entry_sha256"),
                                             payload.get("identity_sha256"))
                if set(payload) != set(expected) | {"segment_key", "attempts", "tokens"}:
                    raise ValueError()
                if any(type(payload[name]) is not str or not _HEX.fullmatch(payload[name])
                       for name in ("entry_sha256", "identity_sha256", "segment_key")):
                    raise ValueError()
                if payload["kind"] != "segment" or payload["segment_key"] != key or _digest(expected) != key:
                    raise ValueError()
                attempts, tokens = payload["attempts"], payload["tokens"]
                if type(attempts) is not list or not attempts or type(tokens) is not list:
                    raise ValueError()
                for index, attempt in enumerate(attempts):
                    if (type(attempt) is not dict or set(attempt) != {"generation", "status", "seed_sha256", "last_sha256"}
                            or type(attempt["generation"]) is not int or attempt["generation"] != index
                            or attempt["status"] not in ("in_progress", "completed", "operation_limit")
                            or attempt["seed_sha256"] != _attempt_seed(self.scope_sha256, key, index)
                            or type(attempt["last_sha256"]) is not str or not _HEX.fullmatch(attempt["last_sha256"])):
                        raise ValueError()
                seen = set()
                for token in tokens:
                    if (type(token) is not dict or set(token) != {"token_sha256", "generation"}
                            or type(token["token_sha256"]) is not str or not _HEX.fullmatch(token["token_sha256"])
                            or token["token_sha256"] in seen or type(token["generation"]) is not int
                            or not 0 <= token["generation"] < len(attempts)):
                        raise ValueError()
                    seen.add(token["token_sha256"])
            return payload, digest
        except RecognitionJournalError:
            raise
        except OSError:
            raise RecognitionJournalError("READ_FAILED") from None
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            raise RecognitionJournalError("RECORD_INVALID") from None

    def _files(self):
        """Validate all committed branches before any provider call.

        A missing ancestor or a corrupt sibling is never silently treated as a
        fresh cache miss. Temporary files are counted but never interpreted.
        """
        files, sizes, total, uncommitted = {}, {}, 0, 0
        try:
            for item in self._directory.iterdir():
                if item.name == ".lock":
                    continue
                temporary = bool(_TEMPORARY.fullmatch(item.name))
                if not temporary and not _RECORD.fullmatch(item.name):
                    raise RecognitionJournalError("RECORD_INVALID")
                size = _regular(item)
                if size > self._journal.max_record_bytes:
                    raise RecognitionJournalError("LIMIT_EXCEEDED")
                total += size
                if temporary:
                    uncommitted += 1
                else:
                    files[item.name] = self._read(item)
                    sizes[item.name] = size
        except OSError:
            raise RecognitionJournalError("READ_FAILED") from None
        self._uncommitted = uncommitted
        self._uncertain_requests = sum(p.get('outcome') == {'kind':'in_flight'} for p,_ in files.values())
        # Reservations may include a crash before actual network dispatch, and
        # cannot be presented as completed requests, tokens or charges.
        self._dispatch_reservations = sum(len(p.get('dispatch_tokens',[])) for p,_ in files.values())
        if len(files) + uncommitted > self._journal.max_records or total > self._journal.max_total_bytes:
            raise RecognitionJournalError("LIMIT_EXCEEDED")
        # Build the full immutable response graph and segment-seed edges, then
        # prove every node has a path to the root (including unvisited branches).
        edges = {}
        for payload, digest in files.values():
            if payload["kind"] == "response":
                edges[digest] = payload["previous_sha256"]
            else:
                for attempt in payload["attempts"]:
                    edges[attempt["seed_sha256"]] = payload["entry_sha256"]
        rooted = {_ZERO}
        for node in edges:
            trail, seen = [], set()
            cursor = node
            while cursor not in rooted:
                if cursor in seen or cursor not in edges:
                    raise RecognitionJournalError("RECORD_INVALID")
                seen.add(cursor)
                trail.append(cursor)
                cursor = edges[cursor]
            rooted.update(trail)
        for payload, _ in files.values():
            if payload["kind"] == "segment":
                for attempt in payload["attempts"]:
                    cursor, seed = attempt["last_sha256"], attempt["seed_sha256"]
                    while cursor != seed:
                        if cursor not in edges or cursor == _ZERO:
                            raise RecognitionJournalError("RECORD_INVALID")
                        cursor = edges[cursor]
        if self._previous not in rooted:
            raise RecognitionJournalError("RECORD_INVALID")
        return files, sizes, total

    def _write(self, name, payload, files, sizes, total):
        try:
            if (name not in files and len(files) + self._uncommitted >= self._journal.max_records):
                raise RecognitionJournalError("LIMIT_EXCEEDED")
            body = _canonical(payload, limit=self._journal.max_record_bytes, code="RECORD_INVALID")
            digest = _hash(body)
            record = _canonical({"payload": payload, "sha256": digest},
                                limit=self._journal.max_record_bytes, code="RECORD_INVALID")
            # Count both old bytes and new temporary bytes at peak write time.
            if total + len(record) > self._journal.max_total_bytes:
                raise RecognitionJournalError("LIMIT_EXCEEDED")
            _atomic_write(self._directory / name, record)
            return digest
        except RecognitionJournalError as error:
            self._blocked = error.code
            raise

    def begin_segment(self, identity):
        """Trusted workflow boundary, not a model action or request budget."""
        if type(identity) is not dict or not identity:
            raise RecognitionJournalError("CONFIG_INVALID")
        identity_hash = _digest(identity)
        if self._active is not None or identity_hash in self._begun:
            raise RecognitionJournalError("CONFIG_INVALID")
        with self._locked():
            files, sizes, total = self._files()
            expected = _segment_identity(self.scope_sha256, self._previous, identity_hash)
            key = _digest(expected)
            name = "s-" + key + ".json"
            uncertain = any(p.get('outcome') == {'kind':'in_flight'} for p,_ in files.values())
            if name in files:
                payload = files[name][0]
            else:
                seed = _attempt_seed(self.scope_sha256, key, 0)
                payload = {**expected, "segment_key": key, "attempts": [
                    {"generation": 0, "status": "in_progress", "seed_sha256": seed, "last_sha256": seed}],
                    "tokens": []}
            attempts = payload["attempts"]
            generation = len(attempts) - 1
            changed = name not in files
            receipt = next((item for item in payload["tokens"]
                            if item["token_sha256"] == self._retry_hash), None)
            if receipt is not None:
                # Even a token first seen during a crash recovery is consumed.
                # Reusing it after that attempt fails must not add another budget.
                generation = receipt["generation"]
            elif self._retry_hash is not None:
                if attempts[-1]["status"] == "operation_limit" and not uncertain:
                    generation = len(attempts)
                    seed = _attempt_seed(self.scope_sha256, key, generation)
                    attempts.append({"generation": generation, "status": "in_progress",
                                     "seed_sha256": seed, "last_sha256": seed})
                payload["tokens"].append({"token_sha256": self._retry_hash, "generation": generation})
                changed = True
            if changed:
                self._write(name, payload, files, sizes, total)
            self._previous = attempts[generation]["seed_sha256"]
            self._active = (key, generation)
            self._begun.add(identity_hash)

    def finish_segment(self, status):
        """Seal local validation success or the unchanged workflow step limit."""
        if type(status) is not str or status not in ("completed", "operation_limit") or self._active is None:
            raise RecognitionJournalError("CONFIG_INVALID")
        with self._locked():
            files, sizes, total = self._files()
            key, generation = self._active
            name = "s-" + key + ".json"
            if name not in files or generation >= len(files[name][0]["attempts"]):
                raise RecognitionJournalError("RECORD_INVALID")
            payload = files[name][0]
            attempt = payload["attempts"][generation]
            if attempt["status"] != status or attempt["last_sha256"] != self._previous:
                attempt.update(status=status, last_sha256=self._previous)
                self._write(name, payload, files, sizes, total)
            self._active = None

    def complete(self, messages):
        return self._complete(messages, preserve_requests=0)

    def complete_preserving(self, messages, *, preserve_requests):
        """Trusted scheduler's floor, not a model argument or extra allowance.

        Replay precedes the quota check. Reconstructing a run must consume its
        cached responses even when the remaining live allowance is smaller.
        Fewer than four total calls cannot fund classification, extraction and
        two writing steps, so those deliberately small jobs keep plain counting.
        """
        if type(preserve_requests) is not int or not 0 <= preserve_requests <= 100000:
            raise RecognitionJournalError('CONFIG_INVALID')
        limit = self._request_budget.identity['max_requests'] if self._request_budget is not None else None
        floor = preserve_requests if limit is not None and limit >= 4 else 0
        return self._complete(messages, preserve_requests=floor)

    def _complete(self, messages, *, preserve_requests):
        if type(messages) is not list:
            raise RecognitionJournalError("REQUEST_INVALID")
        message_hash = _hash(_canonical(messages, limit=MAX_MESSAGES_BYTES, code="REQUEST_INVALID"))
        with self._locked():
            files, sizes, total = self._files()
            expected = _response_identity(self.scope_sha256, self._previous, message_hash)
            key = _digest(expected)
            name = "r-" + key + ".json"
            pending = {n:p for n,(p,_) in files.items()
                       if p.get('outcome') == {'kind':'in_flight'}}
            dispatch_tokens = []
            if name in files and name not in pending:
                payload, digest = files[name]
                self._previous = digest
                for metric, value in payload["usage"].items():
                    self._reused["reused_" + metric] += value
                if payload["outcome"]["kind"] == "format_error":
                    from deepseek_vision_client import DeepSeekVisionError
                    raise DeepSeekVisionError("INVALID_RESPONSE") from None
                return payload["outcome"]["action"]
            if pending:
                # A changed prompt/branch cannot bypass an uncertain call.
                # Only the exact pending request may consume a fresh explicit
                # resume capability. Reusing that token is not another grant.
                if set(pending) != {name}:
                    raise RecognitionJournalError('REQUEST_UNCERTAIN')
                dispatch_tokens = list(pending[name]['dispatch_tokens'])
                if self._retry_hash is None or self._retry_hash in dispatch_tokens:
                    raise RecognitionJournalError('REQUEST_UNCERTAIN')
            elif self._uncommitted and self._retry_hash is None:
                # Legacy interrupted writes may predate dispatch reservations.
                # Do not treat their absent committed response as a cache miss
                # authorizing another paid request after automatic recovery.
                raise RecognitionJournalError('REQUEST_UNCERTAIN')
            if ((name not in files and len(files) + self._uncommitted >= self._journal.max_records)
                    or total >= self._journal.max_total_bytes or len(dispatch_tokens) >= 128):
                raise RecognitionJournalError("LIMIT_EXCEEDED")
            if self._request_budget is not None:
                self._request_budget.reserve(preserve_requests=preserve_requests)
            dispatch_tokens.append(self._retry_hash or _ZERO)
            reservation = {**expected,'request_key':key,'outcome':{'kind':'in_flight'},
                           'usage':{},'dispatch_tokens':dispatch_tokens}
            reserved_digest = self._write(name,reservation,files,sizes,total)
            # The lock spans reservation, transport and commit. Update the local
            # inventory so the final write enforces actual peak disk usage.
            try:
                reserved_size = _regular(self._directory/name)
            except OSError:
                raise RecognitionJournalError('WRITE_FAILED') from None
            total += reserved_size - sizes.get(name,0)
            sizes[name] = reserved_size
            files[name] = (reservation,reserved_digest)
            self._uncertain_requests = 1
            self._dispatch_reservations += 1
            before = _safe_metrics(self._client)
            caught = None
            try:
                action = self._client.complete(messages)
            except Exception as error:
                from deepseek_vision_client import DeepSeekVisionError
                if not isinstance(error, DeepSeekVisionError) or error.code != "INVALID_RESPONSE":
                    if isinstance(error,DeepSeekVisionError) and error.code in (
                            'KEY_MISSING','KEY_INVALID','AUTH_FAILED','QUOTA_EXHAUSTED','RATE_LIMITED','REQUEST_TOO_LARGE'):
                        raise
                    raise RecognitionJournalError('REQUEST_UNCERTAIN') from None
                caught = error
                outcome = {"kind": "format_error", "code": "INVALID_RESPONSE"}
            else:
                if type(action) is not dict:
                    self._blocked = "RECORD_INVALID"
                    raise RecognitionJournalError("RECORD_INVALID")
                # Workflow embeds returned actions into JSON message strings.
                # Give fresh and replay paths the same recursively ordered
                # representation before any local tool sees it. Otherwise a
                # disk replay can change those strings without changing facts,
                # spuriously opening a new request branch. Do not mutate the
                # transport's object; retain every JSON value and array order.
                try:
                    action = json.loads(_canonical(action, limit=self._journal.max_record_bytes,
                                                   code="RECORD_INVALID"))
                except RecognitionJournalError as error:
                    self._blocked = error.code
                    raise
                outcome = {"kind": "action", "action": action}
            payload = {**expected, "request_key": key, "outcome": outcome,
                       "usage": _delta(before, _safe_metrics(self._client)),
                       "dispatch_tokens":dispatch_tokens}
            self._previous = self._write(name, payload, files, sizes, total)
            self._uncertain_requests = 0
            if caught is not None:
                raise caught
            return action


def bind_client(client, *, directory, scope, retry_token=None, request_budget=None):
    """Bind without changing transport; retry tokens are server-owned capabilities."""
    return RecognitionJournal(directory).wrap(client, scope=scope, retry_token=retry_token, request_budget=request_budget)
