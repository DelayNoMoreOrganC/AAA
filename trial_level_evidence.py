"""Source-only support for the current judicial proceeding (not retainer scope).

No inference from a case number, document title or representation agreement.
This boolean guard neither extracts a replacement value nor rewrites evidence.
"""
from __future__ import annotations

import re
import unicodedata


_LEVEL = r"(?:第一审|第二审|一审|二审|再审|重审|初审|终审)"
_VALUE = re.compile(r"(?:民事|刑事|行政)?" + _LEVEL)
_PUNCTUATION = "。!！?？;；"
_PATTERNS = (
    # A neutral judicial field is itself an explicit assertion, but an outer
    # retainer/reference/history section can still invalidate that occurrence.
    re.compile(r"(?:(?:本案|本件)(?:当前|现行)?|当前|现)?(?:审级|审理程序)[:为是]+"
               r"(?P<level>(?:民事|刑事|行政)?" + _LEVEL + r")(?:程序|阶段)?"),
    re.compile(r"本院(?:现|目前|正在)?对本案(?:现|目前|正在)?(?:进行|开展)"
               r"(?P<level>(?:民事|刑事|行政)?" + _LEVEL + r")审理"),
    re.compile(r"本案(?:现|目前|当前)?(?:系|为|属于)"
               r"(?P<level>(?:民事|刑事|行政)?" + _LEVEL + r")(?:案件|程序)"),
    re.compile(r"本案(?:现|目前|当前)?(?:适用|按照|依照)"
               r"(?P<level>(?:民事|刑事|行政)?" + _LEVEL + r")程序(?:审理)?"),
    re.compile(r"(?:现)?本案(?:现|目前|当前|正在)(?:处于|(?:已)?进入|进行|(?:已)?转入)"
               r"(?P<level>(?:民事|刑事|行政)?" + _LEVEL + r")(?:程序|审理|阶段)"),
    re.compile(r"现本案已转入(?P<level>(?:民事|刑事|行政)?" + _LEVEL + r")程序"),
)
_BAD_PREFIX = re.compile(
    r"原审|此前|曾经?|过去|原先|上次|前次|拟|计划|预计|准备|将|"
    r"如果|假如|假设|假定|若|一旦|尚待|尚未|未经|未曾|未予|并非|不是|不属|不代表|不证明|不能认定|否认|"
    r"声称|诉称|辩称|主张|转述|引用|引述|摘录|他案|另案|其他案件|其它案件|"
    r"示例|样例|模板|参考|代理|委托|辩护|合同范围|合同约定|办理范围")
_SCOPE = re.compile(
    r"(?P<bad>参考(?:案例|样式|范本|模板)|(?:另案|他案|其他案件)(?:文书|判决|材料|案例|摘录)?|"
    r"(?:引用|引述|摘录|转述)(?:另案|他案)?(?:文书|判决|内容)?|"
    r"(?:委托代理|委托|代理|合同)(?:事项|范围|阶段|约定))"
    r"(?:[:]|如下[。:])|"
    r"(?P<reset>本院审理情况|本案当前审理情况|本案现时审理情况)[:]")
_BACKREF = re.compile(r"^(?:上述|以上|前述|该|此|本页)(?:所载|记载|文字|内容|程序说明|"
                      r"审级(?:说明)?|审理程序|审理情况|程序|表述|记载|陈述|记录|说明)")
_BACKREF_DENY = re.compile(r"示例|假设|假定|样式|模板|参考|引文|引用|转述|约定|代理范围|"
                          r"拟定|尚待|未获[^。;；]{0,8}确认|尚未|未经|未确认|未核实|已撤回|不代表|并非|不是|不属实|不真实")
_NEUTRAL_LEAD = re.compile(r"(?:本院审理情况|本案当前审理情况|本案现时审理情况)[:]")
_CURRENT_NEGATIVE = re.compile(r"本案(?:现|目前|当前)?(?:尚未|未|还未)(?:起诉|立案|受理|进入审理程序)")
_CURRENT_LEVEL_DENIAL = re.compile(
    r"本案(?:现|目前|当前)?(?:并非|不是|不属于|尚未进入|未进入)"
    r"(?P<level>(?:民事|刑事|行政)?" + _LEVEL + r")(?:案件|程序|审理阶段)")


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def _canonical(value: str) -> str:
    level = re.sub(r"^(?:民事|刑事|行政)", "", value)
    return {"第一审": "一审", "第二审": "二审", "初审": "一审"}.get(level, level)


def _sentence_bounds(page: str, start: int, end: int) -> tuple[int, int]:
    left = max(page.rfind(mark, 0, start) for mark in _PUNCTUATION) + 1
    stops = [position for mark in _PUNCTUATION if (position := page.find(mark, end)) >= 0]
    return left, min(stops) if stops else len(page)


def _section_qualified(page: str, start: int, raw_lines: list[tuple[int, int, str]]) -> bool:
    """Retain explicit outer reference/scope headings across OCR line breaks."""
    scoped = False
    for marker in _SCOPE.finditer(page[:start]):
        scoped = marker["bad"] is not None
    for left, right, line in raw_lines:
        if right > start:
            break
        if re.fullmatch(r"(?:参考(?:案例|样式|模板)|另案(?:文书|判决|材料)|引用材料|代理范围|委托事项)[:]?", line):
            # A later explicit current-case section can end that section.
            if not any(marker["reset"] for marker in _SCOPE.finditer(page[right:start])):
                scoped = True
    return scoped


def _judicial_header_end(lines: list[tuple[int, int, str]], start: int) -> int:
    """Recognize only a finite physical preamble, never derive level from it.

    A line break by itself cannot drop a lead-in such as '假定' or '原审摘录'.
    This allowance needs the printed court + judicial-document title sequence,
    with at most two fixed copy/national labels and one optional case number.
    """
    header = [entry for entry in lines if entry[2] and entry[1] <= start]
    index = 0
    while index < min(2, len(header)) and header[index][2] in ("中华人民共和国", "正本", "副本"):
        index += 1
    if index + 1 >= len(header):
        return 0
    court, title = header[index][2], header[index + 1][2]
    if (not re.fullmatch(r"[\u3400-\u9fff]{2,60}人民法院", court)
            or re.search(r"致|抄送|收件|参照|参考|另案|原审|模板|样式|摘录", court)
            or not re.fullmatch(r"(?:民事|刑事(?:附带民事)?|行政)?(?:判决书|裁定书|调解书|决定书|通知书)", title)):
        return 0
    index += 2
    if index < len(header) and re.fullmatch(r"\([0-9]{4}\)[\u3400-\u9fff0-9]{1,25}号", header[index][2]):
        index += 1
    return header[index - 1][1]


def _valid_occurrence(page: str, match: re.Match, lines: list[tuple[int, int, str]]) -> bool:
    left, right = _sentence_bounds(page, match.start(), match.end())
    prefix, suffix = page[left:match.start()], page[match.end():right]
    if _BAD_PREFIX.search(prefix) or _section_qualified(page, match.start(), lines):
        return False
    # An assertion must start the source sentence or follow a narrowly neutral
    # judicial heading. Unknown lead-in verbs are not accepted merely because
    # they were absent from a list of denial/quotation keywords.
    lead = prefix
    if left == 0:
        header_end = _judicial_header_end(lines, match.start())
        if header_end:
            lead = page[header_end:match.start()]
    if lead and not _NEUTRAL_LEAD.fullmatch(lead):
        return False
    # A quoted example is not transformed into the narrator's current case.
    for opening, closing in (("“", "”"), ("「", "」"), ("『", "』")):
        if page.rfind(opening, 0, match.start()) > page.rfind(closing, 0, match.start()):
            return False
    # Do not accept a prefix of a different proposition (一审案件的代理范围).
    line_end = any(end == match.end() for _, end, _ in lines)
    if suffix and suffix[0] not in ",，:。;；!！?？" and not line_end:
        return False
    if re.search(r"仅为(?:计划|假设|约定|示例)|未经确认|尚未确定|并非实际|不是实际|不属实|已撤回", suffix):
        return False
    following = page[right:].lstrip(_PUNCTUATION)
    next_sentence = re.split("[" + _PUNCTUATION + "]", following, maxsplit=1)[0]
    if _BACKREF.match(next_sentence) and _BACKREF_DENY.search(next_sentence):
        return False
    return True


def validate_trial_level(value: str, quote: str, page_text: str) -> bool:
    """Require a literal, fully quoted assertion at a valid source occurrence.

    Whitespace/full-width comparison only. If two unqualified current levels
    disagree, neither wins by order. A separately marked historical statement
    does not conflict with an explicitly current statement. No page-title or
    case-number deduction, source I/O, calls, or mutation occurs here.
    """
    if not all(isinstance(item, str) and item.strip() for item in (value, quote, page_text)):
        return False
    value, quote, page = map(_compact, (value, quote, page_text))
    if not _VALUE.fullmatch(value) or value not in quote or quote not in page:
        return False
    lines = []
    position = 0
    for raw in page_text.splitlines():
        line = _compact(raw)
        lines.append((position, position + len(line), line))
        position += len(line)
    # An explicit current case non-commencement contradicts an asserted trial
    # stage. Ignore other-case/historical/quoted negatives, not unrelated fees.
    for negative in _CURRENT_NEGATIVE.finditer(page):
        left, _ = _sentence_bounds(page, negative.start(), negative.end())
        if not _BAD_PREFIX.search(page[left:negative.start()]) and not _section_qualified(page, negative.start(), lines):
            return False
    for negative in _CURRENT_LEVEL_DENIAL.finditer(page):
        left, _ = _sentence_bounds(page, negative.start(), negative.end())
        if (_canonical(negative["level"]) == _canonical(value)
                and not _BAD_PREFIX.search(page[left:negative.start()])
                and not _section_qualified(page, negative.start(), lines)):
            return False
    matches = [match for pattern in _PATTERNS for match in pattern.finditer(page)
               if _valid_occurrence(page, match, lines)]
    if len({_canonical(match["level"]) for match in matches}) != 1:
        return False
    cursor = 0
    while (cursor := page.find(quote, cursor)) >= 0:
        for match in matches:
            # The quote must carry the complete semantic assertion, and the
            # literal proposed value must lie within this occurrence's level.
            if (cursor <= match.start() and match.end() <= cursor + len(quote)
                    and value in match["level"] and _canonical(value) == _canonical(match["level"])):
                return True
        cursor += max(1, len(quote))
    return False
