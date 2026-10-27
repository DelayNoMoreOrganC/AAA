"""Serial executor for all Word COM (win32com) operations.

Word is a process-level singleton: only one instance may run at a time.
We route every Word-touching call through a single-worker ThreadPoolExecutor
that initializes pythoncom on its one thread. This serializes Word access
and keeps the asyncio event loop free.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial

_executor: ThreadPoolExecutor | None = None


def _ensure_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        # max_workers=1 guarantees strict serialization of Word COM calls.
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="word-com")
    return _executor


def _init_com() -> None:
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        # pythoncom only available on Windows with pywin32; ignore elsewhere.
        pass


async def run_word(func, /, *args, **kwargs):
    """Run a blocking Word/COM function on the serial executor.

    ``func`` is called as ``func(*args, **kwargs)`` on the dedicated Word
    thread. Returns the function's result. Use this for any code path that
    touches win32com (template filling, doc->docx/pdf conversion).
    """
    ex = _ensure_executor()
    ex.submit(_init_com).result()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(ex, partial(func, *args, **kwargs))


def shutdown_word() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None
