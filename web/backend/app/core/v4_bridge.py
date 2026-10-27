"""Bridge to V4 modules by injecting the V4 project root onto sys.path.

This lets the V6 Web layer import mineru_api, archive_pipeline,
pdf_doc_locator, etc.
WITHOUT copying or modifying any V4 source. The V4 .doc templates and
prompt files are also reachable through V4's own path resolution.
"""
from __future__ import annotations

import importlib
import sys
import threading

from ..config import V4_ROOT

_initialized = False
_lock = threading.Lock()


def init_v4_path() -> None:
    """Insert V4_ROOT at the front of sys.path once (thread-safe)."""
    global _initialized
    with _lock:
        if _initialized:
            return
        if V4_ROOT not in sys.path:
            sys.path.insert(0, V4_ROOT)
        _initialized = True


def load(name: str):
    """Import a V4 module by short name and return the module object."""
    init_v4_path()
    return importlib.import_module(name)


# Convenient lazy accessors. Importing this module does NOT trigger V4
# imports; callers pull them on demand to keep startup fast.
def mineru_api():
    return load("mineru_api")


def archive_pipeline():
    return load("archive_pipeline")


def pdf_doc_locator():
    return load("pdf_doc_locator")


def archive_catalog():
    return load("archive_catalog")


def document_segmenter():
    return load("document_segmenter")


def template_filler():
    return load("template_filler")
