"""Task-private local readings, independent of successful narrative generation.

Only a server-owned checkpoint constructs this capability. Text is untrusted
source material, never an accepted fact. No network, OCR, shared index or public
endpoint lives here. Deleting a task/case directory deletes its readings too.
"""
from copy import deepcopy
import hashlib
from importlib import metadata
import inspect
import json
import os
from pathlib import Path
import stat
import tempfile

VERSION = 'page-reading-v1'
MAX_RECORD_BYTES = 2_000_000


class PageReadingError(RuntimeError):
    def __init__(self):
        super().__init__('本地阅读记录校验失败，已停止复用；原材料未更改。')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def path_key(path):
    return digest(os.path.normcase(os.path.abspath(path)))


def reader_identity():
    """Fingerprint actual local reader code, package versions and bundled weights."""
    from local_ocr import bundled_model_paths
    from visual_archive_agent import CasePages
    root = Path(__file__).resolve().parent
    files = [root/name for name in ('local_ocr.py', 'visual_ocr_orientation.py', 'visual_page_view.py', 'ocr_review.py', 'page_reading_store.py')]
    files += [Path(p) for p in bundled_model_paths().values()]
    hashes = {}
    for path in files:
        h = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024*1024), b''): h.update(chunk)
        hashes[path.name] = h.hexdigest()
    return digest({'files': hashes, 'read': inspect.getsource(CasePages.read),
        'packages': {name: metadata.version(name) for name in ('PyMuPDF', 'rapidocr-onnxruntime', 'onnxruntime')}})


class PageReadingStore:
    def __init__(self, directory, root, scope, sources, reader, *, readonly=False):
        self.directory, self.root = Path(directory).absolute(), Path(root).absolute()
        self.scope = deepcopy(scope)
        self.sources = {row['path_sha256']: deepcopy(row) for row in sources}
        self.reader, self.readonly = reader, readonly
        if len(self.sources) != len(sources) or not isinstance(reader, str) or len(reader) != 64:
            raise PageReadingError()
        self._directory_check()

    def __deepcopy__(self, memo): return self

    def _directory_check(self):
        try:
            relative = self.directory.relative_to(self.root)
            current = self.root
            for part in (None, *relative.parts):
                if part is not None: current /= part
                try: info = current.lstat()
                except FileNotFoundError: continue
                if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                        or getattr(info, 'st_file_attributes', 0) & 1024):
                    raise PageReadingError()
        except (ValueError, OSError): raise PageReadingError() from None

    def _key(self, source, page, rotation):
        selected = self.sources.get(path_key(source['source_path']))
        if (not selected or selected['sha256'] != source['sha256']
                or selected['pages'] != source['page_count'] or type(page) is not int
                or not 1 <= page <= selected['pages'] or type(rotation) is not int
                or rotation not in (0, 90, 180, 270)):
            raise PageReadingError()
        return {'schema': VERSION, 'reader': self.reader, 'path_sha256': path_key(source['source_path']),
                'source_sha256': source['sha256'], 'page': page, 'rotation': rotation}

    def _load(self, key):
        self._directory_check()
        target = self.directory / (digest(key)+'.json')
        try:
            info = target.lstat()
        except FileNotFoundError: return None
        if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or getattr(info, 'st_file_attributes', 0) & 1024 or info.st_size > MAX_RECORD_BYTES):
            raise PageReadingError()
        try:
            envelope = json.loads(target.read_text(encoding='utf-8'))
            body = envelope['body']
            if (envelope['sha256'] != digest(body) or body['key'] != key or body['scope'] != self.scope
                    or type(body['eligible']) is not bool or type(body['text']) is not str
                    or not isinstance(body['blocks'], list) or not isinstance(body['view'], dict)):
                raise PageReadingError()
            return body
        except (OSError, ValueError, TypeError, KeyError): raise PageReadingError() from None

    def _write(self, body):
        if self.readonly: raise PageReadingError()
        self._directory_check()
        data = json.dumps({'body': body, 'sha256': digest(body)}, ensure_ascii=False, allow_nan=False)
        if len(data.encode('utf-8')) > MAX_RECORD_BYTES: raise PageReadingError()
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory/(digest(body['key'])+'.json')
        fd, temporary = tempfile.mkstemp(prefix='.reading-', suffix='.tmp', dir=self.directory)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary): os.remove(temporary)

    def read(self, source, page, rotation):
        body = self._load(self._key(source, page, rotation))
        return deepcopy(body) if body is not None else None

    def save(self, source, page, rotation, *, text, blocks, view):
        key = self._key(source, page, rotation)
        old = self._load(key)
        body = {'key': key, 'scope': self.scope, 'eligible': False,
                'text': text, 'blocks': deepcopy(blocks), 'view': deepcopy(view)}
        if old is not None:
            if any(old[name] != body[name] for name in ('text', 'blocks', 'view')):
                raise PageReadingError()
            return
        self._write(body)

    def mark_eligible(self, source, page, rotation):
        body = self._load(self._key(source, page, rotation))
        if body is not None and not body['eligible']:
            body['eligible'] = True
            self._write(body)

    def _page_records(self, units):
        """Return only actually read full pages used in the prior writing pool.

        Rehash originals, restrict to current old units, skip multiple eligible
        orientations instead of choosing one. No fact/summary is restored here.
        """
        from agent_trace import source_identity
        by_path = {}
        for unit in units:
            by_path.setdefault(unit.source_path, set()).update(range(unit.start_page+1, unit.end_page+2))
        for path, numbers in by_path.items():
            selected = self.sources.get(path_key(path))
            if selected is None: raise PageReadingError()
            source = source_identity(path, selected['pages'])
            for page in sorted(numbers):
                rows = [(rotation, self.read(source, page, rotation)) for rotation in (0,90,180,270)]
                rows = [(rotation, row) for rotation, row in rows if row is not None and row['eligible']]
                yield path, source, page, rows

    def cache_result(self, units):
        cache, ambiguous = {}, set()
        for path, source, page, rows in self._page_records(units):
            if len(rows) == 1: cache[path, page] = rows[0][1]['text']
            elif len(rows) > 1: ambiguous.add((path, page))
        return cache, ambiguous

    def prior_cache(self, units):
        return self.cache_result(units)[0]

    def inherit(self, previous, units):
        if (type(previous) is not PageReadingStore or not previous.readonly or self.readonly
                or any(self.scope[key] != previous.scope[key] for key in ('org_id', 'case_id'))
                or self.reader != previous.reader):
            raise PageReadingError()
        for path, source, page, rows in previous._page_records(units):
            # Preserve competing reads as well; dropping them would let a later
            # task accidentally restore an older, ambiguous narrative excerpt.
            for rotation, row in rows:
                self.save(source, page, rotation, text=row['text'], blocks=row['blocks'], view=row['view'])
                self.mark_eligible(source, page, rotation)
