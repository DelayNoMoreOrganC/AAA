#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""结案小结 / 审（办）结果：按法律实务综合判决主文与执行结果，控制字数

实务结构（律所归档常用）：
  1. 判决主文：谁向谁承担何种给付/连带责任（不写执行、终本）
  2. 执行过程：立案查控 → 特殊终结事由（破产/和解/撤回等）或常规终本
"""

import re

CASE_OUTCOME_MAX_LEN = 150
# Version the workstation's evidence/classification snapshot as a whole.
# New title rules must not silently reuse an older automatic classification.
STRICT_EVIDENCE_VERSION = "strict-fields-v19"

# These are distinct saved facts. In the workstation an accepted quotation or
# an explicit human value must not be replaced by a longer alias, shortened to
# fit a template, or supplemented by unreviewed source text.
OUTCOME_FIELDS = ("结案小结", "审（办）结果", "审办结果")


def preserve_accepted_outcomes(fields: dict) -> dict:
    """Keep only the outcome values already accepted by the calling workflow.

    The caller supplies evidence-validated extraction results or saved human
    values. This function deliberately accepts no PDF text or document units:
    a classification, a requested remedy, and a quoted judgment are not proof
    of this case's disposition or enforcement result. Missing results remain
    missing, and explicit blanks and conflicting aliases remain independent.
    Length/layout checks belong to the renderer and must never silently remove
    an obligation, amount, condition, or negation from an accepted fact.
    """
    result = dict(fields or {})
    if not any(isinstance(result.get(key), str) and result[key].strip() for key in OUTCOME_FIELDS):
        result["_outcome_warnings"] = [
            "尚无已采纳的审办结果或结案小结；未从文书类别、诉请或执行申请推断处理结果，请核对后补充"
        ]
    return result

# 执行结果类型（按实务优先级：特殊终结事由优先于「无财产终本」）
OUTCOME_TYPE_RULES = (
    ("bankruptcy", ("破产", "移送破产", "破产清算", "破产重整", "受理破产", "执转破")),
    ("settlement", ("执行和解", "和解协议", "和解")),
    ("withdraw", ("撤回执行", "撤回申请", "准许撤回")),
    ("participation", ("参与分配",)),
    ("denial", ("不予执行",)),
    ("suspension", ("中止执行",)),
    ("debt_cert", ("债权凭证",)),
    ("property_offset", ("以物抵债",)),
    ("zhiben", ("终结本次执行", "终本", "暂无其他可供执行", "无其他可供执行财产")),
    ("completed", ("执行完毕", "履行完毕", "自动履行", "清偿完毕", "执行终结")),
)

SPECIAL_OUTCOME_TYPES = frozenset({
    "bankruptcy", "settlement", "withdraw", "participation",
    "denial", "suspension", "debt_cert", "property_offset",
})

SPECIAL_EXEC_MARKERS = tuple(
    m for _t, markers in OUTCOME_TYPE_RULES if _t in SPECIAL_OUTCOME_TYPES for m in markers
)

EXEC_MARKERS = (
    "执行",
    "终本",
    "终结本次",
    "拍卖",
    "查封",
    "扣划",
    "冻结",
    "可供执行",
    "恢复执行",
    "立案执行",
) + SPECIAL_EXEC_MARKERS

# 判决段与执行段的分界标记
JUDGMENT_EXEC_SPLIT_MARKERS = (
    "执行过程中",
    "执行中被执行人",
    "执行中，",
    "执行中",
    "其后，",
    "申请执行人申请撤回",
    "申请执行人撤回",
    "本院立案执行",
    "立案执行",
)

OUTCOME_REFERENCE_SHORT = (
    "判决被告何锦刚偿还贷款本金688204.93元及利息，支付律师代理费3000元，"
    "其他被告承担连带清偿责任。执行过程中拍卖部分财产，"
    "但因被执行人无其他可供执行财产，终结本次执行程序。"
)


def _normalize_spaces(text: str) -> str:
    s = re.sub(r"[ \t\r\n]+", " ", (text or "").strip())
    s = re.sub(r" +", " ", s)
    s = re.sub(r"(?<=[\u4e00-\u9fff]) +(?=[\u4e00-\u9fff])", "", s)
    s = re.sub(r"(?<=[0-9]) +(?=[元年月日%])", "", s)
    return s


def _normalize_court_terms(text: str) -> str:
    """将执行裁定书原文中的法院自称「本院」改为第三人称「法院」。

    律所归档以第三人称转述法院行为，摘抄执行裁定书原文时不得保留「本院」。
    """
    return (text or "").replace("本院", "法院")


def truncate_chinese(text: str, max_len: int = CASE_OUTCOME_MAX_LEN) -> str:
    """按字符数截断（中文按字计）"""
    s = _normalize_spaces(text)
    if len(s) <= max_len:
        return s
    cut = s[:max_len]
    for sep in ("。", "；", "，", "、"):
        idx = cut.rfind(sep)
        if idx > max_len * 0.6:
            return cut[: idx + 1]
    return cut.rstrip("，、；") + "。"


def classify_execution_outcome(text: str) -> str:
    """识别执行结果类型（破产等特殊情况优先于常规终本）。"""
    t = text or ""
    for name, markers in OUTCOME_TYPE_RULES:
        if name == "completed":
            # 「未履行完毕」「尚未执行完毕」并不表示执行完毕。
            for marker in markers:
                start = 0
                while True:
                    idx = t.find(marker, start)
                    if idx < 0:
                        break
                    prefix = t[max(0, idx - 4):idx]
                    if not any(neg in prefix for neg in ("未", "尚未", "没有", "并未")):
                        return name
                    start = idx + len(marker)
            continue
        if any(m in t for m in markers):
            return name
    if "执行" in t:
        return "generic"
    return ""


def _outcome_exec_score(text: str) -> int:
    t = text or ""
    score = sum(1 for m in EXEC_MARKERS if m in t)
    # 特殊终结事由在归档中更重要，加权
    if classify_execution_outcome(t) in SPECIAL_OUTCOME_TYPES:
        score += 3
    return score


def pick_best_outcome_text(fields: dict) -> str:
    """优先含执行/终本表述的候选，避免仅判决书内容入选"""
    candidates = []
    for key in ("结案小结", "审（办）结果", "审办结果"):
        v = (fields.get(key) or "").strip()
        if v:
            candidates.append(v)
    if not candidates:
        return ""
    return max(candidates, key=lambda t: (_outcome_exec_score(t) * 200 + len(t)))


def _has_enforcement_measures(text: str) -> bool:
    return any(k in (text or "") for k in ("查封", "冻结", "扣划", "拍卖", "变卖", "查控"))


def _strip_exec_prefix(body: str) -> str:
    """去掉片段开头的「执行过程中」等冗余前缀，便于拼接。"""
    s = (body or "").strip()
    for prefix in (
        "本案执行过程中，",
        "本院执行过程中，",
        "执行过程中，",
        "执行过程中",
        "执行中，",
        "执行阶段，",
    ):
        if s.startswith(prefix):
            return s[len(prefix) :].lstrip("，")
    return s


def _strip_execution_from_judgment(j: str) -> str:
    """判决主文段不应夹带执行/终本表述（实务上两段分开写）。"""
    s = _normalize_spaces(j)
    for marker in JUDGMENT_EXEC_SPLIT_MARKERS + ("终结本次", "裁定终结"):
        idx = s.find(marker)
        if idx > 6:
            s = s[:idx].rstrip("。；，")
    return s


_DECISION_MARKERS = (
    ("判决如下", "judgment"), ("裁定如下", "ruling"),
    ("调解协议内容如下", "mediation"), ("调解如下", "mediation"),
    ("裁判结果如下", ""),
)
_DECISION_PREFIXES = {"judgment": "法院判决", "ruling": "法院裁定", "mediation": "经调解"}


def _decision_kind(text: str, doc_type: str = "") -> str:
    """文书性质来自标题、明示主文或 unit 类型，不从撤诉等事项推定。"""
    raw = text or ""
    # Restrict title detection to actual heading lines, not cited documents in
    # reasoning (e.g. an original judgment quoted inside a later ruling).
    for line in raw.splitlines()[:12]:
        heading = re.sub(r"\s+", "", line)
        title = re.match(r"^(?:[\u4e00-\u9fff]{0,30}法院)?(?:民事|刑事|行政|执行|国家赔偿|赔偿)?(判决|裁定|调解)书(?:$|[（(…])", heading)
        if title:
            return {"判决": "judgment", "裁定": "ruling", "调解": "mediation"}[title.group(1)]
    normalized = _normalize_court_terms(_normalize_spaces(raw))
    for kind, prefix in _DECISION_PREFIXES.items():
        if normalized.startswith(prefix):
            return kind
    if normalized.startswith("裁定"):
        return "ruling"
    matches = [(raw.find(marker), kind) for marker, kind in _DECISION_MARKERS if kind and marker in raw]
    if matches:
        return min(matches)[1]
    return doc_type if doc_type in _DECISION_PREFIXES else "judgment"


def _polish_judgment_clause(j: str, doc_type: str = "") -> str:
    """规范裁判主文起句，保留判决、裁定或调解的文书性质。"""
    kind = _decision_kind(j, doc_type)
    s = _normalize_court_terms(_strip_execution_from_judgment(j)).rstrip("。；，")
    if not s:
        return ""
    s = s.lstrip("：:，。； ")
    s = re.sub(r"^[一二三四五六七八九十0-9]+[、.．]\s*", "", s)
    s = re.sub(r"(?:应)?于?本判决发生法律效力之日起十日内", "", s)
    prefix = _DECISION_PREFIXES[kind]
    if kind != "judgment":
        if s.startswith(prefix):
            return s
        for marker, marker_kind in _DECISION_MARKERS:
            if marker_kind == kind and s.startswith(marker):
                s = s[len(marker):].lstrip("：:， ")
                break
        if kind == "ruling" and s.startswith("裁定"):
            return "法院" + s
        if kind == "mediation" and s.startswith("调解"):
            s = s[2:].lstrip("：:， ")
        return prefix + s
    if s.startswith("判决") and not s.startswith("法院判决"):
        s = "法院" + s
    elif not s.startswith("法院判决"):
        m = re.search(r"法院判决", s)
        if m:
            s = s[m.start() :]
        else:
            s = "法院判决" + s
    return s


def _split_judgment_execution(text: str) -> tuple:
    """将已有综合表述拆为判决段 + 执行段。"""
    s = _normalize_spaces(text)
    for marker in JUDGMENT_EXEC_SPLIT_MARKERS:
        idx = s.find(marker)
        if idx > 6:
            return s[:idx].rstrip("。；，"), s[idx:].lstrip("，")
    return s, ""


def format_execution_for_practice(blurb: str, outcome_type: str = "", max_len: int = 88) -> str:
    """摘录执行原文，类型仅用于定位，不据关键词补写履行、受偿或裁定事实。

    「参与分配」「和解」「拍卖」既可能是事实，也可能是申请、计划或否定
    表述。因此保留完整语句及其限定词；篇幅不足时留待人工核对，不将
    一段残缺语句补成固定的法律结果模板。
    """
    raw = _normalize_court_terms(_strip_exec_prefix(_normalize_spaces(blurb))).rstrip("。；，")
    if not raw:
        return ""
    if len(raw) + 1 <= max_len:
        return raw + "。"

    # 只抽完整句/分号段，不按逗号截断，避免丢掉「但尚未履行」等后半句。
    # 原句太长时不输出不完整事实；detect_outcome_warnings 会提示执行信息缺失。
    markers = dict(OUTCOME_TYPE_RULES).get(outcome_type, ()) or EXEC_MARKERS
    sentences = [s.strip() for s in re.split(r"[。；]", raw) if s.strip()]
    candidates = [
        (index, sentence)
        for index, sentence in enumerate(sentences)
        if any(marker in sentence for marker in markers)
    ]
    selected = []
    used = 0
    for index, sentence in candidates:
        if used + len(sentence) + 1 <= max_len:
            selected.append((index, sentence))
            used += len(sentence) + 1
    return "。".join(sentence for _, sentence in selected) + "。" if selected else ""


def _pick_execution_connector(judgment: str, outcome_type: str) -> str:
    """按执行结果类型选择判决段与执行段之间的衔接词。"""
    if outcome_type == "withdraw":
        return ""  # 撤回执行为独立句，实务上常直接接在判决后
    if outcome_type in SPECIAL_OUTCOME_TYPES:
        if any(x in judgment for x in ("执行过程", "执行中", "立案执行", "查封", "拍卖", "查控")):
            return "其后，"
        return "执行过程中，"
    return "执行过程中，"


def synthesize_outcome_narrative(
    judgment_part: str, execution_part: str, max_len: int = CASE_OUTCOME_MAX_LEN
) -> str:
    """
    将判决书与执行裁定书分路提取的片段合成为一段连贯表述。
    结构：判决主文 + 执行过程/终结事由（实务两段式）。
    """
    j = _polish_judgment_clause(judgment_part)
    e_type = classify_execution_outcome(execution_part)
    e = format_execution_for_practice(execution_part, e_type)
    e_body = _strip_exec_prefix(e).rstrip("。；，")

    if not j and not e_body:
        return ""
    if not j:
        return truncate_chinese(_normalize_court_terms(e), max_len)
    if not e_body:
        return truncate_chinese(j + "。", max_len)
    if e_body in j or j in e_body:
        return truncate_chinese(
            _normalize_court_terms((j if len(j) >= len(e_body) else e_body) + "。"),
            max_len,
        )

    if not j.endswith(("。", "；")):
        j = j + "。"

    connector = _pick_execution_connector(j, e_type)
    # 为执行段预留篇幅。判决主文很长时，不能在最终 150 字截断时把执行结论整体挤掉。
    j = re.sub(r"（[^）]{12,}）", "", j)
    reserve = len(connector) + len(e_body) + 1
    judgment_limit = max(40, max_len - reserve - 1)
    if len(j) > judgment_limit:
        j = truncate_chinese(j, judgment_limit)
        if not j.endswith(("。", "；")):
            j += "。"
    if connector:
        if e_body.startswith(("因", "经", "后", "但", "遂", "故", "现", "已", "本院")):
            merged = j + connector + e_body + "。"
        else:
            merged = j + connector + e_body + "。"
    else:
        merged = j + e_body + "。"

    merged = merged.replace("。。", "。").replace("，。", "。")
    return truncate_chinese(_normalize_court_terms(merged), max_len)


def extract_execution_blurb(pdf_text: str, max_chars: int = 600) -> str:
    """从 OCR 全文截取执行裁定/终本段落（LLM 漏读时补全）"""
    if not pdf_text:
        return ""
    text = pdf_text.replace("\r", "\n")
    # 若存在特殊终结事由，优先抽取该段，避免只抓到「无财产终本」而漏破产等
    special = extract_special_execution_blurb(text, max_chars=max_chars)
    if special and classify_execution_outcome(special) in SPECIAL_OUTCOME_TYPES:
        return special

    patterns = (
        r"执行裁定书[\s\S]{0,4000}?终结本次执行[\s\S]{0,1200}?[。；]",
        r"终结本次执行程序[\s\S]{0,1500}?[。；]",
        r"执行裁定书[\s\S]{0,3000}?[。；]",
        r"恢复执行[\s\S]{0,2000}?[。；]",
    )
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            blurb = _source_sentence_fragment(text, m.start(), m.end())
            if len(blurb) > 30:
                return blurb
    idx = text.find("执行裁定书")
    if idx < 0:
        idx = text.find("终结本次执行")
    if idx >= 0:
        return _source_sentence_fragment(text, idx, idx + max_chars)
    return ""


def _source_sentence_fragment(text: str, start: int, end: int) -> str:
    """保留匹配词所在句的前后文，不能丢失「未/拟/申请」或句末转折。"""
    # OCR line wrapping is not a sentence boundary: "尚未\n达成和解"
    # must never become an affirmative "达成和解" excerpt.
    start = max(text.rfind(sep, 0, start) for sep in ("。", "；")) + 1
    ends = [text.find(sep, end) for sep in ("。", "；")]
    if end > 0 and text[end - 1:end] in ("。", "；"):
        stop = end
    else:
        stop = min((pos + 1 for pos in ends if pos >= 0), default=len(text))
    return _normalize_spaces(text[start:stop])


SPECIAL_EXEC_PATTERNS = (
    r"(?:裁定)?受理[^。；\n]{0,40}破产[\s\S]{0,300}?[。；]",
    r"移送破产审查[\s\S]{0,200}?[。；]",
    r"(?:进入|宣告|裁定)[^。；\n]{0,20}破产[\s\S]{0,300}?[。；]",
    r"[^。；\n]{0,30}破产[\s\S]{0,300}?(?:终结|移送|受理|清算|重整)[\s\S]{0,150}?[。；]",
    r"参与分配[\s\S]{0,300}?[。；]",
    r"(?:达成)?执行和解[\s\S]{0,300}?[。；]",
    r"撤回执行(?:申请)?[\s\S]{0,200}?[。；]",
    r"裁定不予执行[\s\S]{0,200}?[。；]",
    r"中止执行[\s\S]{0,200}?[。；]",
    r"(?:发放|出具)[^。；\n]{0,10}债权凭证[\s\S]{0,150}?[。；]",
    r"以物抵债[\s\S]{0,200}?[。；]",
)


def extract_special_execution_blurb(pdf_text: str, max_chars: int = 400) -> str:
    """从 OCR 全文截取「执行特殊情况」段落。"""
    if not pdf_text:
        return ""
    text = pdf_text.replace("\r", "\n")
    for pat in SPECIAL_EXEC_PATTERNS:
        m = re.search(pat, text)
        if m:
            blurb = _source_sentence_fragment(text, m.start(), m.end())
            if len(blurb) > 8:
                return blurb
    for name, markers in OUTCOME_TYPE_RULES:
        if name not in SPECIAL_OUTCOME_TYPES:
            continue
        for kw in markers:
            idx = text.find(kw)
            if idx >= 0:
                return _source_sentence_fragment(text, idx, idx + max_chars)
    return ""


def _compress_exec_sentence(exec_blurb: str, max_len: int = 85) -> str:
    """兼容旧调用：压缩后走实务格式化。"""
    return format_execution_for_practice(exec_blurb, max_len=max_len)


def _set_outcome(fields: dict, text: str) -> dict:
    fields["结案小结"] = text
    fields["审（办）结果"] = text
    fields["审办结果"] = text
    return fields


def _text_covers_outcome_type(text: str, outcome_type: str) -> bool:
    """判断现有表述是否已覆盖该执行结果类型。"""
    if not text or not outcome_type:
        return False
    detected = classify_execution_outcome(text)
    if detected == outcome_type:
        return True
    if outcome_type == "bankruptcy" and "破产" in text:
        return True
    if outcome_type == "settlement" and "和解" in text:
        return True
    if outcome_type == "withdraw" and "撤回" in text:
        return True
    return False


def _ensure_special_execution(m: dict, pdf_text: str) -> dict:
    """执行特殊情况兜底：破产/和解/撤回等须写入，且优先于「无财产终本」。"""
    if not pdf_text:
        return m

    pdf_type = classify_execution_outcome(pdf_text)
    if pdf_type not in SPECIAL_OUTCOME_TYPES:
        return m

    text = pick_best_outcome_text(m) or ""
    if _text_covers_outcome_type(text, pdf_type):
        return m

    blurb = extract_special_execution_blurb(pdf_text)
    if not blurb:
        return m

    j_part, e_part = _split_judgment_execution(text)
    j_part = _polish_judgment_clause(j_part) if j_part else ""
    special_clause = format_execution_for_practice(blurb, pdf_type)

    if j_part and e_part and not _text_covers_outcome_type(e_part, pdf_type):
        # 已有常规执行段但缺特殊事由：用「其后，」补写
        e_body = _strip_exec_prefix(special_clause).rstrip("。；，")
        connector = "其后，" if "执行" in e_part or _has_enforcement_measures(e_part) else "执行过程中，"
        merged = f"{j_part}。{e_part.rstrip('。；，')}。{connector}{e_body}。"
    elif j_part:
        merged = synthesize_outcome_narrative(j_part, special_clause)
    else:
        merged = special_clause

    merged = merged.replace("。。", "。").replace("，。", "。")
    merged = truncate_chinese(merged, CASE_OUTCOME_MAX_LEN)
    return _set_outcome(m, merged)


def extract_judgment_operative(text: str, doc_type: str = "") -> str:
    """从裁判文书抽取主文，并保留原文明示的判决/裁定/调解性质。"""
    if not text:
        return ""
    raw = text.replace("\r", "\n")
    kind = _decision_kind(raw, doc_type)
    matches = [(raw.find(marker), marker, marker_kind) for marker, marker_kind in _DECISION_MARKERS if marker in raw]
    if not matches:
        return ""
    # A ruling can quote an earlier judgment; prefer its own operative marker.
    matching_kind = [entry for entry in matches if entry[2] == kind]
    idx, marker, marker_kind = min(matching_kind or matches)
    start = idx + len(marker)
    if marker_kind:
        kind = marker_kind
    rest = raw[start:]
    end = len(rest)
    for em in (
        "如不服本判决", "如不服本裁定", "如不服", "审判员", "审判长",
        "书记员", "本判决为终审判决", "本调解书经", "本案受理费", "案件受理费",
    ):
        idx = rest.find(em)
        if idx > 0:
            end = min(end, idx)
    body = _normalize_spaces(rest[:end])
    if len(body) < 6:
        return ""
    return _polish_judgment_clause(body, doc_type=kind)


def collect_units_text(units, page_texts_by_path, target_seqs) -> str:
    """按 catalog_seq 收集 unit 页文本（V6：seq14 判决 / seq15 执行）。"""
    if not units or not page_texts_by_path:
        return ""
    target = set(target_seqs or [])
    chunks = []
    for u in units:
        seq = getattr(u, "catalog_seq", None)
        if seq not in target:
            continue
        path = getattr(u, "source_path", "") or ""
        pages = page_texts_by_path.get(path) or []
        sp = getattr(u, "start_page", None)
        ep = getattr(u, "end_page", None)
        if pages and sp is not None and ep is not None:
            chunk = "\n".join(
                (pages[i] or "").strip()
                for i in range(sp, min(ep, len(pages) - 1) + 1)
            ).strip()
            if chunk:
                chunks.append(chunk)
    return "\n\n".join(chunks)


def has_execution_units(units=None, pdf_text: str = "") -> bool:
    """是否存在执行文书 unit（seq15 或 doc_type=execution）。"""
    if units:
        for u in units:
            if getattr(u, "catalog_seq", None) == 15:
                return True
            if getattr(u, "doc_type", "") == "execution":
                return True
    return False


def build_outcome_from_units(fields: dict, units, page_texts_by_path, pdf_text: str = "") -> dict:
    """V6：规则优先 — 从 seq14/15 unit 文本合成审办结果，覆盖 LLM 乱归纳。"""
    if not fields:
        fields = {}
    m = dict(fields)
    e_raw = collect_units_text(units, page_texts_by_path, {15})

    # seq14 includes rulings, judgments and mediation documents. Do not flatten
    # different units before determining which kind each operative clause is.
    parts = []
    for unit in units or []:
        if getattr(unit, "catalog_seq", None) != 14:
            continue
        raw = collect_units_text([unit], page_texts_by_path, {14})
        if not raw:
            continue
        kind = _decision_kind(raw, getattr(unit, "doc_type", ""))
        part = extract_judgment_operative(raw, doc_type=kind) or _polish_judgment_clause(raw[:1200], doc_type=kind)
        if part:
            parts.append(part.rstrip("。；，"))
    j_part = "。".join(parts)

    e_clause = ""
    if e_raw:
        e_type = classify_execution_outcome(e_raw)
        e_clause = format_execution_for_practice(e_raw, e_type)

    if not j_part and not e_clause:
        return m

    if j_part and e_clause:
        merged = synthesize_outcome_narrative(j_part, e_clause)
    elif j_part:
        merged = truncate_chinese(j_part if j_part.endswith("。") else j_part + "。")
    else:
        merged = truncate_chinese(e_clause)

    if merged:
        return _set_outcome(m, merged)
    return m


def detect_outcome_warnings(fields: dict, units=None, pdf_text: str = "") -> list:
    """低置信度预警（供 V5 Web 展示）。"""
    warnings = []
    text = pick_best_outcome_text(fields)
    if not text:
        warnings.append("未提取到审办结果/结案小结，请人工填写")
        return warnings
    if not text.startswith(("法院判决", "法院裁定", "经调解")):
        warnings.append("审办结果未以「法院判决」等规范起句，建议核对")
    has_exec = has_execution_units(units, pdf_text)
    if ("终结本次" in text or "执行完毕" in text) and not has_exec:
        warnings.append("表述含执行终结，但卷内未识别到执行文书（seq15），请核对")
    if has_exec and "执行" not in text and "终本" not in text:
        warnings.append("卷内已有执行文书，但审办结果未写执行情况，建议补充")
    return warnings


def _ensure_general_execution(m: dict, pdf_text: str, units=None) -> dict:
    """常规终本兜底（仅在没有特殊终结事由时使用）。"""
    text = pick_best_outcome_text(m)
    if not text:
        return m
    if _outcome_exec_score(text) >= 2:
        return m
    if not has_execution_units(units, pdf_text):
        return m
    if not pdf_text:
        return m

    pdf_type = classify_execution_outcome(pdf_text)
    # 全文含破产/和解等特殊事由时，不用「无财产终本」兜底，避免写错终结原因
    if pdf_type in SPECIAL_OUTCOME_TYPES:
        return m
    if "执行裁定" not in pdf_text and "终结本次" not in pdf_text and "执" not in pdf_text:
        return m

    exec_blurb = extract_execution_blurb(pdf_text)
    if not exec_blurb:
        return m

    j_part, _ = _split_judgment_execution(text)
    j_part = _polish_judgment_clause(j_part) if j_part else text.rstrip("。；，")
    exec_clause = format_execution_for_practice(exec_blurb, classify_execution_outcome(exec_blurb))
    merged = synthesize_outcome_narrative(j_part, exec_clause)
    if not merged:
        return m
    return _set_outcome(m, merged)


def polish_outcome_for_practice(fields: dict, pdf_text: str = "", units=None) -> dict:
    """终稿润色：规范判决起句、按执行结果类型改写表述、重新合成。"""
    if not fields:
        return fields
    m = dict(fields)
    text = pick_best_outcome_text(m)
    if not text:
        return m

    j_part, e_part = _split_judgment_execution(text)
    j_part = _polish_judgment_clause(j_part)

    allow_pdf_exec = has_execution_units(units, pdf_text)
    pdf_type = classify_execution_outcome(pdf_text) if pdf_text and allow_pdf_exec else ""
    if not e_part and allow_pdf_exec and pdf_text and pdf_type not in ("", "generic"):
        if not _text_covers_outcome_type(text, pdf_type):
            blurb = extract_special_execution_blurb(pdf_text) or extract_execution_blurb(pdf_text)
            if blurb:
                e_part = format_execution_for_practice(blurb, pdf_type)

    if j_part and e_part:
        safe_execution = format_execution_for_practice(e_part)
        judgment = j_part if j_part.endswith("。") else j_part + "。"
        if len(judgment + safe_execution) <= CASE_OUTCOME_MAX_LEN:
            merged = judgment + safe_execution
        else:
            merged = synthesize_outcome_narrative(j_part, safe_execution)
    elif j_part:
        merged = truncate_chinese(j_part + "。")
    elif e_part:
        merged = truncate_chinese(format_execution_for_practice(e_part))
    else:
        merged = truncate_chinese(text)

    return _set_outcome(m, merged)


def apply_outcome_type_override(fields: dict, outcome_type: str, pdf_text: str = "") -> dict:
    """Web 重填时按用户选择的执行结果类型改写表述。"""
    if not fields or not outcome_type or outcome_type == "auto":
        return fields
    m = dict(fields)
    text = pick_best_outcome_text(m)
    if not text:
        return m
    j_part, e_part = _split_judgment_execution(text)
    j_part = _polish_judgment_clause(j_part) if j_part else text.rstrip("。；，")

    if outcome_type == "none":
        merged = truncate_chinese(j_part + "。" if j_part else text)
        return _set_outcome(m, merged)

    blurb = e_part or pdf_text[:800] if pdf_text else e_part or text
    if not _text_covers_outcome_type(blurb, outcome_type):
        # 下拉框选择只确认类型，不等于法院已准许、债务已履行等细节。
        labels = {
            "bankruptcy": "破产相关", "settlement": "执行和解", "withdraw": "撤回执行",
            "participation": "参与分配", "denial": "不予执行", "suspension": "中止执行",
            "debt_cert": "债权凭证", "property_offset": "以物抵债",
            "completed": "执行完毕", "zhiben": "终本",
        }
        label = labels.get(outcome_type)
        if not label:
            return m
        e_clause = f"经办人标注执行类型为{label}，具体事实待核对。"
    else:
        e_clause = format_execution_for_practice(blurb, outcome_type)
    if not e_clause:
        return m
    if j_part:
        merged = synthesize_outcome_narrative(j_part, e_clause)
    else:
        merged = truncate_chinese(e_clause)
    return _set_outcome(m, merged)


def ensure_outcome_covers_execution(fields: dict, pdf_text: str = "", units=None) -> dict:
    """
    1. 特殊终结事由优先补写（破产/和解/撤回等）
    2. 无特殊事由时再补常规终本（须有执行 unit）
    3. 终稿按法律实务润色合成
    """
    if not fields:
        return fields
    m = dict(fields)
    if units is not None and has_execution_units(units, pdf_text):
        m = _ensure_special_execution(m, pdf_text)
    elif units is None:
        m = _ensure_special_execution(m, pdf_text)
    m = _ensure_general_execution(m, pdf_text, units=units)
    m = polish_outcome_for_practice(m, pdf_text, units=units)
    return m


def unify_case_outcome_fields(fields: dict) -> dict:
    """结案小结与审（办）结果使用同一综合表述（≤150字）"""
    if not fields:
        return fields
    m = dict(fields)
    text = pick_best_outcome_text(m)
    if not text:
        return m
    text = truncate_chinese(text, CASE_OUTCOME_MAX_LEN)
    m["结案小结"] = text
    m["审（办）结果"] = text
    m["审办结果"] = text
    return m
