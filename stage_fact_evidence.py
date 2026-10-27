"""Literal, bounded business-stage facts; never final case completion.

This pure helper does not read sources, resolve identities across documents or
rewrite values. The caller retains the exact original value and quotation.
"""
from __future__ import annotations

import re
import unicodedata


FIELDS = frozenset(("阶段工作情况", "顾问协议状态"))
_WORK_TITLE = re.compile(r"法律顾问工作记录|办理法律事务活动记录|法律事务工作记录|阶段工作记录|非诉讼法律事务工作记录")
_STATUS_TITLE = re.compile(r"(?:法律)?顾问协议(?:存续情况|状态|履行情况|中止情况|终止情况|解除情况)说明|(?:中止|终止|解除)(?:法律)?顾问协议书?")
_SUBJECT = re.compile(r"(?:^|(?<=[。;；\n]))(?:服务对象|委托人|聘方)(?:名称)?[:：]([^。;；,，:：\n]{2,80})(?=[。;；\n]|$)")
_REFERENCE = re.compile(r"另案|其他案件|另(?:一(?:份|个)?)?(?:顾问)?协议|其他(?:顾问)?协议|参考案例|案例摘录|引用案例|示例文本|参考模板|示例记录|声称|转述|诉称|辩称|主张|引述|据称")
_PROPOSED = re.compile(r"拟|计划|预计|预期|希望|争取|承诺|如(?:果)?|假如|假设|若|一旦|是否|尚待|尚未|未曾|未能|没有|并未|未予|不代表|不证明|不能证明|不能确认|不确认|并非|不是|[未不]$")
_FINANCIAL_OR_FINAL = re.compile(r"支付|收款|付款|收取|已收到|实收|尚欠|已退|应退|(?:退款|退费)(?:人民币)?[0-9零一二三四五六七八九十百千万]|到账|受偿|签收|签署|结案|办结|全部服务|全年.*(?:完成|终止)|(?:完成|终止).*全年|(?:本案|本项目|案件)(?:已)?(?:终止|结束|全部完成)")
_WORK_EVENT = re.compile(r"(?:已)?完成[^。;；]{0,45}(?:合同|协议|文书|模板)[^。;；]{0,20}(?:审查|审核|修订|起草)|(?:已)?(?:发出|发送|出具|交付)[^。;；]{0,30}(?:法律意见书|法律意见|修订意见|合同修改稿)")
_CONTINUING = re.compile(r"(?:该|本)?(?:法律)?顾问协议仍在履行|(?:该|本)?(?:法律)?顾问协议(?:仍)?(?:有效|存续)|后续(?:日常)?顾问服务继续")
_TERMINATED = re.compile(r"(?:该|本)?(?:法律)?顾问(?:协议|合同)(?:已|已经)(?:中止|终止|解除)")
_QUALIFIER = re.compile(r"但|仅|除外|尚未|未附|不包括|不涉及|不等于|不代表|不证明")
_PLAN_FOOTER = re.compile(r"(?:上述|以上|前述)[^。;；]{0,24}(?:拟开展|计划|工作安排|不是已完成|未完成)")


def _compact(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def stage_subject(page_text) -> str | None:
    """Return the one explicitly named service subject, never a model hint."""
    if not isinstance(page_text, str) or not page_text.strip():
        return None
    # Preserve line boundaries for independently headed identity labels.
    text = unicodedata.normalize("NFKC", page_text)
    # validate_fact's semantic path supplies an OCR-whitespace-compacted copy.
    # A known leading heading still creates a boundary, not an identity claim.
    heading = re.search(r"(?:" + _WORK_TITLE.pattern + "|" + _STATUS_TITLE.pattern + ")", text[:100])
    if heading:
        text = text[:heading.end()] + "\n" + text[heading.end():]
    names = {re.sub(r"\s+", "", m.group(1)) for m in _SUBJECT.finditer(text)}
    if len(names) != 1:
        return None
    name = next(iter(names))
    if (re.search(r"简称|不详|未提供|待核|、|\(|\)", name)
            or name in ("本公司", "该公司", "贵公司", "本单位", "该单位", "委托人", "聘方")
            or _REFERENCE.search(text)):
        return None
    corporate = bool(re.search(r"公司|事务所|委员会|学校|银行|医院|政府|中心$", name))
    if (re.search(r"(?:公司|事务所|银行|学校)(?:和|与|及).+(?:公司|事务所|银行|学校)", name)
            or not corporate and re.fullmatch(r"[\u3400-\u9fff]{1,4}(?:和|与|及)[\u3400-\u9fff]{1,4}(?:二人|两人)?", name)):
        return None
    return name


def validate_stage_fact(field, value, quote, page_text) -> bool:
    if field not in FIELDS or not all(isinstance(s, str) and s.strip() for s in (value, quote, page_text)):
        return False
    if len(value) > 1000 or len(quote) > 1500:
        return False
    value, quote, page = map(_compact, (value, quote, page_text))
    subject = stage_subject(page_text)
    if value not in quote or quote not in page or subject is None:
        return False
    title = _WORK_TITLE if field == "阶段工作情况" else _STATUS_TITLE
    heading = title.search(page[:100])
    if heading is None or _REFERENCE.search(page[:heading.end()]):
        return False
    for found in re.finditer(re.escape(quote), page):
        for candidate in re.finditer(re.escape(value), quote):
            start = found.start() + candidate.start()
            end = start + len(value)
            # A quoted example/allegation never becomes our business record.
            if _REFERENCE.search(page[:end]):
                continue
            if _PLAN_FOOTER.search(page[end:]):
                continue
            left = max(page.rfind(mark, 0, start) for mark in "。;；!！?？") + 1
            stops = [pos for mark in "。;；!！?？" if (pos := page.find(mark, end)) >= 0]
            right = min(stops) if stops else len(page)
            prefix = page[left:start]
            suffix = "" if value[-1] in "。;；!！?？" else page[end:right]
            if _PROPOSED.search(prefix):
                continue
            # A cropped quotation must not discard a same-sentence limitation.
            if _QUALIFIER.search(suffix):
                continue
            if field == "阶段工作情况":
                event = _WORK_EVENT.search(value)
                if (not event or _PROPOSED.search(value[:event.start()])
                        or re.search(r"对方|相对方|第三方|第三人|被告|原告|债务人|供应商", prefix + value[:event.start()])
                        or _FINANCIAL_OR_FINAL.search(value)):
                    continue
                actor = prefix + value[:event.start()]
                # An explicit other recipient/actor defeats the page's service
                # subject label; do not treat the heading as ownership of every
                # event on the page. Ambiguous bare personal actors stay reviewable.
                without_subject = actor.replace(_compact(subject), "")
                if re.search(r"[\u3400-\u9fffA-Za-z0-9]{2,80}(?:公司|银行|事务所|学校|医院|委员会)", without_subject):
                    continue
                recipient = re.search(r"(?:为|替)([^:。;；,，]{1,80})$", actor)
                if recipient and recipient.group(1) != _compact(subject):
                    continue
                actor = re.sub(r"(?:办理结果|阶段工作情况|工作情况|阶段工作|实际工作)[:：]", "", actor)
                actor = re.sub(r"\d{4}年\d{1,2}月\d{1,2}日|[,，:：]|已经|已", "", actor).strip()
                if actor and _compact(subject) not in actor and "本所" not in actor and "律师" not in actor:
                    continue
                return True
            # Explicit ongoing/suspended/terminated states are separate from
            # case closure, payment or signature. Conflicting records remain
            # separate candidates for the normal conflict mechanism.
            state = _CONTINUING.search(value) or _TERMINATED.search(value)
            if (not state or _PROPOSED.search(value[:state.start()])
                    or re.search(r"已办结|已结案|已完成|签收|签署|支付|收款", value)):
                continue
            states = set()
            for pattern, category in ((_CONTINUING, "continuing"), (_TERMINATED, "ended_or_suspended")):
                # A document heading such as 存续情况说明 is a subject/title,
                # not an assertion that the agreement is still in force.
                for match in pattern.finditer(page, heading.end()):
                    boundary = max(page.rfind(mark, 0, match.start()) for mark in "。;；!！?？") + 1
                    if not _PROPOSED.search(page[boundary:match.start()]):
                        states.add(category if category == "continuing" else match.group()[-2:])
            if len(states) > 1:
                continue
            return True
    return False
