"""Independent title/context checks; catalog placement never proves signing.

Only a standalone leading heading is evidence. A quoted title in a complaint,
power of attorney, evidence list or business contract must not change its type.
No customer text is emitted in diagnostics; returned titles come from literals.
"""
from __future__ import annotations

import re
import unicodedata

NOTICE = "agency_notice"
NOTICE_TITLE = "委托代理通知书"
EXECUTION = "execution"
EXECUTION_TITLES = frozenset(("执行申请书", "申请执行书", "强制执行申请书", "申请强制执行书", "执行裁定书",
    "执行通知书", "报告财产令", "限制消费令", "限制高消费令", "执行决定书", "执行案件受理通知书",
    "受理执行案件通知书", "执行立案通知书"))
EXECUTION_PROCESS_NOTICES = {
    "评估结果通知书": r"评估|估价",
    "拍卖事项通知": r"拍卖|变卖",
    "拍卖事项通知书": r"拍卖|变卖",
    "执行情况告知书": r"执行|拍卖|款项",
    "执行情况通知书": r"执行|拍卖|款项",
}
ACCEPTANCE_TITLES = frozenset(("受理案件通知书", "案件受理通知书", "民事案件受理通知书"))
PRESERVATION_NOTICE_TITLES = frozenset(("财产保全情况告知书", "保全情况告知书", "财产保全告知书"))
CLOSURE_NOTICE_TITLES = frozenset(("结案通知书", "执行结案通知书", "执行案件结案通知书"))
PRESERVATION_TITLES = frozenset(("财产保全申请书", "诉讼保全申请书", "诉前财产保全申请书", "证据保全申请书",
    "行为保全申请书", "先予执行申请书", "先行给付申请书", "财产保全裁定书", "保全裁定书"))
DEFAULT_NEW_READ_BUDGET = 24
MAX_NEW_READ_BUDGET = 128
HEADINGS = {
    "结案报告表": "closure_report", "律师结案报告表": "closure_report",
    "律师所送达材料清单": "service_list", "律师事务所送达材料清单": "service_list",
    "律师办案质量监督卡": "quality_card", "律师服务质量监督卡": "quality_card",
    "委托人须知": "client_notice",
    "立案审批表": "intake_approval", "律师所接案审批表": "intake_approval",
    "接案审批表": "intake_approval", "收案审批表": "intake_approval",
    NOTICE_TITLE: NOTICE,
    "授权委托书": "poa", "民事授权委托书": "poa",
    "民事起诉状": "complaint", "起诉状": "complaint", "行政起诉状": "complaint",
    "证据目录": "evidence", "证据清单": "evidence", "证据材料清单": "evidence", "证据材料目录": "evidence",
    "借款合同": "evidence", "金融借款合同": "evidence", "个人借款合同": "evidence",
    "保证合同": "evidence", "抵押合同": "evidence", "买卖合同": "evidence",
    "委托代理合同": "contract", "民事委托代理合同": "contract", "法律服务合同": "contract",
    "民事判决书": "judgment", "民事裁定书": "ruling", "民事调解书": "mediation",
    "行政判决书": "judgment", "刑事判决书": "judgment", "行政裁定书": "ruling", "刑事裁定书": "ruling",
    "传票": "summons", "出庭通知书": "summons", "开庭传票": "summons", "开庭通知书": "summons",
    "诉讼授权委托书": "poa", "民事诉讼授权委托书": "poa",
    "最高额保证合同": "evidence", "最高额抵押合同": "evidence", "借款担保合同": "evidence",
    "质押合同": "evidence", "租赁合同": "evidence", "销售合同": "evidence",
    "法律顾问合同": "contract", "法律服务协议": "contract", "刑事辩护委托合同": "contract",
    **{title: "unknown" for title in ACCEPTANCE_TITLES},
    **{title: "unknown" for title in CLOSURE_NOTICE_TITLES},
    **{title: "preservation" for title in PRESERVATION_NOTICE_TITLES},
    **{title: "preservation" for title in PRESERVATION_TITLES},
    **{title: EXECUTION for title in EXECUTION_TITLES},
    **{title: EXECUTION for title in EXECUTION_PROCESS_NOTICES},
}
# These headings describe existing business-specific catalog material. The
# same legal opinion is a non-litigation deliverable or a counsel work record
# depending on the selected business; never impose a global civil/default slot.
_BUSINESS_ACTIVITY_TITLES = (
    "办理法律事务活动记录", "办理具体法律事务活动记录", "办理具体法律事务活动的记录",
)
BUSINESS_HEADINGS = {
    "criminal": {title: "meeting_record" for title in
                 ("会见笔录", "刑事会见笔录", "会见犯罪嫌疑人笔录", "会见被告人笔录")},
    "nonlit": {title: "legal_work" for title in
               ("法律意见书", "法律工作记录", "法律事务工作记录", "非诉法律事务工作记录", *_BUSINESS_ACTIVITY_TITLES)},
    "counsel": {
        **{title: "client_intro" for title in ("聘方基本情况", "聘方基本情况介绍", "顾问单位基本情况")},
        **{title: "work_record" for title in ("法律意见书", "法律工作记录", "法律事务工作记录", "顾问工作记录", "法律顾问工作记录", "法律顾问服务记录", *_BUSINESS_ACTIVITY_TITLES)},
        **{title: "agreement_status" for title in ("顾问协议存续情况说明", "顾问协议中止情况说明", "顾问协议终止情况说明", "法律顾问协议状态说明")},
    },
}


def _headings(case_type=None):
    return HEADINGS | BUSINESS_HEADINGS.get(case_type, {})


def _compact(value):
    return re.sub(r"[\s\u200b\ufeff]+", "", unicodedata.normalize("NFKC", str(value or "")))


_CASE_NUMBER = re.compile(r"^(?:案号[:：]?)?(\(\d{4}\)[\u4e00-\u9fff\d]{1,28}号)(?:之[一二三四五六七八九十百\d]{1,4})?$")
_EVIDENCE_PREFIX = re.compile(r"^(?:证据(?:[一二三四五六七八九十百0-9]+|目录|清单|材料)|附件清单|材料目录)")
_NOTICE_REFERENCE = re.compile(r"另案|其他案件|其它案件|案外案件|引用.{0,12}(?:判决|裁定|通知)|仅供参考|摘录")
_PRESERVATION_ACTION = r"查封|冻结|扣押|(?:解除|采取|实施).{0,8}保全"
_CLOSURE_ACTION = r"执行完毕|执行终结|执行结案|执结|终结(?:本次)?执行|结案|结束执行"


def _notice_context_conflicts(body, action, *, reject_negative=True):
    # A notice heading must not launder a quoted/proposed/negated event into a
    # locally verified document. Test only the prefix of the relevant action:
    # a later right to object or an unpaid balance does not negate closure.
    if _NOTICE_REFERENCE.search(body):
        return True
    for clause in re.split(r"[。;；]", body):
        for match in re.finditer(action, clause):
            lead = re.split(r"[,，]", clause[:match.start()])[-1]
            if re.search(r"拟|计划|预计|若|如(?!下|实|期|数)(?:果)?|假如|假设|一旦|请求|恳请|诉称|主张", lead):
                return True
            if reject_negative and re.search(r"(?:尚未|并未|没有|未曾|未能|未予|未|不予|并非)(?:依法|予以|决定|采取|实施|全部|足额|实际|对[^,，。;；]{0,40})?$", lead):
                return True
    return False


def _number_phase(value):
    """Accept a complete header line, never a case number embedded in prose."""
    line = _compact(value)
    match = _CASE_NUMBER.fullmatch(line)
    if not match:
        header = re.fullmatch(r"([\u3400-\u9fff]{2,60}人民法院)((?:案号:?)?\(\d{4}\).+)", line)
        if header and not re.search(r"引用|根据|依据|参照|另案|其他案件|其它案件|诉称|主张|摘录|参考", header.group(1)):
            match = _CASE_NUMBER.fullmatch(header.group(2))
    if not match:
        return "", ""
    number = match.group(1)
    if re.search(r"(?:执保|财保|行保)\d+号$", number):
        return "preservation", number
    if re.search(r"执(?:恢|异|复|监)?\d+号$", number):
        return "enforcement", number
    if re.search(r"(?:民|行|刑)(?:初|终|申|再|抗)\d+号$", number):
        return "trial", number
    return "", number


def _prefix_allowed(line):
    return bool(_number_phase(line)[1] or re.fullmatch(
        r"(?:.{1,50}(?:人民法院|人民检察院|仲裁委员会|律师事务所)|中华人民共和国|正本|副本)", line))


def _result(kind, title, stage, *, reason="standalone_title_verified", role="standard", verified=True, identity=""):
    return {"doc_type": kind if verified else "unknown", "candidate_type": kind, "title": title,
            "procedure_stage": stage if verified else "unknown", "document_role": role if verified else "unknown",
            "verified": verified, "reason_code": reason, "_identity": identity}


def _classify_heading(title, lines, index, consumed, kind):
    body = _compact("\n".join(lines[index + consumed:]))[:5000]
    context = _compact("\n".join(lines))[:6000]
    # An earlier document number printed in an introductory header is allowed;
    # numbers quoted deep in the body are deliberately ignored.
    anchors = [_number_phase(value) for value in lines[:index] + lines[index + consumed:index + consumed + 3]]
    phases = {phase for phase, _ in anchors if phase}
    identity = next((number for _, number in anchors if number), "")
    phase = next(iter(phases)) if len(phases) == 1 else ""
    if len(phases) > 1 or len({number for _, number in anchors if number}) > 1:
        return _result(kind, title, "unknown", verified=False, reason="conflicting_leading_case_numbers")
    business_context = {
        "meeting_record": (r"会见时间|会见地点|被会见人|犯罪嫌疑人|被告人", r"律师|记录|问[:：]|答[:：]"),
        "legal_work": (r"法律意见|审查意见|律师|本所", r"事项|项目|建议|结论|起草|审查|草拟"),
        "client_intro": (r"顾问单位|聘方|企业|公司", r"基本情况|经营范围|住所|法定代表人|业务范围"),
        "work_record": (r"顾问|法律服务|法律事务|律师|本所", r"工作事项|服务事项|顾问事项|记录|审查|起草|咨询"),
        "agreement_status": (r"法律顾问|顾问协议|顾问合同", r"存续|中止|终止|服务期限|协议状态"),
    }
    if kind in business_context:
        supported = all(re.search(pattern, body) for pattern in business_context[kind])
        return _result(kind, title, "other", verified=bool(supported),
                       reason="business_document_context_verified" if supported else "business_document_context_unverified")
    court = bool(re.search(r"人民法院|法院", context))
    if kind == "firm_letter":
        supported = bool(court and re.search(r"指派|委派", body) and re.search(r"律师", body)
                         and re.search(r"代理|辩护", body) and not re.search(r"拟指派|拟委派|模板|样例", context))
        return _result(kind, title, "engagement", verified=supported,
                       reason="firm_convention_letter_20261026")
    if title in ACCEPTANCE_TITLES:
        if phase == "enforcement":
            return _result(EXECUTION, title, "enforcement", identity=identity, reason="execution_acceptance_verified")
        if phase == "preservation":
            return _result("preservation", title, "trial", identity=identity, reason="preservation_acceptance_verified")
        # There is no dedicated catalog slot for ordinary acceptance notices.
        # Recognize its nature without pretending it is a summons or a ruling.
        # Some notices state the current trial procedure instead of repeating
        # "受理" in the body. Require a current declarative sentence, a leading
        # court header and a trial case number for this alternative; quoted,
        # planned or conditional proceedings do not qualify.
        current_trial = bool(phase == "trial" and identity and
            any(re.fullmatch(r"[\u3400-\u9fff]{2,60}人民法院", _compact(line)) for line in lines[:index]) and
            re.search(r"(?:^|[。；;])本院(?:依法)?适用(?:简易|普通|小额诉讼)程序对本案(?:进行)?审理(?=[，,。；;]|$)", body[:800]))
        return _result("unknown", title, "trial", role="case_acceptance_notice", identity=identity,
                       verified=court and (bool(re.search(r"受理|立案", body)) or current_trial), reason="acceptance_notice_no_dedicated_slot")
    if title in PRESERVATION_NOTICE_TITLES:
        if phase == "enforcement":
            return _result("preservation", title, "unknown", verified=False, reason="title_case_number_stage_conflict")
        factual = bool(re.search(r"(?:本院|本案)[^。;；]{0,140}(?:" + _PRESERVATION_ACTION + r")", body)
                       or re.search(r"保全(?:情况|结果|措施)[:：][^。;；]{0,100}(?:" + _PRESERVATION_ACTION + r")", body)
                       or re.search(r"(?:本院|本案)[^。;；]{0,100}(?:未发现|未查到|未查询到|没有发现)[^。;；]{0,30}(?:可供保全|保全财产)", body))
        # An unsuccessful preservation attempt is still a preservation notice.
        # Classifying it must not assert that any property was actually frozen.
        # A later renewal/application instruction does not negate the earlier
        # completed preservation paragraph. Validate each factual clause; do
        # not turn classification into a finding of successful preservation.
        factual_clauses = [clause for clause in re.split(r"[。;；]", body)
                           if re.search(r"本院|本案|保全(?:情况|结果|措施)[:：]", clause)
                           and re.search(_PRESERVATION_ACTION, clause)
                           and not _notice_context_conflicts(clause, _PRESERVATION_ACTION, reject_negative=False)]
        supported = ((court or "本院" in body) and factual
                     and not re.search(r"(?:本案|该案)(?:并非|不是|不属于)保全", body)
                     and not _NOTICE_REFERENCE.search(body)
                     and (bool(factual_clauses) or not _notice_context_conflicts(body, _PRESERVATION_ACTION, reject_negative=False)))
        return _result("preservation", title, "trial", verified=bool(supported), identity=identity,
                       reason="preservation_notice_verified" if supported else "preservation_notice_context_unverified")
    if title in CLOSURE_NOTICE_TITLES:
        if phase in ("trial", "preservation"):
            return _result(EXECUTION, title, "unknown", verified=False, reason="title_case_number_stage_conflict")
        closed_execution = bool(re.search(
            r"(?:本案|本院|该案)[^。;；]{0,150}(?:执行完毕|执行终结|执行结案|执结|终结(?:本次)?执行|结束执行|执行程序[^。;；]{0,15}(?:结束|结案)|执行[^。;；]{0,100}(?:已结案|予以结案))", body))
        supported = ((court or "本院" in body) and (phase == "enforcement" or closed_execution)
                     and not re.search(r"(?:本案|该案)(?:并非|不是|不属于)执行|(?:本案|该案)(?:为|属于)(?:普通)?(?:诉讼|审判)案件", body)
                     and not _notice_context_conflicts(body, _CLOSURE_ACTION, reject_negative=phase != "enforcement"))
        return _result(EXECUTION, title, "enforcement", verified=bool(supported), identity=identity,
                       reason="execution_closure_notice_verified" if supported else "closure_notice_requires_execution_context")
    if kind == EXECUTION:
        if title == "执行裁定书" and phase == "preservation":
            supported = court and bool(re.search(r"保全|查封|冻结|扣押", body))
            return _result("preservation", title, "trial", verified=supported, identity=identity,
                           reason="preservation_execution_ruling_verified" if supported else "preservation_context_unverified")
        if title in EXECUTION_PROCESS_NOTICES:
            supported = (court and phase == "enforcement"
                         and bool(re.search(EXECUTION_PROCESS_NOTICES[title], body))
                         and not _NOTICE_REFERENCE.search(body))
            # Planned auctions are valid notices, never proof of an actual sale.
            return _result(EXECUTION, title, "enforcement", verified=bool(supported), identity=identity,
                           reason="execution_process_notice_verified" if supported else "execution_context_unverified")
        if phase in ("trial", "preservation"):
            return _result(kind, title, "unknown", verified=False, reason="title_case_number_stage_conflict")
        supported = court or bool(re.search(r"申请执行人|被执行人|申请执行事项|执行请求|请求执行", body))
        return _result(kind, title, "enforcement", verified=supported, identity=identity,
                       reason="execution_title_verified" if supported else "execution_context_unverified")
    if kind == "ruling":
        if not court and not re.search(r"裁定如下|申请人|原告|被告", body):
            return _result(kind, title, "unknown", verified=False, reason="court_context_unverified")
        if phase == "enforcement":
            return _result(EXECUTION, title, "enforcement", identity=identity, reason="execution_case_number_verified")
        # An operative preservation order (not a party's request/quoted rule)
        # can disambiguate a civil ruling, while execution boilerplate cannot.
        preservation_order = bool(re.search(r"裁定如下[:：].{0,60}(?:查封|扣押|冻结|解除.{0,10}保全)", body))
        if phase == "preservation" or preservation_order:
            return _result("preservation", title, "trial", identity=identity, reason="preservation_order_verified")
        if not phase and re.search(r"本院(?:在)?执行.{0,40}(?:一案|过程中)|本案执行过程中", body):
            return _result(kind, title, "unknown", verified=False, reason="procedure_stage_requires_review")
        return _result(kind, title, "trial", identity=identity)
    if kind in ("judgment", "mediation"):
        if phase in ("enforcement", "preservation"):
            return _result(kind, title, "unknown", verified=False, reason="title_case_number_stage_conflict")
        return _result(kind, title, "trial", identity=identity,
                       verified=court or bool(re.search(r"原告|被告|判决如下|调解协议", body)), reason="court_title_verified")
    if kind == "summons":
        if phase in ("enforcement", "preservation"):
            return _result("unknown", title, "enforcement" if phase == "enforcement" else "trial",
                           role="other_procedural", identity=identity, reason="nontrial_hearing_requires_mapping")
        return _result(kind, title, "trial", identity=identity,
                       verified=court or bool(re.search(r"受传唤人|开庭|到庭时间|传唤|出庭", body)), reason="summons_context_verified")
    if kind == "preservation":
        return _result(kind, title, "trial", identity=identity,
                       verified=court or bool(re.search(r"申请人|被申请人|请求.{0,15}(?:保全|冻结|查封)|保全请求", body)),
                       reason="preservation_context_verified")
    if kind == NOTICE:
        supported = bool(re.search(r"律师事务所|贵所|该所", body) and re.search(
            r"委托.{0,60}(?:贵所|律师事务所|代理)|请贵所|由贵所|委托事项|代理事项", body))
        return _result(kind, title, "engagement", verified=supported,
                       reason="agency_notice_in_contract_slot" if supported else "agency_notice_context_unverified")
    if kind == "contract":
        return _result(kind, title, "engagement", verified=bool(re.search(r"律师事务所|律师|贵所", body)),
                       reason="engagement_context_verified")
    if kind == "poa":
        return _result(kind, title, "engagement", verified=bool(re.search(r"委托|受托|代理|授权", body)), reason="authorization_context_verified")
    if kind == "intake_approval":
        supported=bool(re.search(r'委托人|当事人',body) and re.search(r'案由|案情|承办律师',body))
        return _result(kind,title,'engagement',verified=supported,reason='intake_form_original_present')
    if kind == 'closure_report':
        supported=bool(re.search(r'委托人|委托单位',body) and re.search(r'结案小结|承办律师|律师意见',body))
        return _result(kind,title,'other',verified=supported,reason='lawfirm_closure_form_original_present')
    if kind == 'service_list':
        supported=bool(re.search(r'委托人|当事人|案件',body) and re.search(r'文件名称|文书名称|材料名称|核收人|收件人',body))
        return _result(kind,title,'other',verified=supported,reason='lawfirm_service_list_original_present')
    if kind == 'quality_card':
        supported=bool(re.search(r'承办律师|律师事务所',body) and re.search(r'评价|意见|是否|服务质量',body))
        return _result(kind,title,'other',verified=supported,reason='quality_card_original_present')
    if kind == 'client_notice':
        supported=bool(re.search(r'委托人|委托合同',body) and re.search(r'律师事务所|承办律师',body)
                       and re.search(r'权利|风险|告知|知晓|律师费',body))
        return _result(kind,title,'engagement',verified=supported,reason='client_notice_original_present')
    if kind == "complaint":
        return _result(kind, title, "trial", verified=bool(re.search(r"诉讼|诉请|原告|被告|起诉|事实|理由", body)), reason="complaint_context_verified")
    if kind == 'invoice':
        return _result(kind, title, 'other', verified=bool(re.search(r'委托人|委托方', body)
            and re.search(r'业务费|律师费', body)), reason='fee_settlement_document_not_payment_proof')
    return _result(kind, title, "other")


def title_evidence(text, *, case_type=None):
    """Classify only a standalone leading title with local semantic support.

    The first title wins: a later quoted title never replaces an evidence list,
    business contract or judgment heading. No returned fact asserts submission,
    signature, court acceptance, payment or completion of execution.
    """
    lines = [line.strip() for line in str(text or "")[:16000].splitlines() if line.strip()]
    headings = _headings(case_type)
    from fee_settlement_evidence import TITLE as SETTLEMENT_TITLE
    # Only a leading standalone title is a document boundary; a settlement
    # label mentioned in a pleading/evidence list cannot replace that document.
    if lines and SETTLEMENT_TITLE.fullmatch(_compact(lines[0])):
        headings[_compact(lines[0])] = 'invoice'
    if case_type in ("civil", "admin"):
        for line in lines[:3]:
            title = _compact(line)
            if re.fullmatch(r"[\u3400-\u9fff]{2,40}律师事务所函", title):
                headings[title] = "firm_letter"
    for index, line in enumerate(lines[:8]):
        value = _compact(line)
        candidates = [(value, 1)]
        if index + 1 < len(lines) and len(value) <= 14:
            candidates.append((value + _compact(lines[index + 1]), 2))
        for candidate, consumed in candidates:
            if candidate not in headings:
                continue
            prefixes = [_compact(prior) for prior in lines[:index]]
            if any(_EVIDENCE_PREFIX.match(prior) for prior in prefixes):
                return _result("evidence", "证据材料清单", "other", reason="evidence_heading_precedes_title_reference")
            # Letterhead/reference identifiers are page furniture, not another
            # document title. Only a bounded identifier immediately preceding
            # an actual pleading heading qualifies; never skip prose/headings.
            reference_prefix = (headings[candidate] == 'complaint' and 1 <= len(prefixes) <= 2
                and re.fullmatch(r'[A-Z]{2,10}[-_]?\d{6,24}', prefixes[-1])
                and (len(prefixes) == 1 or (re.fullmatch(r'[\u4e00-\u9fff]{2,6}', prefixes[0])
                     and not re.search(r'附件|摘录|案例|示例|证据|目录|引用|参考|说明', prefixes[0])))
                and re.search(r'原告\s*[:：]', '\n'.join(lines[index+consumed:]))
                and re.search(r'被告[一二三四五六七八九十\d]*\s*[:：]', '\n'.join(lines[index+consumed:])))
            if index > 3 or not (all(_prefix_allowed(prior) for prior in prefixes) or reference_prefix):
                return None
            evidence = _classify_heading(candidate, lines, index, consumed, headings[candidate])
            if case_type in ("civil", "admin") and evidence["verified"] and evidence["document_role"] == "case_acceptance_notice":
                evidence.update(doc_type="acceptance_notice", candidate_type="acceptance_notice",
                                reason_code="firm_convention_acceptance_20261026")
            # A repeated heading can be an ordinary continuation header. Keep
            # this cue in memory only; never publish the surrounding body text.
            following = " ".join(lines[index + consumed:index + consumed + 2])
            evidence["_continuation"] = bool(re.search(r"续页|第\s*(?:[2-9]|\d{2,})\s*页", following))
            return evidence
    # A notification screenshot has no paper heading. Require positive hearing
    # details, a court/case anchor and message/UI context; never match a quoted
    # notice inside a pleading or turn delivery reminders into hearing notices.
    body = _compact("".join(lines))
    if (not any(_compact(line) in headings for line in lines[:8])
            and re.search(r"短信|12368|审判流程|电子诉讼|开庭提醒|开庭通知", body[:160])
            and re.search(r"人民法院", body)
            and re.search(r"\(\d{4}\)[\u3400-\u9fff\d]{2,28}民(?:初|终)\d+号", body)
            and re.search(r"\d{4}年\d{1,2}月\d{1,2}日|\d{4}[-/]\d{1,2}[-/]\d{1,2}", body)
            and re.search(r"开庭时间|定于.{0,45}开庭|开庭审理|准时.{0,12}(?:到庭|参加庭审)", body)
            and re.search(r"法庭|审判庭|互联网庭审|线上庭审|庭审平台", body)
            and not re.search(r"拟|取消|另行通知|待定|尚未|暂不|引用|摘录|模板|样例", body)):
        return _result("summons", "开庭通知截图", "trial", reason="hearing_message_details_verified")
    return None


def _hint(row, case_type=None):
    return _compact(row.get("title", "")) in _headings(case_type)


def _review_priority(decisions, case_type=None):
    """Review risky starts first, then nearby boundaries, then ordinary starts."""
    runs, current = [], []
    for index, row in enumerate(decisions):
        if row["document_start"] and current:
            runs.append(current); current = []
        current.append(index)
    if current:
        runs.append(current)
    starts = [run[0] for run in runs]
    unknown = [i for i in starts if decisions[i]["doc_type"] == "unknown"]
    sensitive = [i for i in starts if decisions[i]["doc_type"] in ("contract", NOTICE, EXECUTION)]
    hinted = [i for i, row in enumerate(decisions) if _hint(row, case_type)]
    adjacent = [run[1] for run in runs if len(run) > 1 and
                decisions[run[0]]["doc_type"] in ("unknown", "evidence", "contract", NOTICE, EXECUTION)]
    # Round-robin continuations prevent a single huge evidence bundle consuming
    # the entire budget before the next document's boundary is sampled.
    tails = [run[offset] for offset in range(1, max(map(len, runs), default=0))
             for run in runs if offset < len(run)]
    return list(dict.fromkeys(unknown + sensitive + hinted + adjacent + starts + tails))


def _read_evidence(decisions, pages, budget, case_type=None):
    if type(budget) is not int or not 0 <= budget <= MAX_NEW_READ_BUDGET:
        raise ValueError("标题复核预算必须是 0 至 128 的整数")
    metrics = {"configured_budget": budget, "total_pages": len(decisions), "new_page_reads": 0,
               "cached_page_reads": 0, "pages_reviewed": 0, "read_failures": 0,
               "pages_not_independently_reviewed": len(decisions), "verified_title_pages": 0,
               "corrected_pages": 0, "new_boundaries": 0, "uncertain_pages": 0}
    if budget == 0:
        return {}, metrics
    cached = set(getattr(pages, "read_pages", set()))
    priority = _review_priority(decisions, case_type)
    chosen = [i for i, row in enumerate(decisions) if row["page_id"] in cached]
    chosen += [i for i in priority if decisions[i]["page_id"] not in cached][:budget]
    results = {}
    for index in chosen:
        key = decisions[index]["page_id"]
        metrics["cached_page_reads" if key in cached else "new_page_reads"] += 1
        try:
            text = pages.read(key)
            evidence = title_evidence(text, case_type=case_type)
            if evidence:
                from document_continuity import page_context
                evidence['_page_context'] = page_context(text, evidence)
            results[index] = (evidence, "read")
            metrics["pages_reviewed"] += 1
        except Exception:
            # No exception message, path chosen by a document, or raw OCR output
            # reaches logs or audit entries. Failed reads are not verified pages.
            results[index] = (None, "failed")
            metrics["read_failures"] += 1
    metrics["pages_not_independently_reviewed"] -= metrics["pages_reviewed"]
    return results, metrics


def review_visual_titles(decisions, pages, *, max_new_reads=DEFAULT_NEW_READ_BUDGET, case_type=None):
    """Apply bounded local checks without adding/dropping/reordering source pages.

    Ordinary model results outside the local budget are left alone, and never
    counted as independently reviewed. Specific conflicts/unknowns remain for
    review. The only I/O is the existing authorized CasePages.read(page_id).
    """
    reviewed, metrics = _read_evidence(decisions, pages, max_new_reads, case_type)
    if max_new_reads == 0:
        metrics["uncertain_pages"] = sum(row["confidence"] <= .5 for row in decisions)
        pages.title_review_metrics = metrics
        return [dict(row) for row in decisions], []
    output, audit, projection, current_evidence = [], [], None, None
    projection_keys = ("doc_type", "document_role", "procedure_stage", "confidence")
    conflict_reasons = {"conflicting_leading_case_numbers", "title_case_number_stage_conflict",
                        "procedure_stage_requires_review", "preservation_notice_context_unverified",
                        "closure_notice_requires_execution_context"}

    def record(index, original, row, reason, *, evidence=None):
        path, number = pages.pages[row["page_id"]]
        item = {"source_path": path, "page": number + 1, "reason_code": reason,
                "visual_doc_type": original["doc_type"], "effective_doc_type": row["doc_type"],
                "method": "local_title_context_review" if evidence else "title_review_status",
                "independent_title_verified": bool(evidence and evidence["verified"])}
        if evidence:
            # Identity is used only for comparison in this process. Do not copy
            # case numbers, names, free model titles, or page text into this audit.
            item["title"] = evidence["title"]
            item["procedure_stage"] = row.get("procedure_stage", "unknown")
            if evidence["doc_type"] == NOTICE:
                item["contract_presence_confirmed"] = False
        audit.append(item)

    for index, original in enumerate(decisions):
        row = dict(original)
        if original["document_start"]:
            projection, current_evidence = None, None
        elif projection is not None:
            row.update(projection)
        evidence, read_status = reviewed.get(index, (None, "not_reviewed"))
        if read_status in ("not_reviewed", "failed"):
            # Budget omission does not itself discredit an otherwise recognized
            # document. A concrete title/type conflict is still actionable.
            hinted = _headings(case_type).get(_compact(original.get("title", "")))
            if hinted is not None and hinted != original["doc_type"] and original["doc_type"] != "unknown":
                row["confidence"] = min(row["confidence"], .5)
                record(index, original, row, "title_conflict_not_independently_reviewed")
            if read_status == "not_reviewed":
                output.append(row)
                continue
        if evidence is None:
            if original["document_start"] and original["doc_type"] == NOTICE:
                row.update(doc_type="unknown", confidence=.5, document_role="unknown", procedure_stage="unknown")
                projection = {key: row[key] for key in projection_keys}
                record(index, original, row, "title_review_unavailable" if read_status == "failed" else "agency_notice_title_unverified")
            output.append(row)
            continue
        verified = evidence["verified"]
        if verified:
            metrics["verified_title_pages"] += 1
        concrete_conflict = (evidence["candidate_type"] != row["doc_type"] or
                             evidence["reason_code"] in conflict_reasons or row["doc_type"] in ("unknown", NOTICE))
        if not verified and not concrete_conflict:
            record(index, original, row, "heading_context_not_independently_verified", evidence=evidence)
            output.append(row)
            continue
        if not original["document_start"]:
            same = (current_evidence is not None and current_evidence["title"] == evidence["title"]
                    and row["doc_type"] == evidence["doc_type"])
            different_identity = (same and current_evidence.get("_identity") and evidence.get("_identity")
                                  and current_evidence["_identity"] != evidence["_identity"])
            if same and not different_identity:
                # Repeated court headings alone do not establish a new document.
                # A different leading case number does; no source page is lost.
                if not evidence.get("_continuation"):
                    row["confidence"] = min(row["confidence"], .5)
                    projection = {key: row[key] for key in projection_keys}
                    record(index, original, row, "repeated_heading_boundary_requires_review", evidence=evidence)
                output.append(row)
                continue
            row["document_start"] = True
            metrics["new_boundaries"] += 1
        row.update(doc_type=evidence["doc_type"], title=evidence["title"],
                   document_role=evidence["document_role"], procedure_stage=evidence["procedure_stage"])
        row["confidence"] = (max(.85, min(row["confidence"], .95)) if verified and row["doc_type"] != "unknown" else .5)
        projection = {key: row[key] for key in projection_keys}
        current_evidence = evidence
        record(index, original, row, evidence["reason_code"], evidence=evidence)
        output.append(row)
    from document_continuity import reconcile as reconcile_continuity
    output, continuity_audit = reconcile_continuity(output, pages, reviewed)
    audit.extend(continuity_audit)
    metrics['merged_continuation_pages'] = len(continuity_audit)
    metrics["corrected_pages"] = sum(any(old.get(key) != new.get(key) for key in
        ("doc_type", "document_role", "procedure_stage", "document_start")) for old, new in zip(decisions, output))
    metrics["uncertain_pages"] = sum(row["confidence"] <= .5 for row in output)
    pages.title_review_metrics = metrics
    return output, audit
