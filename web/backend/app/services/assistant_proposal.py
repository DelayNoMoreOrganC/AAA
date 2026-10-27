"""Signed, short-lived human-adoption proposals; no model action writes state."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import uuid

from ..security import _create_token, decode_token
from .task_sources import fields_digest

PROPOSAL_TOOL = "propose_field_change"
EDITABLE_FIELDS = (
    "委托人", "当事人", "对方当事人", "承办律师", "律师事务所", "案由", "案号", "审理法院", "审级", "合同号",
    "收案日期", "立案审批日期", "结案日期", "收费标准", "委托人电话", "地址", "结案小结", "案情简介", "法院收案号", "案件或项目名称",
    "应收业务费", "已收业务费", "尚欠业务费", "应退业务费", "归档日期",
)
ALIASES = {"委托人": ("客户", "委托人名称"), "合同号": ("合同编号",), "案号": ("案件编号",),
           "地址": ("联系地址", "住所地"), "立案审批日期": ("立案日期",), "结案小结": ("办理结果", "审办结果")}
REASON = "根据你本次输入的明确新值提出；采用后记为人工修改，不代表原文已经证明。"


class ProposalError(ValueError):
    pass


def field_value(fields, field):
    value = (fields or {}).get(field)
    if value is None:
        return ""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ProposalError("当前字段格式不支持对话修改，请打开表格核对。")
    return str(value)


def validate_proposal_command(command, message):
    field, value = command.get("field"), command.get("value")
    if (set(command) != {"tool", "field", "query", "value"} or command.get("tool") != PROPOSAL_TOOL
            or command.get("query") != "" or field not in EDITABLE_FIELDS
            or not isinstance(value, str) or len(value) > 1500):
        raise ProposalError("修改建议包含不允许的字段或格式，本次未保存任何修改。")
    # A model may select a tool, but cannot manufacture a new fact or transform
    # a quoted document instruction into an adopted edit. History is insufficient.
    if (not isinstance(message, str)
            or not any(name in message for name in (field, *ALIASES.get(field, ())))
            or not re.search(r"改为|改成|修改为|更新为|设置为|填为|填写|替换为|清空|留空|置空|补充", message)
            or re.search(r"不要|不需要|无需|不应|不是要|别(?:把|将|改|填)", message)):
        raise ProposalError("请在本次消息明确写出要修改的字段及新值；本次未保存任何修改。")
    if value:
        if value not in message:
            raise ProposalError("建议的新值未逐字出现在本次请求中，请明确提供新值后再试。")
    elif not re.search(r"清空|留空|置空", message):
        raise ProposalError("清空字段需要你在本次请求中明确说明。")
    return field, value


def make_proposal(task, user_id, command, message):
    field, after = validate_proposal_command(command, message)
    before = field_value(task.fields, field)
    if before == after:
        return {"tool": PROPOSAL_TOOL, "message": "该字段已经是这个值，无需修改。", "items": [],
                "action": {"type": "fields", "label": "查看字段"}}
    expiry = datetime.now(timezone.utc) + timedelta(minutes=15)
    ident = uuid.uuid4().hex
    payload = {"proposal_id": ident, "task_id": task.id, "revision": task.revision,
               "source_version": task.source_version, "field": field, "after": after,
               "fields_digest": fields_digest(task.fields, task.order_mode)}
    token = _create_token(user_id, expiry, "assistant_proposal", payload)
    return {"tool": PROPOSAL_TOOL, "message": "已生成修改建议，尚未保存。请核对前后内容，再决定是否采用。", "items": [],
            "action": {"type": "fields", "label": "打开表格核对"},
            "proposal": {"id": ident, "proposal_token": token, "field": field, "before": before, "after": after,
                         "reason": REASON, "revision": task.revision, "source_version": task.source_version,
                         "expires_at": expiry.isoformat()}}


def decode_proposal(token, task, user_id, expected_revision):
    payload = decode_token(token)
    if (not payload or payload.get("type") != "assistant_proposal" or payload.get("sub") != user_id
            or payload.get("task_id") != task.id):
        raise ProposalError("建议无效、已过期或不属于当前账号和任务，请重新提出修改。")
    field, after = payload.get("field"), payload.get("after")
    if (field not in EDITABLE_FIELDS or not isinstance(after, str) or len(after) > 1500
            or payload.get("revision") != task.revision or expected_revision != task.revision
            or payload.get("source_version") != task.source_version
            or payload.get("fields_digest") != fields_digest(task.fields, task.order_mode)):
        raise ProposalError("建议已应用或当前材料、修订、字段值已改变，请刷新后重新提出修改。")
    return payload
