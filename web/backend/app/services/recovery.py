"""Reconcile interrupted jobs on single-worker workstation startup."""
from sqlalchemy import select
from ..database import AsyncSessionLocal
from ..models import ArchiveTask, TaskStatus, Case, User
from ..case_access import can_access_case
from .execution_profile import validate_task_authorization
from .safe_errors import SafeTaskError, public_error


async def recover_interrupted_tasks():
    resume = []
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ArchiveTask).where(ArchiveTask.status.in_([TaskStatus.pending, TaskStatus.running])))
        for task in result.scalars():
            if (isinstance(task.idempotency_key, str)
                    and task.idempotency_key.startswith("real-auto-scheduled-")
                    and task.requested_operation not in ("draft", "assemble")):
                # The external daily gate has already consumed this attempt.
                # A restart cannot infer whether a cloud request was charged,
                # even if an earlier analysis checkpoint is present. Preserve
                # all material/snapshot/field evidence and never requeue it.
                task.status = TaskStatus.failed
                task.phase = "failed"
                task.stage = "定时实卷分析已中断，等待人工检查"
                task.error = "为避免重复计费，启动恢复未重新调用模型。请人工核查原任务状态与每日回归台账；材料和已保存分析保留。"
                task.output_pdf = ""
                continue
            actor = await db.get(User, task.created_by) if task.created_by else None
            case = await db.get(Case, task.case_id)
            try:
                validate_task_authorization(task)
            except SafeTaskError as exc:
                task.status = TaskStatus.failed
                task.phase = "failed"
                task.stage = "任务授权检查未通过，未发送材料"
                task.error = public_error(exc)
                task.output_pdf = ""
                continue
            if task.source_manifest and can_access_case(actor, case):
                task.status = TaskStatus.pending
                task.phase = "queued"
                task.stage = "正在恢复上次未完成的步骤"
                task.error = ""
                resume.append((task.id, task.case_id, case.org_id, actor.id, task.requested_operation, task.order_mode))
            else:
                task.status = TaskStatus.failed
                task.phase = "failed"
                task.stage = "上次处理已中断"
                task.error = "工作站曾停止或重启；旧任务缺少可恢复的输入版本或发起账号，请继续归档建立新修订。原件和核对草稿保留。"
            task.output_pdf = ""
        await db.commit()
    from .archive_service import run_archive, run_assemble
    from .task_manager import task_manager
    for task_id, case_id, org_id, actor_id, operation, order in resume:
        coroutine = (run_assemble(task_id, case_id, org_id, actor_id, order, draft=True) if operation == "draft" else
                     run_assemble(task_id, case_id, org_id, actor_id, order) if operation == "assemble" else
                     run_archive(task_id, case_id, org_id, actor_id, order))
        task_manager.start(task_id, coroutine)
