"""In-process async task manager with progress tracking and WS broadcast."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from dataclasses import dataclass, field
from .safe_errors import ErrorCode, public_error, log_failure

logger = logging.getLogger("v6.task")


# Core callbacks are untrusted free text: some legacy callers embed exceptions
# or filenames. Admit only complete fixed events and bounded integer counters.
_FIXED_LOGS = frozenset({
    "从已保存分析检查点恢复，无需重复识别材料",
    "复用未变化材料的分析快照；保留人工核对内容",
    "咨询代书补件需要重新核对全卷业务日期顺序；保留已人工核对字段",
    "归档助理：工具结果校验未通过，正在重试",
    "视觉归档助理：开始查看已授权的材料页面",
    "归档助理：已核对全部页面，未发现可采纳的目标字段；保留来源材料供核对",
    "[1/4] WF1 统一 OCR 摄入...",
    "[2/4] WF2+3 文书切分与映射...",
    "[3/4] WF4 字段提取与系统表...",
    "[4/4] 缺失项核对...",
    "[PREVIEW] 当前为跨平台预览模式，跳过 DOCX 模板生成",
    "[卷内目录] 使用本地 PDF 目录，不调用 Word",
    "[FAIL] 源 PDF 页守恒未满足，归档标记为失败",
    "归档失败",
})
_N = r"[0-9]{1,9}"
_SECONDS = r"[0-9]{1,9}\.[0-9]{3}"
_COUNTER_LOGS = tuple(re.compile(pattern) for pattern in (
    rf"视觉归档助理：已查看 {_N} / {_N} 页",
    rf"视觉分类：已核对 {_N} / {_N} 页",
    rf"文书提取：已处理 {_N} / {_N} 份文书",
    rf"\[性能\] (?:analysis|source_ingest|field_agent): {_SECONDS}s; status=(?:completed|failed)",
    rf"归档助理本次计时：model_requests={_N} model_failed_requests={_N} model_seconds={_SECONDS} max_request_seconds={_SECONDS} agent_seconds={_SECONDS}",
    rf"归档助理：在本案检索并查看 {_N} 个页面片段",
    rf"归档助理：正在阅读 {_N} 个页面片段",
    rf"归档助理：来源核对完成，已处理 {_N} / {_N} 个页面片段",
    rf"\[本地 OCR\] 第 {_N}/{_N} 页完成",
    rf"补件增量分析：复用 {_N} 份材料，仅分析 {_N} 份新增材料",
    rf"输入文件: {_N} 个",
    rf"OCR 引擎调用: {_N} 次",
    rf"提取到 {_N} 个字段",
    rf"已找到: {_N} 项",
    rf"缺失: {_N} 项",
    rf"归档完成: {_N} 页",
    rf"缺失/跳过项: {_N} 项",
    rf"源 PDF 已包含 {_N}/{_N} 页",
    rf"\[PDF 导航\] {_N} 个书签，{_N} 条目录链接",
    rf"\[WARN\] 第 {_N} 页未识别到正文文字，请核对是否为空白页或图像材料。",
))


def safe_log_line(value):
    if type(value) is not str or len(value) > 300 or "\n" in value or "\r" in value:
        return None
    line = value.strip()
    return line if line in _FIXED_LOGS or any(pattern.fullmatch(line) for pattern in _COUNTER_LOGS) else None


def filtered_log_lines(values):
    if type(values) is str:
        values = values.splitlines()
    if type(values) not in (list, tuple):
        return []
    return [line for value in values if (line := safe_log_line(value)) is not None][-500:]


@dataclass
class ProgressTracker:
    task_id: int
    progress: float = 0.0
    stage: str = ""
    log_lines: list = field(default_factory=list)
    _subscribers: set = field(default_factory=set)
    _loop: object = None

    def _send(self, message):
        def deliver():
            for q in list(self._subscribers):
                try:
                    q.put_nowait(message)
                except asyncio.QueueFull:
                    pass
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(deliver)

    def log(self, msg: str) -> None:
        text = safe_log_line(msg)
        if text is None:
            return
        self.log_lines.append(text)
        del self.log_lines[:-500]
        self._send({"type": "log", "text": text})

    def update(self, progress: float, stage: str = "") -> None:
        self.progress = progress
        if stage:
            self.stage = stage
        self._send({"type": "progress", "progress": self.progress, "stage": self.stage})

    def finish(self) -> None:
        self._send({"type": "done"})

    def fail(self, error) -> None:
        self._send({"type": "error", "error": public_error(error)})

    async def subscribe(self) -> asyncio.Queue:
        self._loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._subscribers.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)


class TaskManager:
    def __init__(self) -> None:
        self._trackers: dict = {}
        self._tasks: dict = {}
        self._sem = asyncio.Semaphore(1)
        self._case_locks: dict[str, asyncio.Lock] = {}

    def case_lock(self, case_id):
        return self._case_locks.setdefault(case_id, asyncio.Lock())

    async def _persist(self, task_id):
        from ..database import AsyncSessionLocal
        from ..models import ArchiveTask
        tracker = self.get_tracker(task_id)
        async with AsyncSessionLocal() as db:
            task = await db.get(ArchiveTask, task_id)
            if task:
                tracker.log_lines = filtered_log_lines(tracker.log_lines)
                task.log_text = "\n".join(tracker.log_lines)
                task.heartbeat_at = datetime.now(timezone.utc)
                if task.status.value in ("pending", "running"):
                    task.progress = max(task.progress or 0, tracker.progress)
                await db.commit()

    async def _record_failure(self, task_id, error):
        """Best-effort fixed failure state; never let raw storage errors escape."""
        from ..database import AsyncSessionLocal
        from ..models import ArchiveTask, TaskStatus
        code = log_failure(logger, error, task_id)
        tracker = self.get_tracker(task_id)
        tracker.fail(code)
        try:
            async with AsyncSessionLocal() as db:
                task = await db.get(ArchiveTask, task_id)
                if task:
                    task.status, task.phase = TaskStatus.failed, "failed"
                    task.error = public_error(code)
                    task.output_pdf, task.artifacts = "", None
                    task.finished_at = datetime.now(timezone.utc)
                    await db.commit()
        except Exception:
            log_failure(logger, ErrorCode.TASK_FAILURE_PERSIST_FAILED, task_id)

    def get_tracker(self, task_id: int) -> ProgressTracker:
        if task_id not in self._trackers:
            self._trackers[task_id] = ProgressTracker(task_id=task_id)
        return self._trackers[task_id]

    def start(self, task_id: int, coro) -> None:
        if self.is_running(task_id):
            coro.close()
            raise RuntimeError("任务正在执行")
        tracker = self.get_tracker(task_id)
        tracker._loop = asyncio.get_running_loop()
        tracker.stage = "等待工作站处理"
        tracker.progress = 0
        async def serial():
            started = False
            try:
                async with self._sem:
                    started = True
                    # Restore durable events before the first heartbeat can write
                    # an empty in-memory tracker over a previous attempt's log.
                    try:
                        from ..database import AsyncSessionLocal
                        from ..models import ArchiveTask
                        async with AsyncSessionLocal() as db:
                            previous = await db.get(ArchiveTask, task_id)
                            if previous and previous.log_text and not tracker.log_lines:
                                tracker.log_lines = filtered_log_lines(previous.log_text)
                    except Exception:
                        log_failure(logger, ErrorCode.TASK_LOG_LOAD_FAILED, task_id)
                    stop_monitor = asyncio.Event()
                    async def heartbeat():
                        while not stop_monitor.is_set():
                            try:
                                await self._persist(task_id)
                            except Exception:
                                log_failure(logger, ErrorCode.TASK_LOG_PERSIST_FAILED, task_id)
                            try:
                                await asyncio.wait_for(stop_monitor.wait(), timeout=2)
                            except asyncio.TimeoutError:
                                pass
                    monitor = asyncio.create_task(heartbeat())
                    try:
                        await coro
                    finally:
                        stop_monitor.set()
                        await monitor
                        try:
                            await self._persist(task_id)
                        except Exception:
                            log_failure(logger, ErrorCode.TASK_FINAL_PERSIST_FAILED, task_id)
            except Exception as exc:
                await self._record_failure(task_id, exc)
            finally:
                if not started:
                    coro.close()
        self._tasks[task_id] = asyncio.create_task(serial(), name="archive-" + str(task_id))

    def is_running(self, task_id: int) -> bool:
        t = self._tasks.get(task_id)
        return t is not None and not t.done()

    @property
    def semaphore(self) -> asyncio.Semaphore:
        return self._sem


task_manager = TaskManager()
