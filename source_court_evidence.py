"""Bounded candidates from already-read judicial headings, without I/O.

This adds a candidate, not a finding that a document is authentic or that a
court remains responsible for a proceeding. The caller owns source scope,
conflicting court candidates, human edits and final evidence persistence.
"""
from __future__ import annotations

import re


_NUMBER = re.compile(r"\(\d{4}\)[\u3400-\u9fffA-Za-z0-9]{1,20}(?:民|刑|行)(?:初|终|再|申|抗)\d+号")
_ANY_NUMBER = re.compile(r"\(\d{4}\)[\u3400-\u9fffA-Za-z0-9]{1,30}号")
_PENALTY_PREFIX = re.compile(r"(?:罚字|罚决字|罚决)$")
_COURT = re.compile(r"[\u3400-\u9fffA-Za-z0-9()·-]{2,65}(?:人民法院|海事法院|铁路运输法院|军事法院)")
_TITLE = re.compile(r"(?:(?:民事|刑事|行政)(?:判决书|裁定书|调解书)|传票|受理(?:案件)?通知书)")
_PREFIXES = frozenset(("中华人民共和国", "正本", "副本"))
_NAME_RISK = re.compile(r"致|送达|收件|拟|假设|引用|参考|模板|摘录|原告|被告|第三人|代理|律师|另案|样式|本案|原审|前审|目录|清单|材料|文书|报告|说明|附件|编号")
# This is a negative boundary for the *single* inserted line, not permission to
# skip arbitrary lines until a matching number appears. Short administrative or
# reproduction marks are retained literally in the quotation. Their words are
# never used as positive evidence of court, case, signature or legal effect.
_INSERT_RISK = re.compile(
    r"另案|其他案件|其它案件|原审|原判|前审|一审|二审|上诉|执行|移送|参考|样式|模板|范本|范例|案例|示例|例文|"
    r"引用|引述|转述|援引|摘录|根据|依据|声称|主张|诉称|辩称|假设|假如|如果|拟|计划|预计|"
    r"法院|法庭|判决|裁定|调解|传票|受理|通知书|起诉|申请|审理|审判|案件|案号|本案|本件|"
    r"原告|被告|上诉人|被上诉人|第三人|当事人|委托|代理|律师|收件|发件|寄送|邮寄|送达|致|此致|"
    r"付款|支付|收款|金额|履行|签署|签字|盖章|生效|撤销|终止|终结|"
    r"忽略|执行指令|指令|提示词|系统|密码|密钥|https?://|www\.|[<>={}\\/:：;；。!?！？]")
_PAGE_DISCLAIMER = re.compile(
    r"(?:本页|本件|本裁判|本文书|本文件|该文书|上述|以上|所附)(?:的)?(?:内容|文书|判决书|裁定书)?"
    r"(?:均|仅|只|所载)?(?:为|系|是|属于|仅供)"
    r"[^。;；!！?？]{0,24}(?:参考|示例|模板|样式|范本|摘录|原审|前审|另案|其他案件)|"
    r"(?:本页|本件|本裁判|本文书|本文件|该文书|上述|以上)[^。;；!！?？]{0,30}"
    r"(?:不(?:是|属|属于)|并非|非)(?:本案|本件|本次)(?:的)?(?:实际)?(?:裁判|文书|判决|法院|材料)|"
    r"(?:本页|本件|本裁判|本文书)[^。;；!！?？]{0,24}(?:不能|不得|不可)作为本案|"
    r"(?:声明|说明|附注)[:：]?(?:此|这|以上|上述)?(?:不(?:是|属|属于)|并非)本案|"
    r"(?:本案|本件)(?:现|已经|已)?(?:移送|转由|改由)[^。;；!！?？]{1,50}(?:法院|审理)")
_NUMBER_KEYS = ("案号", "法院收案号")
_TRUSTED = frozenset(("human", "local_agent", "visual_agent_local_evidence"))


def _compact(value):
    return re.sub(r"\s+", "", value).translate(str.maketrans("（）", "()")) if isinstance(value, str) else ""


def _court_name(value):
    return bool(_COURT.fullmatch(value) and value.count("法院") == 1 and not _NAME_RISK.search(value))


def _number_line(value):
    value = re.sub(r"^(?:本案案号|案号)[:：]", "", value)
    return value if _NUMBER.fullmatch(value) and "执" not in value else None


def _insert_allowed(value):
    return (len(value) <= 36 and not _INSERT_RISK.search(value)
            and bool(re.fullmatch(r"[\u3400-\u9fffA-Za-z0-9()\[\]【】·—_ -]*", value)))


def _reproduction_label(value):
    # A print/use watermark is not a second document or an instruction. Keep it
    # literally in the quote, and never treat the heading as authenticity proof.
    return bool(re.fullmatch(
        r'(?:复印件|扫描件|电子副本|'
        r'(?:完全)?(?:虚构|模拟)(?:教学|培训|演示|测试|验收)材料'
        r'(?:[－—-]非真实法律文书)?(?:[－—-]无真实身份或印章)?)', value))


def extract_court_header_candidate(page_text, current_case_number):
    """Return a literal court heading candidate bound to an accepted case no.

    One short non-operative line may intervene between title and number. It is
    never removed from ``quote``. No leading body/letter/directory content is
    skipped. Different visible case numbers or second standalone headings keep
    the page for review. Trial-number equality is necessary, not identity proof.
    """
    current = _compact(current_case_number)
    if (not isinstance(page_text, str) or not page_text.strip() or len(page_text) > 60000
            or not _NUMBER.fullmatch(current) or "执" in current):
        return None
    physical = []
    offset = 0
    for raw in page_text.splitlines(keepends=True):
        physical.append((raw.rstrip("\r\n"), offset))
        offset += len(raw)
    if not physical:
        return None
    index = 0
    # Only whitespace at the page edge, not arbitrary text, may precede it.
    while index < min(2, len(physical)) and not physical[index][0].strip():
        index += 1
    # Native PDF extraction can place a standalone printed page number before
    # the court heading. Skip exactly one numeric line only when the next line
    # is already a full court/title; never search past arbitrary body content.
    if (index+1 < len(physical) and re.fullmatch(r'[1-9]\d{0,3}', _compact(physical[index][0]))
            and (_court_name(_compact(physical[index+1][0])) or _TITLE.fullmatch(_compact(physical[index+1][0])))):
        index += 1
    prefix_count = 0
    while index < len(physical) and _compact(physical[index][0]) in _PREFIXES and prefix_count < 2:
        index += 1
        prefix_count += 1
    if index >= len(physical):
        return None
    start = index
    if _TITLE.fullmatch(_compact(physical[index][0])):
        title = _compact(physical[index][0])
        index += 1
        if index < len(physical) and _reproduction_label(_compact(physical[index][0])):
            index += 1
        if index >= len(physical):
            return None
        court_start = physical[index][1]
        raw = physical[index][0]
        line = _compact(raw)
        combined = re.fullmatch(r'(.+?法院)((?:(?:本案案号|案号)[:：])?\(\d{4}\).+)', line)
        if combined:
            court, number = combined[1], _number_line(combined[2])
            # Raw offsets preserve spaces, fullwidth punctuation and OCR text.
            court_end = court_start + raw.index('法院') + len('法院')
        else:
            court = line
            court_end = court_start + len(raw)
            index += 1
            number = _number_line(_compact(physical[index][0])) if index < len(physical) else None
        if not _court_name(court) or number != current:
            return None
        return _validated_heading(page_text, physical, start, index, court_start,
                                  court_end, title, current_case_number)
    court_start = physical[start][1]
    court = _compact(physical[index][0])
    if not _court_name(court):
        # One adjacent physical OCR wrap is permitted, but never an empty line,
        # a label or a full name followed by a second court.
        if (index + 1 >= len(physical) or not court
                or not _compact(physical[index + 1][0]) or "法院" in court
                or _court_name(_compact(physical[index + 1][0]))):
            return None
        court += _compact(physical[index + 1][0])
        if not _court_name(court):
            return None
        index += 1
    court_end = physical[index][1] + len(physical[index][0])
    index += 1
    if index >= len(physical):
        return None
    title = _compact(physical[index][0])
    if not _TITLE.fullmatch(title):
        if (index + 1 >= len(physical) or not title
                or not _compact(physical[index + 1][0])):
            return None
        title += _compact(physical[index + 1][0])
        if not _TITLE.fullmatch(title):
            return None
        index += 1
    index += 1
    if index >= len(physical):
        return None
    number = _number_line(_compact(physical[index][0]))
    if number is None:
        if not _insert_allowed(_compact(physical[index][0])):
            return None
        index += 1
        if index >= len(physical):
            return None
        number = _number_line(_compact(physical[index][0]))
    if number != current:
        return None
    return _validated_heading(page_text, physical, start, index, court_start,
                              court_end, title, current_case_number)


def _validated_heading(page_text, physical, start, index, court_start, court_end,
                       title, current_case_number):
    current = _compact(current_case_number)
    if title[0] in "民刑行" and title[0] != re.search(r"(民|刑|行)(?:初|终|再|申|抗)\d+号$", current)[1]:
        return None
    # Retain a small physical heading; no search through long body text.
    end = physical[index][1] + len(physical[index][0])
    if index - start > 5 or end - physical[start][1] > 400:
        return None
    compact_page = _compact(page_text)
    if _PAGE_DISCLAIMER.search(compact_page):
        return None
    # A second full case number or standalone court/title is ambiguous. This
    # deliberately sacrifices recall of quoted prior proceedings for review.
    numbers = set()
    for match in _ANY_NUMBER.finditer(compact_page):
        # An explicitly named administrative penalty number is not a second
        # judicial case. Never exempt a judicial-looking or unlabelled number.
        if (re.fullmatch(r"\(\d{4}\)第\d+号", match[0])
                and _PENALTY_PREFIX.search(compact_page[max(0, match.start()-12):match.start()])):
            continue
        numbers.add(match[0])
    if numbers != {current}:
        return None
    if any(_court_name(_compact(raw)) or _TITLE.fullmatch(_compact(raw))
           for raw, _ in physical[index + 1:]):
        return None
    return {"field": "审理法院",
            "value": page_text[court_start:court_end].strip(),
            "quote": page_text[physical[start][1]:end].strip(),
            "binding": "court_case_number", "case_number": current_case_number}


def current_court_binding_supported(ref, fields):
    """Check the current canonical trial number behind a saved court binding.

    Source ownership/page validity, target court value freshness and derived
    input matching remain caller duties. Legacy/other bindings are unchanged.
    A matching alias alone cannot override an absent/cleared canonical number.
    """
    if not isinstance(ref, dict):
        return False
    if ref.get("binding") != "court_case_number":
        return True
    if not isinstance(fields, dict):
        return False
    bound = _compact(ref.get("case_number"))
    current = _compact(fields.get("案号"))
    if not _NUMBER.fullmatch(bound) or "执" in bound or current != bound:
        return False
    conflicts = fields.get("_field_conflicts", [])
    if not isinstance(conflicts, list) or any(
        not isinstance(item, dict) or (item.get("field") in _NUMBER_KEYS and item.get("resolved") is not True)
        for item in conflicts
    ):
        return False
    provenance = fields.get("_provenance")
    if not isinstance(provenance, dict):
        return False
    canonical_confirmed = False
    for key in _NUMBER_KEYS:
        raw = fields.get(key)
        if raw is not None and not isinstance(raw, str):
            return False
        value = _compact(raw)
        if value and value != current:
            return False
        refs = provenance.get(key, [])
        refs = [refs] if isinstance(refs, dict) else refs
        if not isinstance(refs, list):
            return False
        matching = [item for item in refs if isinstance(item, dict)
                    and isinstance(item.get("value"), str) and _compact(item["value"]) == value]
        if key in fields and not value and any(item.get("method") == "human" for item in matching):
            return False
        if key == "案号":
            canonical_confirmed = any(item.get("method") in _TRUSTED for item in matching)
    return canonical_confirmed
