#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""将 LLM 提取字段映射到各 Word 模板中的【占位符】名称"""

from case_outcome import truncate_chinese, CASE_OUTCOME_MAX_LEN
from field_sanitize import is_placeholder_value, parse_court_document_list, is_valid_field_value

# 送达材料清单：同一占位符在多行各填一份法院文书
COURT_DOC_PLACEHOLDER = "PDF中落款是法院的所有文件，识别文件抬头"
SEQ_PLACEHOLDER_PREFIX = "__seq__"

def get_template_paths():
    """模板路径：打包目录 templates/bundled（EXE 可移植）"""
    try:
        from app_paths import get_template_paths as _paths
        return _paths()
    except ImportError:
        pass
    import os
    base = os.path.join(os.path.dirname(__file__), "templates", "bundled")
    names = ["立案审批表", "送达材料清单", "档案卷宗", "结案报告表", "质量监督卡"]
    return {n: os.path.join(base, f"{n}.doc") for n in names}


class _TemplatePathsProxy(dict):
    def __getitem__(self, key):
        return get_template_paths()[key]

    def items(self):
        return get_template_paths().items()

    def keys(self):
        return get_template_paths().keys()

    def values(self):
        return get_template_paths().values()

    def __iter__(self):
        return iter(get_template_paths())


ORIGINAL_TEMPLATE_PATHS = _TemplatePathsProxy()

# LLM 字段名 -> 模板【占位符】名（同一值可填入多个占位符）
PLACEHOLDER_ALIASES = {
    # 各占位符只映射到语义匹配的字段，禁止跨槽位 fallback（如当事人→委托人）
    "委托代理合同中委托人": ["委托人", "委托人名称"],
    "起诉状中的原告": ["起诉状中的原告", "判决书中的原告", "原告"],
    "判决书中的原告": ["判决书中的原告", "起诉状中的原告", "原告"],
    "判决书上的原告": ["判决书中的原告", "起诉状中的原告", "原告"],
    "起诉状中的被告": ["起诉状中的被告", "判决书中的被告", "对方当事人", "被告"],
    "判决书中的被告": ["判决书中的被告", "起诉状中的被告", "对方当事人", "被告"],
    "委托代理合同中委托人联系电话": ["委托人电话"],
    "起诉状中，原告的“住所地”": ["地址"],
    "固定XXX元\\基础XXX元+风险": ["收费标准"],  # 与模板中反斜杠一致
    "委托代理合同中落款日期": ["收案日期"],
    "民事判决书的落款法院（如果有二审需要一并罗列进该项）": ["审理法院"],
    "判决书原告的委托诉讼代理人": ["判决书原告的委托诉讼代理人", "判决书上代理律师", "承办律师", "代理律师"],
    "判决书上代理律师": ["判决书上代理律师", "判决书原告的委托诉讼代理人", "承办律师", "代理律师"],
    "判决书内确认的案由（被告主体信息后的下一段会注明原告XXX诉被告XXXAAA一案，AAA就是案由）": ["案由"],
    # 结案报告表「案件或项目名称」：须完整称谓，勿仅用案由（见 _build_case_project_name）
    "判决书内的（原告XXX诉被告XXXAAA一案）": ["案件或项目名称"],
    "一审、二审（如有）、执行": ["审级"],
    "一审案号（民事判决书的案号）、二审案号（如有）、执行案号（执行裁定书中的案号）": ["法院收案号", "案号"],
    "《律师业务卷宗（银行案)》sheet1的I列，根据判决书、执行裁定书的内容，匹配最相近的选项填写": ["结案小结", "审（办）结果", "审办结果"],
    "PDF中落款是法院的所有文件，识别文件抬头": ["法院文件清单"],
    "留空": [],
    "民事": [],
}

CASE_BRIEF_PLACEHOLDER = (
    "XXX（对方当事人）的贷款逾期，委托人委托我所代理起诉，"
    "起诉标的XXX（起诉状中起诉标的）元"
)

# 无【】的特殊占位符（质量监督卡）
PLAIN_PLACEHOLDERS = {
    "=判决上的原告律师": ["承办律师", "代理律师"],
    "=委托代理合同上委托人+联系地址+电话": ["委托人联系地址及电话", "委托人联系信息"],
}


def _first_value(base_fields, keys):
    for key in keys:
        val = base_fields.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


import re as _re

# 伪值检测：LLM 把字段说明/提取要求当作值返回时，这些特征不会出现在真实数据中
# 实现见 field_sanitize.looks_like_requirement_text / is_valid_field_value


def _looks_like_requirement_text(val: str) -> bool:
    from field_sanitize import looks_like_requirement_text
    return looks_like_requirement_text(val)


def _is_valid_field_value(val: str) -> bool:
    return is_valid_field_value(val)




CASE_PROJECT_PLACEHOLDER = "判决书内的（原告XXX诉被告XXXAAA一案）"


def _build_case_project_name(base_fields, *, strict_evidence=False) -> str:
    """
    结案报告表「案件或项目名称」：XXX与XXX的XXXX纠纷案（或判决书「原告诉被告…一案」全文）。
    """
    if strict_evidence:
        # Only an explicitly supplied name belongs here. Workstation names are
        # derived later from supported facts by form_drafts, without assigning
        # plaintiff/defendant roles or replacing a human's deliberate blank.
        value = base_fields.get("案件或项目名称")
        return value if isinstance(value, str) else ""
    for key in ("案件或项目名称",):
        v = (base_fields.get(key) or "").strip()
        if not v:
            continue
        if "诉" in v or "与" in v or "被告人" in v or "涉嫌" in v:
            return v
        if len(v) >= 8 and not v.endswith("纠纷"):
            return v

    ay = (base_fields.get("案由") or base_fields.get("罪名") or "").strip()
    case_type = (base_fields.get("案件类别") or "").strip()
    if case_type == "刑事":
        accused = _first_value(base_fields, ["被告人", "犯罪嫌疑人", "当事人"])
        if accused and ay:
            return f"被告人{accused}{ay}一案"
        if accused:
            return f"被告人{accused}一案"
    if case_type == "非诉":
        client = _first_value(base_fields, ["项目委托人", "委托人"])
        matter = _first_value(base_fields, ["项目事项", "项目类型", "案由"])
        if client and matter:
            return f"{client}{matter}项目"
        return matter or client
    if case_type == "法律顾问":
        client = _first_value(base_fields, ["顾问单位", "委托人"])
        matter = _first_value(base_fields, ["顾问事项", "案由"]) or "常年法律顾问"
        return f"{client}{matter}项目" if client else matter
    p1 = _first_value(base_fields, ["当事人", "委托人", "委托方", "判决书中的原告", "起诉状中的原告"])
    p2 = (base_fields.get("对方当事人") or "").strip()
    if p1 and p2 and ay:
        if case_type == "行政":
            return f"{p1}诉{p2}{ay}一案"
        cause = ay
        if "纠纷" not in cause:
            cause = cause + "纠纷"
        if not cause.endswith("案"):
            cause = cause + "案"
        return f"{p1}与{p2}的{cause}"
    if ay:
        return ay
    return _first_value(base_fields, ["案件或项目名称", "案由"])


def _build_case_brief(base_fields):
    brief = base_fields.get("案情简介", "").strip()
    if brief:
        return brief
    case_type = (base_fields.get("案件类别") or "").strip()
    if case_type == "刑事":
        accused = _first_value(base_fields, ["被告人", "犯罪嫌疑人", "当事人"])
        charge = _first_value(base_fields, ["罪名", "案由"])
        client = _first_value(base_fields, ["委托人"])
        if accused:
            charge_text = f"涉嫌{charge}" if charge else "所涉刑事案件"
            client_text = f"接受{client}委托，" if client else ""
            return f"{client_text}为{accused}{charge_text}一案提供辩护或法律帮助"
        return ""
    if case_type == "非诉":
        client = _first_value(base_fields, ["项目委托人", "委托人"])
        matter = _first_value(base_fields, ["项目事项", "项目类型", "案由"])
        if client and matter:
            return f"{client}委托我所办理{matter}项目并提供专项法律服务"
        return matter
    if case_type == "法律顾问":
        client = _first_value(base_fields, ["顾问单位", "委托人"])
        matter = _first_value(base_fields, ["顾问事项", "案由"]) or "日常法律事务"
        return f"为{client}提供常年法律顾问服务，主要办理{matter}" if client else matter
    party = _first_value(base_fields, ["对方当事人"])
    client = _first_value(base_fields, ["委托人"])
    target = base_fields.get("起诉标的", base_fields.get("标的额", ""))
    if party and client:
        target_part = f"，起诉标的{target}元" if target else ""
        return f"{client}与{party}发生{base_fields.get('案由') or '争议'}，委托我所代理处理{target_part}"
    return ""


def _build_client_contact(base_fields):
    if base_fields.get("委托人联系地址及电话"):
        return str(base_fields["委托人联系地址及电话"]).strip()
    client = _first_value(base_fields, ["委托人", "委托人名称"])
    phone = _first_value(base_fields, ["委托人电话"])
    addr = _first_value(base_fields, ["地址"])
    parts = [p for p in [client, addr, phone] if p]
    return " ".join(parts)


def _adapt_fields_for_template(base_fields):
    """Map case-specific legal roles onto legacy five-form placeholders."""
    fields = dict(base_fields or {})
    case_type = (fields.get("案件类别") or "").strip()

    if case_type == "刑事":
        party = _first_value(fields, ["被告人", "犯罪嫌疑人", "当事人"])
        opponent = _first_value(fields, ["公诉机关", "被害人", "对方当事人"])
        lawyer = _first_value(fields, ["辩护人", "承办律师", "代理律师"])
        if party:
            fields.setdefault("当事人", party)
            fields.setdefault("判决书中的原告", party)
            fields.setdefault("起诉状中的原告", party)
        if opponent:
            fields.setdefault("对方当事人", opponent)
            fields.setdefault("判决书中的被告", opponent)
            fields.setdefault("起诉状中的被告", opponent)
        if lawyer:
            fields.setdefault("承办律师", lawyer)
        if fields.get("罪名"):
            fields.setdefault("案由", fields["罪名"])
        if fields.get("审判法院"):
            fields.setdefault("审理法院", fields["审判法院"])
    elif case_type == "行政":
        party = _first_value(fields, ["行政相对人", "当事人", "原告"])
        opponent = _first_value(fields, ["行政机关", "被诉行政机关", "对方当事人"])
        if party:
            fields.setdefault("当事人", party)
            fields.setdefault("判决书中的原告", party)
        if opponent:
            fields.setdefault("对方当事人", opponent)
            fields.setdefault("判决书中的被告", opponent)
    elif case_type in ("非诉", "法律顾问"):
        client = _first_value(fields, ["项目委托人", "顾问单位", "委托人"])
        matter = _first_value(fields, ["项目事项", "顾问事项", "案由"])
        result = _first_value(fields, ["服务成果", "结案小结", "审（办）结果"])
        if client:
            fields.setdefault("委托人", client)
            fields.setdefault("当事人", client)
            fields.setdefault("判决书中的原告", client)
        if matter:
            fields.setdefault("案由", matter)
        if result:
            fields.setdefault("结案小结", result)
            fields.setdefault("审（办）结果", result)

    return fields


def expand_fields_for_template(template_name, base_fields):
    """
    把 LLM 通用字段展开为某模板内所有需要替换的键值对。
    键为占位符内容（不含【】），值为替换文本。
    """
    base_fields = _adapt_fields_for_template(base_fields)

    if template_name == "立案审批表":
        from lian_approval_fill import expand_lian_fields

        return expand_lian_fields(base_fields)

    # 【修复第12轮迭代】送达材料清单fallback：确保承办律师字段有值
    # 在映射开始前执行，确保后续映射能使用到完整数据
    if template_name == "送达材料清单":
        if not base_fields.get("承办律师") or not str(base_fields.get("承办律师", "")).strip():
            agent_lawyer = (base_fields.get("代理律师") or base_fields.get("判决书上代理律师") or "").strip()
            if is_valid_field_value(agent_lawyer):
                base_fields["承办律师"] = agent_lawyer

    # 结案小结 / 审（办）结果：统一为 ≤150 字的综合表述
    outcome = (
        base_fields.get("结案小结")
        or base_fields.get("审（办）结果")
        or base_fields.get("审办结果")
        or ""
    )
    if outcome:
        outcome = truncate_chinese(str(outcome).strip(), CASE_OUTCOME_MAX_LEN)
        base_fields["结案小结"] = outcome
        base_fields["审（办）结果"] = outcome
        base_fields["审办结果"] = outcome

    result = {}

    # 【】占位符
    for placeholder, source_keys in PLACEHOLDER_ALIASES.items():
        if placeholder == "留空":
            result[placeholder] = ""
            continue
        if placeholder == "所有字体格式要求：宋体四号，行距：固定值20磅，案情简介加上限制100字内":
            result[placeholder] = ""
            continue
        if placeholder == "民事":
            result[placeholder] = base_fields.get("案件类别", "民事") or "民事"
            continue
        if placeholder == CASE_PROJECT_PLACEHOLDER:
            val = _build_case_project_name(base_fields)
            if val:
                result[placeholder] = val
            continue

        if source_keys:
            # 送达材料清单：法院文书由 __seq__ 按行填入，此处跳过整表替换
            if (
                placeholder == COURT_DOC_PLACEHOLDER
                and template_name == "送达材料清单"
            ):
                continue
            val = _first_value(base_fields, source_keys)
            if _is_valid_field_value(val):
                result[placeholder] = val

    # 案情简介类长占位符
    case_brief = _build_case_brief(base_fields)
    if case_brief:
        result[CASE_BRIEF_PLACEHOLDER] = case_brief

    # 格式说明类占位符：清空提示文字
    result["所有字体格式要求：宋体四号，行距：固定值20磅，案情简介加上限制100字内"] = ""

    # 无括号占位符
    for placeholder, source_keys in PLAIN_PLACEHOLDERS.items():
        if placeholder == "=委托代理合同上委托人+联系地址+电话":
            val = _build_client_contact(base_fields)
        else:
            val = _first_value(base_fields, source_keys)
        if _is_valid_field_value(val):
            result[placeholder] = val

    # 送达材料清单：法院文书按行各填一项（不整表重复同一串）
    court_docs_raw = base_fields.get("法院文件清单", base_fields.get("法院文书", ""))
    if template_name == "送达材料清单":
        doc_list = parse_court_document_list(str(court_docs_raw or ""))
        if doc_list:
            result[f"{SEQ_PLACEHOLDER_PREFIX}{COURT_DOC_PLACEHOLDER}"] = doc_list
    elif court_docs_raw:
        result[COURT_DOC_PLACEHOLDER] = str(court_docs_raw).strip()

    return result
