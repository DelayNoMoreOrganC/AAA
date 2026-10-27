#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""字段后处理：案号、法院文书列表等"""

import re

# 中文案号：（年份）或 (年份) + 法院字号 + 类型 + 序号 + 号
CASE_NO_RE = re.compile(r"[（(]\d{4}[）)][^、，,；;\n\r]{2,48}?号")

# 模板占位符后附带的示例说明（档案卷宗等）
REFERENCE_FORMAT_TRAILING = re.compile(r"参考格式[：:\s].*$", re.DOTALL)

# 提示词中的范例案号（若原样填入则丢弃，改从 PDF 文本提取）
PROMPT_EXAMPLE_MARKERS = ("18549", "15469", "7816", "参考格式", "格式：", "格式:")

# 档案卷宗「法院收案号」仅允许：判决书诉讼案号 + 执行裁定书执行案号
LITIGATION_MARKERS = ("民初", "民终", "民再")
EXECUTION_EXCLUDE = ("执保", "执异", "执复", "执监", "执协", "民函", "仲")


# 「待X」占位符：LLM 可能产生各种变体，逐一枚举永远追不完。
# 用「明确集合 + 两字兜底正则」组合：集合覆盖已知 3~4 字变体，
# 正则 ^待.$ 只匹配两字占位（待查/待核/待补/待填/待证…），避免误伤真实词（待业人员等）。
_PLACEHOLDER_PHRASES = frozenset({
    "待确认", "待确定", "待查证", "待核实", "待补全", "待完善",
    "待识别", "待提供", "待说明", "待定稿", "待更新", "待录入",
    "待填写", "待核查", "待查验", "待补充", "待整理",
})
_PLACEHOLDER_RE = re.compile(r"^待.$")

# LLM 把字段说明/提取要求当作值返回时的特征
_REQUIREMENT_TEXT_PATTERNS = (
    "[从", "[仅", "[格式", "[必须", "[完整", "[优先", "[禁止",
    "提取", "提取落款", "从文档中", "从判决书", "从起诉状", "从委托代理合同",
    "从授权", "中提取", "填写", "格式要求", "字体格式", "行距",
    "如有二审", "禁止只填", "必须综合", "优先判决书", "sheet1", "Sheet1",
    "根据判决书", "匹配最相近",
)
_REQUIREMENT_PHRASES = (
    "委托代理合同中落款", "原告律师信息", "代理律师信息", "被告信息", "原告信息",
    "起诉状中起诉标的", "所有字体格式要求",
)


def is_placeholder_value(val: str) -> bool:
    """检测值是否是占位符（待确认/待确定/待查/无/未知/暂无/none 等），应留空。"""
    s = str(val or "").strip()
    if not s:
        return True
    low = s.lower()
    if low in ("无", "未知", "暂无", "none", "n/a", "na", "/", "-", "—"):
        return True
    if s in _PLACEHOLDER_PHRASES:
        return True
    # 两字「待X」占位兜底（待查/待核/待补/待填/待证/待定/待录…）
    if _PLACEHOLDER_RE.match(s):
        return True
    return False


def looks_like_requirement_text(val: str) -> bool:
    """检测值是否为字段说明/提取要求（非真实数据）。"""
    s = str(val or "").strip()
    if not s:
        return False
    for pat in _REQUIREMENT_TEXT_PATTERNS:
        if pat in s:
            return True
    for phrase in _REQUIREMENT_PHRASES:
        if phrase in s:
            return True
    if re.search(r"XXX{2,}", s):
        return True
    if re.search(r"从.{0,12}中提取", s):
        return True
    if len(s) > 60 and any(k in s for k in ("提取", "填写", "格式", "优先", "禁止", "必须")):
        return True
    return False


def is_valid_field_value(val: str) -> bool:
    """值有效：非空、非占位符、非字段说明文字。"""
    s = str(val or "").strip()
    if not s or is_placeholder_value(s):
        return False
    return not looks_like_requirement_text(s)


def extract_case_numbers_from_text(text: str) -> list:
    if not text:
        return []
    found = CASE_NO_RE.findall(text)
    out = []
    seen = set()
    for n in found:
        n = n.strip()
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _normalize_case_no_parens(s: str) -> str:
    s = (s or "").replace("(", "（").replace(")", "）")
    return re.sub(r"\s+", "", s)


def _classify_archive_case_no(case_no: str):
    """
    档案卷宗法院收案号分类。
    返回 'litigation' | 'execution' | None（排除）。
    """
    n = _normalize_case_no_parens((case_no or "").strip())
    if not n or len(n) < 8:
        return None
    if any(x in n for x in EXECUTION_EXCLUDE):
        return None
    if re.search(r"字第\s*号$", n) or "字第号" in n:
        return None
    if re.search(r"第\d{5,}号$", n) and "民" not in n and "执" not in n:
        return None

    if any(m in n for m in LITIGATION_MARKERS):
        return "litigation"

    # 执行案号：含「执」+ 数字，且非诉讼案号样式
    if re.search(r"执\s*\d", n) and not any(m in n for m in LITIGATION_MARKERS):
        return "execution"

    return None


def _dedupe_preserve_order(items):
    seen = set()
    out = []
    for x in items:
        key = _normalize_case_no_parens(x)
        if key in seen:
            continue
        seen.add(key)
        out.append(_normalize_case_no_parens(x))
    return out


def _court_code_from_case(case_no: str) -> str:
    """提取法院地区码，如 粤0604 -> 0604"""
    m = re.search(r"粤\s*0*(\d{4})", _normalize_case_no_parens(case_no))
    return m.group(1) if m else ""


def _pick_litigation_case_numbers(candidates, pdf_text: str):
    """多个诉讼案号时：保留民终；民初仅保留本案民事判决书主案号一条"""
    if not candidates:
        return []
    if len(candidates) == 1:
        return candidates

    pdf = pdf_text or ""
    ends, others = [], []
    for n in candidates:
        norm = _normalize_case_no_parens(n)
        if "民终" in norm:
            ends.append(n)
        else:
            others.append(n)

    if not others:
        return _dedupe_preserve_order(ends)

    scored = []
    for n in others:
        norm = _normalize_case_no_parens(n)
        score = 0
        for title in ("民事判决书", "判决书"):
            idx = pdf.find(title)
            if idx >= 0 and norm in pdf[idx : idx + 6000]:
                score += 30
                break
        for bad in ("参与分配", "另案", "查封公告", "拍卖", "分配方案"):
            idx = pdf.find(bad)
            if idx >= 0 and norm in pdf[max(0, idx - 120) : idx + 600]:
                score -= 25
        ym = re.search(r"[（(](\d{4})[）)]", norm)
        if ym:
            y = int(ym.group(1))
            if y <= 2020:
                score += 3
            elif y >= 2021:
                score -= 8
        scored.append((score, n))

    scored.sort(key=lambda x: (-x[0], x[1]))
    primary = [scored[0][1]] if scored else [others[0]]
    return _dedupe_preserve_order(ends + primary)


def _pick_execution_case_numbers(candidates, pdf_text: str, litigation_nums: list):
    """多个执行案号时，优先与本案判决法院一致、且出自终结/立案执行裁定书段落"""
    if not candidates:
        return []
    if len(candidates) == 1:
        return candidates

    lit_code = _court_code_from_case(litigation_nums[0]) if litigation_nums else ""
    scored = []
    pdf = pdf_text or ""

    for n in candidates:
        score = 0
        norm = _normalize_case_no_parens(n)
        if lit_code and lit_code in norm:
            score += 10
        # 终结本次执行 / 立案执行 裁定书中的案号优先
        for marker, bonus in (
            ("终结本次执行", 20),
            ("终结执行", 18),
            ("恢复执行", 12),
            ("执行裁定书", 8),
        ):
            idx = pdf.find(marker)
            if idx >= 0 and norm in pdf[max(0, idx - 80) : idx + 1200]:
                score += bonus
                break
        # 财产保全段落降权
        if "财产保全" in pdf and norm in pdf:
            idx = pdf.find("财产保全")
            if idx >= 0 and norm in pdf[max(0, idx - 80) : idx + 800]:
                score -= 15
        if "执保" in norm:
            score -= 50
        scored.append((score, n))

    scored.sort(key=lambda x: (-x[0], x[1]))
    best = scored[0][1]
    return [best] if best else [candidates[0]]


def _extract_from_pdf_sections(pdf_text: str):
    """按文书段落从 PDF 文本提取诉讼案号、执行案号"""
    if not pdf_text:
        return [], []

    text = pdf_text.replace("\r", "\n")
    lit, exe = [], []

    # 民事判决书段落
    for m in re.finditer(
        r"(民事判决书|判决书)(.{0,4000}?)(?=执行裁定书|裁定书|财产分配|受理案件|$)",
        text,
        re.DOTALL,
    ):
        chunk = m.group(0)
        if "民事裁定" in chunk[:30]:
            continue
        for n in extract_case_numbers_from_text(chunk):
            if _classify_archive_case_no(n) == "litigation":
                lit.append(n)

    if not lit:
        head = text[:8000]
        for n in extract_case_numbers_from_text(head):
            if _classify_archive_case_no(n) == "litigation":
                lit.append(n)

    # 执行裁定书（排除财产保全专段）
    for m in re.finditer(
        r"(执行裁定书|执行裁定)(.{0,3500}?)(?=执行裁定书|执行裁定|民事判决|财产分配|受理案件|$)",
        text,
        re.DOTALL,
    ):
        chunk = m.group(0)
        if "财产保全" in chunk[:400] or "执保" in chunk[:400]:
            continue
        for n in extract_case_numbers_from_text(chunk):
            if _classify_archive_case_no(n) == "execution":
                exe.append(n)

    if not exe:
        for m in re.finditer(
            r"(终结本次执行|终结执行|立案执行)(.{0,2500}?)",
            text,
            re.DOTALL,
        ):
            for n in extract_case_numbers_from_text(m.group(0)):
                if _classify_archive_case_no(n) == "execution":
                    exe.append(n)

    return _dedupe_preserve_order(lit), _dedupe_preserve_order(exe)


def filter_archive_case_numbers(numbers, pdf_text: str = ""):
    """
    档案卷宗法院收案号：仅保留判决书诉讼案号（民初/民终/民再）+
    执行裁定书执行案号（不含执保等）。
    """
    lit, exe = [], []
    for n in numbers or []:
        kind = _classify_archive_case_no(n)
        if kind == "litigation":
            lit.append(n)
        elif kind == "execution":
            exe.append(n)

    lit = _dedupe_preserve_order(lit)
    lit = _pick_litigation_case_numbers(lit, pdf_text)
    exe = _dedupe_preserve_order(exe)
    exe = _pick_execution_case_numbers(exe, pdf_text, lit)

    return lit + exe


def strip_template_reference_suffix(text: str) -> str:
    """去掉 Word 模板中占位符后的「参考格式：示例案号」等固定说明"""
    if not text:
        return text
    had_cr = "\r" in text
    s = text.replace("\x07", "")
    s = REFERENCE_FORMAT_TRAILING.sub("", s)
    s = re.sub(r"格式[：:\s]*$", "", s)
    s = s.rstrip()
    if had_cr and not s.endswith("\r"):
        s += "\r"
    return s


CASE_TYPE_NO_MARKERS = {
    "criminal": ("刑初", "刑终", "刑再", "刑申", "刑抗", "刑核", "刑附民"),
    "admin": ("行初", "行终", "行再", "行申", "行赔", "行非"),
}


def _sanitize_typed_case_no(value: str, pdf_text: str, case_type: str) -> str:
    markers = CASE_TYPE_NO_MARKERS.get(case_type, ())
    candidates = extract_case_numbers_from_text(value or "")
    if not candidates and pdf_text:
        candidates = extract_case_numbers_from_text((pdf_text or "")[:16000])
    if markers:
        candidates = [n for n in candidates if any(marker in n for marker in markers)]
    candidates = [n for n in candidates if not any(x in n for x in EXECUTION_EXCLUDE)]
    return "、".join(_dedupe_preserve_order(candidates)[:4])


def sanitize_court_case_no(value: str, pdf_text: str = "", case_type: str = "civil") -> str:
    """
    档案卷宗等使用的法院收案号：仅判决书诉讼案号 + 执行裁定书执行案号。
    不从 PDF 全文捞取所有案号，避免另案/保全/律所函号等误入。
    """
    raw = strip_template_reference_suffix((value or "").strip())
    raw = re.sub(r"^参考格式[：:\s]*", "", raw)
    raw = re.sub(r"^格式[：:\s]*", "", raw)

    if case_type != "civil":
        return _sanitize_typed_case_no(raw, pdf_text, case_type)

    from_value = extract_case_numbers_from_text(raw)
    looks_like_prompt_example = any(m in (value or "") for m in PROMPT_EXAMPLE_MARKERS)

    if looks_like_prompt_example:
        from_value = []

    filtered = filter_archive_case_numbers(from_value, pdf_text)

    if not filtered and pdf_text:
        lit, exe = _extract_from_pdf_sections(pdf_text)
        lit = _pick_litigation_case_numbers(lit, pdf_text)
        exe = _pick_execution_case_numbers(exe, pdf_text, lit)
        filtered = lit + exe

    return "、".join(filtered)


def sanitize_field_value(value) -> str:
    """去掉 LLM 返回值中的【】占位符残留、参考格式说明、零宽字符"""
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    s = re.sub(r"【[^】]*】", "", s)
    s = re.sub(r"参考格式[：:\s][^\n\r]*", "", s)
    s = re.sub(r"^格式[：:\s]*", "", s)
    s = re.sub(r"[\u200b-\u200d\ufeff]", "", s)
    return s.strip()


def sanitize_all_field_values(fields: dict) -> dict:
    if not fields:
        return fields
    out = {}
    for k, v in fields.items():
        if isinstance(v, str):
            s = sanitize_field_value(v)
            if not is_valid_field_value(s):
                s = ""
            out[k] = s
        elif isinstance(v, (list, tuple)):
            out[k] = [sanitize_field_value(x) for x in v if is_valid_field_value(str(x))]
        else:
            out[k] = v
    return out


def parse_litigation_parties(text: str) -> tuple[str, str]:
    """从「原告：A，被告：B」或「A诉B…一案」提取原、被告姓名（不含标签）。"""
    s = (text or "").strip()
    if not s:
        return "", ""

    plaintiff = ""
    defendant = ""

    m = re.search(r"原告[：:为]?\s*([^，,;；\n]+?)(?=[，,;；\n]|被告|$)", s)
    if m:
        plaintiff = m.group(1).strip()
    m = re.search(r"被告[：:为]?\s*([^，,;；\n]+)", s)
    if m:
        defendant = m.group(1).strip()

    if not plaintiff or not defendant:
        m = re.search(r"(.+?)诉(.+?)(?:一案|纠纷案|案件)", s)
        if m:
            if not plaintiff:
                plaintiff = m.group(1).strip()
            if not defendant:
                rest = m.group(2).strip()
                defendant = re.sub(
                    r"(借款|买卖|租赁|合同|侵权|劳动|服务|信用卡)?纠纷$",
                    "",
                    rest,
                ).strip() or rest

    for label, val in (("原告", plaintiff), ("被告", defendant)):
        if val:
            val = re.sub(rf"^{label}[：:为]?\s*", "", val).strip()
        if label == "原告":
            plaintiff = val
        else:
            defendant = val

    return plaintiff, defendant


def _clean_party_name(name: str) -> str:
    n = (name or "").strip()
    n = re.sub(r"^(原告|被告)[：:为]?\s*", "", n)
    return n.strip()


def _normalize_defendant_name(name: str) -> str:
    """个人被告常带性别/出生信息，只保留姓名或公司名。"""
    n = _clean_party_name(name)
    if not n:
        return n
    if re.search(r"[，,].*(男|女|出生|身份证|住址)", n):
        n = re.split(r"[，,]", n, maxsplit=1)[0].strip()
    if len(n) > 40:
        m2 = re.match(r"^([^，,;；\d]{2,20})", n)
        if m2:
            n = m2.group(1).strip()
    return n


def normalize_plaintiff_lawyer(text: str) -> str:
    """从「原告律师A、被告律师B」提取本案承办律师（原告侧）。"""
    s = (text or "").strip()
    if not s or is_placeholder_value(s):
        return ""
    m = re.search(r"原告律师[：:]?\s*([^、,，;；\n]+)", s)
    if m:
        return m.group(1).strip()
    if "被告律师" in s:
        head = s.split("被告律师", 1)[0]
        head = re.sub(r"^原告律师[：:]?\s*", "", head).strip(" 、，,;；")
        if head:
            return head
    return re.sub(r"^原告律师[：:]?\s*", "", s).strip()


def enrich_party_fields(fields: dict, case_type=None, *, strict_evidence=False) -> dict:
    """Normalize explicit roles without inventing a party or document source.

    A client need not be a plaintiff; a neutral opposing party need not be a
    defendant. Legacy form-slot equivalence belongs to field_mapping, not to
    these extracted facts. Document-specific fields stay document-specific.
    """
    if not fields:
        return fields
    if strict_evidence:
        # The workstation's agents already validate individual values against
        # their source clauses. A party's court role does not establish the
        # represented side, and a lawyer named in a judgment may be opposing
        # counsel. Preserve explicit values, including deliberate blanks and
        # contradictory evidence, for the existing review workflow.
        return dict(fields)
    m = dict(fields)
    case_type = case_type or m.get("案件类别")
    litigation = case_type in (None, "", "civil", "admin", "民事", "行政")

    plaintiff = _clean_party_name(
        m.get("判决书中的原告") or m.get("起诉状中的原告") or m.get("原告") or ""
    )
    defendant = _normalize_defendant_name(
        m.get("判决书中的被告")
        or m.get("起诉状中的被告")
        or m.get("被告")
        or ""
    )

    for raw in (m.get("当事人"), m.get("案件或项目名称")) if litigation else ():
        if not raw:
            continue
        pl, df = parse_litigation_parties(str(raw))
        if pl and not plaintiff:
            plaintiff = pl
        if df and not defendant:
            defendant = df

    # Clean each supplied document field independently. Never overwrite a
    # complaint party with a later judgment party or manufacture the other key.
    for key in ("判决书中的原告", "起诉状中的原告"):
        if m.get(key):
            m[key] = _clean_party_name(m[key])
    for key in ("判决书中的被告", "起诉状中的被告"):
        if m.get(key):
            m[key] = _normalize_defendant_name(m[key])
    if plaintiff:
        m.setdefault("原告", plaintiff)
    if defendant:
        defendant = _normalize_defendant_name(defendant)
        m.setdefault("对方当事人", defendant)
        m.setdefault("被告", defendant)

    client = _clean_party_name(m.get("委托人") or m.get("委托人名称") or "")
    if client:
        m["委托人"] = client
        m.setdefault("委托人名称", client)
        if case_type in ("arbitration", "consultation", "nonlit", "counsel", "仲裁", "咨询代书", "非诉", "法律顾问"):
            m.setdefault("当事人", client)

    for key in ("判决书上代理律师", "判决书原告的委托诉讼代理人"):
        value = m.get(key)
        if isinstance(value, str) and value.strip() and not is_placeholder_value(value):
            m[key] = normalize_plaintiff_lawyer(value) or value

    for src in ("判决书上代理律师", "判决书原告的委托诉讼代理人", "代理律师", "承办律师"):
        v = (m.get(src) or "").strip()
        if v and not is_placeholder_value(v):
            clean = normalize_plaintiff_lawyer(v) or v
            m.setdefault("承办律师", clean)
            break

    # 所有字段：没把握（待确认/说明文字/提取要求）一律留空，不写入模板
    for k in list(m.keys()):
        v = str(m.get(k) or "").strip()
        if is_placeholder_value(v) or looks_like_requirement_text(v):
            m[k] = ""

    return m


def parse_court_document_list(text: str) -> list:
    """
    将法院文件清单拆成不重复的单项文书名称（用于送达材料清单逐行填写）。
    """
    if not text:
        return []
    s = (text or "").strip()
    s = re.sub(r"^参考[^：:]*[：:\s]*", "", s)
    s = re.sub(r"页码识别|可以的话", "", s)

    parts = re.split(r"[、，,;；\n\r]+", s)
    out = []
    seen = set()
    for p in parts:
        p = p.strip()
        if not p:
            continue
        p = re.sub(r"\s*\d+\s*页\s*$", "", p).strip()
        p = re.sub(r"^[\d\.、\s]+", "", p).strip()
        if len(p) < 2:
            continue
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out
