"""Fixed public errors: exception messages and chains are never diagnostics."""
from enum import Enum


class ErrorCode(str, Enum):
    ANALYSIS_FAILED = "GD_ANALYSIS_FAILED"
    ASSEMBLY_FAILED = "GD_ASSEMBLY_FAILED"
    TASK_FAILED = "GD_TASK_FAILED"
    CASE_UNAVAILABLE = "GD_CASE_UNAVAILABLE"
    NO_SOURCES = "GD_NO_SOURCES"
    SOURCE_CHANGED = "GD_SOURCE_CHANGED"
    SNAPSHOT_STALE = "GD_SNAPSHOT_STALE"
    SETUP_NOT_READY = "GD_SETUP_NOT_READY"
    LOCAL_URL_INVALID = "GD_LOCAL_URL_INVALID"
    LOCAL_MODEL_UNSELECTED = "GD_LOCAL_MODEL_UNSELECTED"
    LOCAL_MODEL_UNLOADED = "GD_LOCAL_MODEL_UNLOADED"
    LOCAL_MODEL_UNAVAILABLE = "GD_LOCAL_MODEL_UNAVAILABLE"
    LOCAL_OCR_UNAVAILABLE = "GD_LOCAL_OCR_UNAVAILABLE"
    LOCAL_OCR_MODELS_MISSING = "GD_LOCAL_OCR_MODELS_MISSING"
    CLOUD_DISABLED = "GD_CLOUD_DISABLED"
    CLOUD_MODEL_UNCONFIGURED = "GD_CLOUD_MODEL_UNCONFIGURED"
    CLOUD_OCR_UNCONFIGURED = "GD_CLOUD_OCR_UNCONFIGURED"
    CLOUD_CONSENT_REQUIRED = "GD_CLOUD_CONSENT_REQUIRED"
    EXECUTION_PROFILE_INVALID = "GD_EXECUTION_PROFILE_INVALID"
    GLM_KEY_UNCONFIGURED = "GD_GLM_KEY_UNCONFIGURED"
    GLM_CHECK_FAILED = "GD_GLM_CHECK_FAILED"
    GLM_ANALYSIS_FAILED = "GD_GLM_ANALYSIS_FAILED"
    DEEPSEEK_KEY_UNCONFIGURED = "GD_DEEPSEEK_KEY_UNCONFIGURED"
    DEEPSEEK_CHECK_FAILED = "GD_DEEPSEEK_CHECK_FAILED"
    DEEPSEEK_ANALYSIS_FAILED = "GD_DEEPSEEK_ANALYSIS_FAILED"
    DEEPSEEK_AUTH_FAILED = "GD_DEEPSEEK_AUTH_FAILED"
    DEEPSEEK_QUOTA_EXHAUSTED = "GD_DEEPSEEK_QUOTA_EXHAUSTED"
    DEEPSEEK_RATE_LIMITED = "GD_DEEPSEEK_RATE_LIMITED"
    RECOGNITION_PROGRESS_INVALID = "GD_RECOGNITION_PROGRESS_INVALID"
    RECOGNITION_PROGRESS_STORAGE = "GD_RECOGNITION_PROGRESS_STORAGE"
    RECOGNITION_PROGRESS_CONFIG = "GD_RECOGNITION_PROGRESS_CONFIG"
    PROCESSING_MODE_INVALID = "GD_PROCESSING_MODE_INVALID"
    SOURCE_VERSION_MISSING = "GD_SOURCE_VERSION_MISSING"
    CONFIRMATION_REQUIRED = "GD_CONFIRMATION_REQUIRED"
    SNAPSHOT_CONFIRMATION_MISMATCH = "GD_SNAPSHOT_CONFIRMATION_MISMATCH"
    UNRESOLVED_ISSUES = "GD_UNRESOLVED_ISSUES"
    SYSTEM_FORMS_INCOMPLETE = "GD_SYSTEM_FORMS_INCOMPLETE"
    ASSEMBLY_VALIDATION_FAILED = "GD_ASSEMBLY_VALIDATION_FAILED"
    COVER_PAGE_COUNT_FAILED = "GD_COVER_PAGE_COUNT_FAILED"
    ARTIFACT_VALIDATION_FAILED = "GD_ARTIFACT_VALIDATION_FAILED"
    BROWSER_RENDER_FAILED = "GD_BROWSER_RENDER_FAILED"
    ORIGINAL_TEMPLATE_FAILED = "GD_ORIGINAL_TEMPLATE_FAILED"
    ORIGINAL_TEMPLATE_OVERFLOW = "GD_ORIGINAL_TEMPLATE_OVERFLOW"
    CATALOG_TEMPLATE_MISMATCH = "GD_CATALOG_TEMPLATE_MISMATCH"
    TASK_LOG_LOAD_FAILED = "GD_TASK_LOG_LOAD_FAILED"
    TASK_LOG_PERSIST_FAILED = "GD_TASK_LOG_PERSIST_FAILED"
    TASK_FINAL_PERSIST_FAILED = "GD_TASK_FINAL_PERSIST_FAILED"
    TASK_FAILURE_PERSIST_FAILED = "GD_TASK_FAILURE_PERSIST_FAILED"


_MESSAGES = {
    ErrorCode.ANALYSIS_FAILED: "材料分析未完成，请检查材料可读性及本机 OCR、模型状态后重试。原件和已保存草稿保留。",
    ErrorCode.ASSEMBLY_FAILED: "归档生成未完成，请检查本机 PDF 生成器及输出目录权限后重试。原件和已保存草稿保留。",
    ErrorCode.TASK_FAILED: "工作站未能完成当前步骤，请检查运行环境后继续归档。原件和已保存草稿保留。",
    ErrorCode.CASE_UNAVAILABLE: "案件不可用，请刷新并确认当前账号仍有权限。",
    ErrorCode.NO_SOURCES: "未上传文件，请先添加案件材料。",
    ErrorCode.SOURCE_CHANGED: "材料、分类或办理阶段已变化，请继续归档更新分析后重新确认。",
    ErrorCode.SNAPSHOT_STALE: "保存的分析版本与当前任务不一致，请继续归档建立新修订。",
    ErrorCode.SETUP_NOT_READY: "工作站尚未就绪，请在设置中检查本机模型、OCR 和 PDF 生成器。",
    ErrorCode.LOCAL_URL_INVALID: "本地模型地址必须使用工作站回环 IP，且不能含账号或查询参数。",
    ErrorCode.LOCAL_MODEL_UNSELECTED: "尚未选择本地模型，请由管理员完成配置。",
    ErrorCode.LOCAL_MODEL_UNLOADED: "配置的本地模型尚未加载，请加载后重试。",
    ErrorCode.LOCAL_MODEL_UNAVAILABLE: "本地模型服务未就绪，请由管理员启动模型服务。",
    ErrorCode.LOCAL_OCR_UNAVAILABLE: "缺少本地 OCR 组件，请由部署人员安装。",
    ErrorCode.LOCAL_OCR_MODELS_MISSING: "本地 OCR 模型包不完整，请由部署人员修复。",
    ErrorCode.CLOUD_DISABLED: "工作站已禁止外部 AI，请使用本地模式。",
    ErrorCode.CLOUD_MODEL_UNCONFIGURED: "未配置云端模型，请由管理员检查设置。",
    ErrorCode.CLOUD_OCR_UNCONFIGURED: "未配置云端 OCR，请由管理员检查设置。",
    ErrorCode.CLOUD_CONSENT_REQUIRED: "本次材料版本尚未授权发送至所选云端服务，请核对处理模式并重新同意。",
    ErrorCode.EXECUTION_PROFILE_INVALID: "任务处理模式或云端授权记录无效，已停止外发；请建立新的归档修订。",
    ErrorCode.GLM_KEY_UNCONFIGURED: "未配置 GLM 标准 API 密钥；Coding Plan 额度不能用于本工作站。",
    ErrorCode.GLM_CHECK_FAILED: "GLM 标准 API 连接检查未通过，请检查账号密钥、模型权限及网络后重试。",
    ErrorCode.GLM_ANALYSIS_FAILED: "GLM 视觉归档未完成，请检查标准 API 密钥、额度及模型服务后重试；未切换其他服务商，原件和已保存草稿保留。",
    ErrorCode.DEEPSEEK_KEY_UNCONFIGURED: "未配置 DeepSeek 标准 API 密钥，请在设置中保存后重试。",
    ErrorCode.DEEPSEEK_CHECK_FAILED: "DeepSeek 连接检查未通过，请检查密钥、模型权限和网络后重试。",
    ErrorCode.DEEPSEEK_ANALYSIS_FAILED: "DeepSeek 视觉整理未完成，请检查模型服务后重试；未切换服务商，原件和已保存结果保留。",
    ErrorCode.DEEPSEEK_AUTH_FAILED: "DeepSeek API 鉴权失败，请检查当前账号保存的密钥及模型权限。",
    ErrorCode.DEEPSEEK_QUOTA_EXHAUSTED: "DeepSeek API 余额不足，请检查标准 API 额度后重试。",
    ErrorCode.DEEPSEEK_RATE_LIMITED: "DeepSeek API 并发或速率受限，请稍后重试。",
    ErrorCode.RECOGNITION_PROGRESS_INVALID: "已保存的识别进度无法通过一致性检查，已停止，未自动重做已完成的模型请求。请由管理员检查进度记录；原材料和历史成果保留。",
    ErrorCode.RECOGNITION_PROGRESS_STORAGE: "识别进度暂时无法读取或保存，已停止。请检查工作站存储权限、空间或重复运行后继续。最后一次尚未保存的模型请求可能需要重发；原材料和历史成果保留。",
    ErrorCode.RECOGNITION_PROGRESS_CONFIG: "识别续跑配置无效，已停止。请由管理员检查工作站版本；未切换服务商，原材料和历史成果保留。",
    ErrorCode.PROCESSING_MODE_INVALID: "处理模式无效，请由管理员检查设置。",
    ErrorCode.SOURCE_VERSION_MISSING: "旧任务缺少输入版本，请继续归档建立新修订。",
    ErrorCode.CONFIRMATION_REQUIRED: "当前修订尚未最终确认，请重新核对并确认出卷。",
    ErrorCode.SNAPSHOT_CONFIRMATION_MISMATCH: "分析快照与最终确认内容不一致，请重新核对并保存后出卷。",
    ErrorCode.UNRESOLVED_ISSUES: "仍有尚未核对的材料异常，请完成集中核对后再生成。",
    ErrorCode.SYSTEM_FORMS_INCOMPLETE: "五份系统表 Word 未生成齐全，请检查本机生成环境后重试。",
    ErrorCode.ASSEMBLY_VALIDATION_FAILED: "归档合并失败；源页、分类或输出检查未通过，请核对材料后重试。",
    ErrorCode.COVER_PAGE_COUNT_FAILED: "封面分页或整卷页数未收敛，请检查系统表分页后重新生成。",
    ErrorCode.ARTIFACT_VALIDATION_FAILED: "成果页码或必需文件校验未通过，请重新生成并核对质检结果。",
    ErrorCode.BROWSER_RENDER_FAILED: "浏览器未能生成有效 PDF，请检查本机 PDF 生成器后重试。",
    ErrorCode.ORIGINAL_TEMPLATE_FAILED: "律所原表转换或版式校验未通过，已停止输出，未改用重画表格；请检查本机 Word 和原模板。",
    ErrorCode.ORIGINAL_TEMPLATE_OVERFLOW: "表格内容超出原表固定位置，请在表格核对中简要填写相关内容后重新生成。未截断内容，未扩大表框或增加页数。",
    ErrorCode.CATALOG_TEMPLATE_MISMATCH: "本次归档包含律所原目录未设置的项目，或对应原目录尚未提供。请核对适用目录；未遗漏材料或用重画目录替代。",
    ErrorCode.TASK_LOG_LOAD_FAILED: "历史进度记录暂不可读取，当前步骤仍将尝试恢复。",
    ErrorCode.TASK_LOG_PERSIST_FAILED: "当前进度暂未保存，请检查工作站存储状态。",
    ErrorCode.TASK_FINAL_PERSIST_FAILED: "最终进度暂未保存，请刷新并检查任务状态。",
    ErrorCode.TASK_FAILURE_PERSIST_FAILED: "失败状态暂未保存，请检查工作站存储状态后刷新。",
}


class SafeTaskError(RuntimeError):
    """Only a code is accepted; callers cannot attach a public custom message."""

    def __init__(self, code: ErrorCode, *, reasons=()):
        if type(code) is not ErrorCode or type(reasons) is not tuple or any(type(item) is not ErrorCode for item in reasons):
            raise TypeError("SafeTaskError requires an ErrorCode")
        self.code = code
        self.reasons = reasons
        super().__init__(_MESSAGES[code])


def error_code(error, fallback=ErrorCode.TASK_FAILED):
    """Do not inspect str(), args, causes, or message prefixes of raw errors."""
    if type(error) is ErrorCode:
        return error
    if type(error) is SafeTaskError and type(error.code) is ErrorCode:
        return error.code
    return fallback if type(fallback) is ErrorCode else ErrorCode.TASK_FAILED


def public_error(error, fallback=ErrorCode.TASK_FAILED):
    code = error_code(error, fallback)
    codes = [code]
    if type(error) is SafeTaskError and type(error.reasons) is tuple:
        codes.extend(item for item in error.reasons if type(item) is ErrorCode and item not in codes)
    return " ".join(f"{_MESSAGES[item]} [{item.value}]" for item in codes)


def original_template_hint(error):
    """Only fixed form field names may supplement a public overflow message."""
    from .original_template_service import OriginalTemplateError
    from .preview_fields import TEMPLATE_FIELD_SPECS
    if type(error) is not OriginalTemplateError or error.code not in ("overflow", "page_count", "frame"):
        return ""
    allowed = {item["key"] for fields in TEMPLATE_FIELD_SPECS.values() for item in fields}
    names = [name for name in getattr(error, "fields", ()) if type(name) is str and name in allowed]
    return " 请核对字段：" + "、".join(dict.fromkeys(names)) + "。" if names else ""


def _validated_template_target(value):
    from .preview_fields import TEMPLATE_FIELD_SPECS
    if type(value) is not dict:
        return None
    name = value.get("template_name")
    if type(name) is not str or name not in TEMPLATE_FIELD_SPECS:
        return None
    field = value.get("field")
    allowed = {item["key"] for item in TEMPLATE_FIELD_SPECS[name]}
    return {"template_name": name, "field": field if type(field) is str and field in allowed else None}


def original_template_target(error):
    """Recover only fixed template/field identities, never exception text or paths."""
    from .original_template_service import OriginalTemplateError
    if type(error) is not OriginalTemplateError or error.code not in ("overflow", "page_count", "frame"):
        return None
    target = _validated_template_target({"template_name": getattr(error, "template_name", None)})
    if target is None:
        return None
    for field in getattr(error, "fields", ()):
        candidate = _validated_template_target({**target, "field": field})
        if candidate["field"] is not None:
            return candidate
    return target


def task_recovery_target(task):
    """Old errors and in-flight operations must not expose a stale recovery link."""
    from ..models import TaskStatus
    if (getattr(task, "status", None) != TaskStatus.awaiting_review
            or getattr(task, "phase", None) != "needs_input" or not getattr(task, "error", "")):
        return None
    return _validated_template_target(getattr(task, "recovery_target", None))


# These are exact static readiness findings, not an exception-message allowlist.
# Unknown findings retain the generic setup guidance; no caller text is copied.
_READINESS_CODES = {
    "本地保密模式的模型地址必须是工作站回环 IP（127.0.0.1 或 ::1），且不能包含账号或查询参数": ErrorCode.LOCAL_URL_INVALID,
    "工作站尚未选择本地模型，请由管理员完成一次配置": ErrorCode.LOCAL_MODEL_UNSELECTED,
    "工作站缺少本地 OCR 组件，请由部署人员安装": ErrorCode.LOCAL_OCR_UNAVAILABLE,
    "工作站本地 OCR 模型包不完整，请由部署人员修复": ErrorCode.LOCAL_OCR_MODELS_MISSING,
    "配置的本地模型尚未加载，请在工作站加载后重试": ErrorCode.LOCAL_MODEL_UNLOADED,
    "本地模型服务未就绪，请由管理员启动模型服务": ErrorCode.LOCAL_MODEL_UNAVAILABLE,
    "工作站已禁止外部 AI，云端模式不能启动；请使用本地模式": ErrorCode.CLOUD_DISABLED,
    "未配置云端模型密钥": ErrorCode.CLOUD_MODEL_UNCONFIGURED,
    "未配置云端 OCR 密钥": ErrorCode.CLOUD_OCR_UNCONFIGURED,
    "未配置 GLM 标准 API 密钥；Coding Plan 额度不能用于本工作站": ErrorCode.GLM_KEY_UNCONFIGURED,
    "未配置 DeepSeek 标准 API 密钥": ErrorCode.DEEPSEEK_KEY_UNCONFIGURED,
    "处理模式无效": ErrorCode.PROCESSING_MODE_INVALID,
}


def readiness_error(readiness):
    issues = readiness.get("issues") if type(readiness) is dict else None
    reasons = tuple(dict.fromkeys(_READINESS_CODES[item] for item in issues or []
                                 if type(item) is str and item in _READINESS_CODES)) if type(issues) is list else ()
    return SafeTaskError(ErrorCode.SETUP_NOT_READY, reasons=reasons)


def log_failure(logger, error, task_id, fallback=ErrorCode.TASK_FAILED):
    """No exc_info: even a safe outer exception can carry a sensitive cause."""
    code = error_code(error, fallback)
    logger.error("task_id=%s error_code=%s", task_id if type(task_id) is int else "unknown", code.value)
    return code


def deepseek_error_code(error, fallback=ErrorCode.DEEPSEEK_ANALYSIS_FAILED):
    """Classify only the transport's fixed code, never its body/message/chain."""
    from ..core.v4_bridge import init_v4_path
    init_v4_path()
    from deepseek_vision_client import DeepSeekVisionError
    if type(error) is not DeepSeekVisionError:
        return fallback
    return {"KEY_MISSING": ErrorCode.DEEPSEEK_KEY_UNCONFIGURED,
            "KEY_INVALID": ErrorCode.DEEPSEEK_AUTH_FAILED,
            "AUTH_FAILED": ErrorCode.DEEPSEEK_AUTH_FAILED,
            "QUOTA_EXHAUSTED": ErrorCode.DEEPSEEK_QUOTA_EXHAUSTED,
            "RATE_LIMITED": ErrorCode.DEEPSEEK_RATE_LIMITED}.get(error.code, fallback)


def recognition_progress_error_code(error):
    """A private journal's contents/paths must never become a public diagnostic."""
    from ..core.v4_bridge import init_v4_path
    init_v4_path()
    from recognition_journal import RecognitionJournalError
    if type(error) is not RecognitionJournalError:
        return ErrorCode.ANALYSIS_FAILED
    if error.code in ("READ_FAILED", "WRITE_FAILED", "LOCKED", "LIMIT_EXCEEDED"):
        return ErrorCode.RECOGNITION_PROGRESS_STORAGE
    if error.code in ("CONFIG_INVALID", "REQUEST_INVALID"):
        return ErrorCode.RECOGNITION_PROGRESS_CONFIG
    return ErrorCode.RECOGNITION_PROGRESS_INVALID
