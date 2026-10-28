"""Platform-neutral browser preview definitions for the five system forms."""
from __future__ import annotations

import re
from typing import Any

from .analysis_snapshot import SYSTEM_TEMPLATE_NAMES


def _field(key: str, label: str, *aliases: str, multiline: bool = False) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "aliases": list(aliases),
        "multiline": multiline,
    }


TEMPLATE_FIELD_SPECS: dict[str, list[dict[str, Any]]] = {
    "立案审批表": [
        _field("案件类别", "案件类别"),
        _field("合同号", "合同号"),
        _field("委托人", "委托人", "委托人名称"),
        _field("当事人", "当事人"),
        _field("委托人电话", "委托人电话"),
        _field("传真", "传真", "委托人传真"),
        _field("收费标准", "收费标准"),
        _field("地址", "地址", "住所地"),
        _field("对方当事人", "对方当事人"),
        _field("案情简介", "案情简介", multiline=True),
        _field("立案审批日期", "立案日期", "收案日期"),
    ],
    "送达材料清单": [
        _field("合同号", "案号（律所内部编号）"),
        _field("承办律师", "承办律师"),
        _field("委托人", "委托人", "委托人名称"),
        _field("法院文件清单", "法院文件清单", "法院文书", multiline=True),
    ],
    "档案卷宗": [
        _field("案件类别", "案件类别"),
        _field("合同号", "合同号"),
        _field("承办律师", "承办律师"),
        _field("委托人", "委托人", "委托人名称"),
        _field("当事人", "当事人"),
        _field("对方当事人", "对方当事人"),
        _field("案由", "案由"),
        _field("收案日期", "收案日期"),
        _field("结案日期", "结案日期"),
        _field("审理法院", "审理法院"),
        _field("审级", "审级"),
        _field("法院收案号", "法院收案号", "案号"),
        _field("审（办）结果", "审（办）结果", "审办结果", "结案小结", multiline=True),
        _field("归档日期", "归档日期"),
        _field("立卷人", "立卷人"),
        _field("档案号", "档案号"),
        _field("保存期限", "保存期限", "保存年限"),
    ],
    "结案报告表": [
        _field("案件类别", "案件类别"),
        _field("委托人", "委托人名称", "委托人"),
        _field("案件或项目名称", "案件或项目名称"),
        _field("结案小结", "结案小结", "审（办）结果", "审办结果", multiline=True),
        _field("委托人对服务质量意见", "委托人对服务质量意见", "委托人对质量意见", multiline=True),
        _field("应收业务费", "应收业务费"),
        _field("已收业务费", "已收业务费"),
        _field("尚欠业务费", "尚欠业务费"),
        _field("应退业务费", "应退业务费"),
        _field("结案日期", "结案日期"),
    ],
    "质量监督卡": [
        _field("律师事务所", "律师事务所"),
        _field("合同号", "案号（律所内部编号）"),
        _field("承办律师", "承办律师"),
        _field(
            "委托人联系地址及电话",
            "委托人联系地址及电话",
            "委托人联系信息",
            multiline=True,
        ),
    ],
}


def _first_value(fields: dict[str, Any], keys: list[str]) -> Any:
    # A deliberate blank is a decision, not permission to restore an old alias.
    canonical = keys[0]
    if fields.get('_model_form_synthesis') and canonical in ('结案小结', '审（办）结果'):
        return fields.get(canonical) or ''
    provenance = (fields.get("_provenance") or {}).get(canonical) or []
    if isinstance(provenance, dict):
        provenance = [provenance]
    if canonical in fields and any(isinstance(p, dict) and p.get("method") == "human"
                                   and p.get("value") == fields[canonical] for p in provenance):
        return fields[canonical] if fields[canonical] is not None else ""
    for key in keys:
        value = fields.get(key)
        refs = (fields.get("_provenance") or {}).get(key) or []
        refs = [refs] if isinstance(refs, dict) else refs
        if key in fields and any(isinstance(p,dict) and p.get('method')=='human' and p.get('value')==value for p in refs):
            return value if value is not None else ""
        if value is not None and str(value).strip():
            return value
    return ""


def build_preview(template_name: str, fields: dict[str, Any] | None, *, derived_output=None,
                  source_manifest=(), issues=()) -> dict[str, Any]:
    if template_name not in SYSTEM_TEMPLATE_NAMES:
        raise ValueError(f"unknown template: {template_name}")
    source = dict(fields or {})
    case_label = str(source.get("案件类别") or "")
    label_overrides = {
        "刑事": {
            "当事人": "本所代理或辩护的当事人",
            "对方当事人": "其他相关方（按材料核对）",
            "案由": "罪名",
            "审理法院": "审判法院",
            "结案小结": "刑事案件办理结果",
        },
        "行政": {
            "当事人": "本所代理的当事人",
            "对方当事人": "诉讼相对方（按材料核对）",
            "案由": "行政案由",
            "结案小结": "行政案件办理结果",
        },
        "非诉": {
            "当事人": "项目委托人",
            "对方当事人": "项目相对方（如有）",
            "案由": "项目事项",
            "审理法院": "办理机构（如有）",
            "结案小结": "服务成果",
        },
        "法律顾问": {
            "当事人": "顾问单位",
            "对方当事人": "相关方（如有）",
            "案由": "顾问事项",
            "审理法院": "办理机构（如有）",
            "结案小结": "顾问服务成果",
        },
    }
    current_labels = label_overrides.get(case_label, {})
    items = []
    for spec in TEMPLATE_FIELD_SPECS[template_name]:
        keys = [spec["key"], *spec["aliases"]]
        if spec['key']=='立案审批日期':keys=[spec['key']]
        value = _first_value(source, keys)
        # Reference answers (including a typed "满意") are not permission to
        # answer a client's evaluation on a new generated form.
        if spec['key']=='委托人对服务质量意见':
            from ..core.v4_bridge import load
            value=load('form_cell_contracts').explicit_human_value(source,spec['key'])
        source_key = next((key for key in keys if source.get(key) == value), spec["key"])
        from .field_assurance import field_assurance
        items.append({
            "key": spec["key"],
            "label": current_labels.get(spec["key"], spec["label"]),
            "value": value,
            "multiline": spec["multiline"],
            "assurance": field_assurance(spec["key"], value, source, source_key=source_key,
                                         source_manifest=source_manifest, issues=issues),
        })
        from ..core.v4_bridge import load
        policy=load('form_cell_contracts').optional_output(spec['key'],value,source)
        if policy:
            status=items[-1]['assurance']['status']
            if (spec['key'] in load('form_cell_contracts').OPTIONAL_FACT_FIELDS
                    and (status=='conflict' or source_manifest and status not in
                         ('human_confirmed','source_supported','convention_default'))):
                policy={'value':'','code':'optional_blank','reason':'当前来源未能明确核实，按使用约定留空；不强制补填。'}
            items[-1]['value']=policy['value']
            items[-1]['output_policy']={k:v for k,v in policy.items() if k!='value'}
        if template_name == '立案审批表' and spec['key'] == '收费标准':
            from ..core.v4_bridge import load
            presentation = load('fee_display').current(source)
            if presentation and items[-1]['value']:
                items[-1].update(display_value=presentation['value'], display_note=presentation['note'], multiline=True)
        if template_name == '立案审批表' and spec['key'] == '立案审批日期':
            from ..core.v4_bridge import load
            presentation = load('intake_contract_date').presentation(source)
            if presentation and items[-1]['value']:
                items[-1].update(display_value=presentation['value'], display_note=presentation['note'])
    return {"template": template_name, "fields": items, "derived_output": dict(derived_output or {})}


def sanitize_preview_updates(template_name: str, values: dict[str, Any]) -> dict[str, Any]:
    if template_name not in SYSTEM_TEMPLATE_NAMES:
        raise ValueError(f"unknown template: {template_name}")
    values = dict(values or {})
    if template_name == '立案审批表' and '收案日期' in values:
        # Old clients may still use this form's former shared field key.
        values.setdefault('立案审批日期', values.pop('收案日期'))
    allowed = {item["key"] for item in TEMPLATE_FIELD_SPECS[template_name]}
    return {key: value for key, value in (values or {}).items() if key in allowed}


_CUSTOM_VALUE_KEY_RE = re.compile(r"^p\d{1,2}-b\d{1,2}-r\d{1,3}-c\d{1,2}$")
_STYLE_KEY_RE = re.compile(
    r"^(?:field:[^:]{1,100}|line:[^:]{1,100}:\d{1,2}|custom:p\d{1,2}-b\d{1,2}-r\d{1,3}-c\d{1,2})$"
)
_FONT_SIZE_RE = re.compile(r"^(?:8|9|10|10\.5|11|12|14|16|18|20|22|24)pt$")
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_ALLOWED_FONTS = {
    'SimSun, "Songti SC", "Noto Serif CJK SC", serif',
    'FangSong, STFangsong, "Noto Serif CJK SC", serif',
    'KaiTi, STKaiti, "Noto Serif CJK SC", serif',
    'Microsoft YaHei, "PingFang SC", "Noto Sans CJK SC", sans-serif',
}


def sanitize_preview_styles(template_name: str, styles: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Keep only supported per-cell formatting values for the browser preview."""
    if template_name not in SYSTEM_TEMPLATE_NAMES:
        raise ValueError(f"unknown template: {template_name}")

    clean: dict[str, dict[str, str]] = {}
    for style_key, raw_style in (styles or {}).items():
        if not isinstance(style_key, str) or not _STYLE_KEY_RE.fullmatch(style_key):
            continue
        if not isinstance(raw_style, dict):
            continue

        item: dict[str, str] = {}
        font_family = raw_style.get("fontFamily")
        if font_family in _ALLOWED_FONTS:
            item["fontFamily"] = font_family
        font_size = raw_style.get("fontSize")
        if isinstance(font_size, str) and _FONT_SIZE_RE.fullmatch(font_size):
            item["fontSize"] = font_size
        if raw_style.get("fontWeight") in {"normal", "bold"}:
            item["fontWeight"] = raw_style["fontWeight"]
        if raw_style.get("fontStyle") in {"normal", "italic"}:
            item["fontStyle"] = raw_style["fontStyle"]
        if raw_style.get("textDecoration") in {"none", "underline"}:
            item["textDecoration"] = raw_style["textDecoration"]
        if raw_style.get("textAlign") in {"left", "center", "right", "justify"}:
            item["textAlign"] = raw_style["textAlign"]
        color = raw_style.get("color")
        if isinstance(color, str) and _COLOR_RE.fullmatch(color):
            item["color"] = color.lower()
        if item:
            clean[style_key] = item
    return clean


def sanitize_preview_custom_values(template_name: str, values: dict[str, Any]) -> dict[str, str]:
    """Sanitize user-created text boxes addressed by stable layout coordinates."""
    if template_name not in SYSTEM_TEMPLATE_NAMES:
        raise ValueError(f"unknown template: {template_name}")
    clean: dict[str, str] = {}
    for key, value in (values or {}).items():
        if not isinstance(key, str) or not _CUSTOM_VALUE_KEY_RE.fullmatch(key):
            continue
        if value is None:
            clean[key] = ""
        elif isinstance(value, (str, int, float, bool)):
            clean[key] = str(value)[:5000]
    return clean
