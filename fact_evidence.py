"""Conservative, local-only checks for extracted facts, never inferred replacements.

This is an acceptance guard, not an assertion that every accepted fact is true.
Unknown or ambiguous sensitive facts remain absent and require review. No I/O,
model calls, document instructions, date conversion or role inference occurs here.
"""
from __future__ import annotations

import re
import unicodedata


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def _clause(text: str, start: int, end: int) -> str:
    """Keep OCR line wraps, but stop at actual sentence/semicolon boundaries."""
    left = max(text.rfind(mark, 0, start) for mark in "。!！?？;；") + 1
    stops = [position for mark in "。!！?？;；" if (position := text.find(mark, end)) >= 0]
    right = min(stops) if stops else len(text)
    return text[max(left, start - 160):min(right, end + 160)]


def _occurrences(text: str, value: str):
    cursor = 0
    while (cursor := text.find(value, cursor)) >= 0:
        yield cursor
        cursor += max(1, len(value))


_FUTURE = re.compile(r"拟|计划|预计|预期|希望|争取|承诺|应当|应于|应在|将于|将会|待|尚待|如(?:果)?|假如|假设|若|一旦|是否|尚未|未曾|未能|没有|并未|未予|未实际|不代表|不证明")
_NEGATION = re.compile(r"不|未|无|没有|尚未|并非|否认")
_ACTUAL = re.compile(r"已(?:经)?(?:实际)?(?:全部|足额|部分)?(?:履行|支付|付款|收款|收取|收到|受偿|收回)|(?:履行|支付|付款)(?:完毕|完成)|实际(?:收到|收款|受偿|支付)|(?:款项|案款|律师费)?(?:已)?到账|收讫|实收|已收(?:业务费|律师费|金额)?")
_SATISFACTION = re.compile(r"满意|好评|认可(?:律师|服务)")
_ENGAGEMENT_FORM = re.compile(r"委托代理合同|委托合同|法律服务合同|收案审批|立案审批")
_COURT_RECEIPT = re.compile(r"法院|本院|人民法院|仲裁委|仲裁机构|起诉日期|裁判日期|判决日期")
_OUTCOME_EVENT = re.compile(r"判决|判令|裁定|裁决|调解|撤诉|终结|终止|办结|结案|本案已(?:经)?执行完毕|咨询意见|法律意见|代书定稿|提供咨询|出具[^。;；]{0,12}(?:意见|文书)")
_OUTCOME_REFERENCE = re.compile(r"另案|其他案件|其它案件|参考案例|案例参考|引用案例|案例引用|案例摘录|引述[^。;；]{0,12}(?:判决|裁定|裁决)")
_OUTCOME_CLAIM = re.compile(r"(?:原告|被告|申请人|被申请人|上诉人|被上诉人)(?:诉称|辩称|主张|声称|陈述)|(?:诉讼请求|上诉请求|申请事项|答辩意见)[:：]")
# Judicial obligations may say 应当/应于; those are not uncertain dispositions.
_OUTCOME_PROPOSED = re.compile(r"请求|恳请|拟|计划|预计|预期|希望|争取|承诺|如(?!下|实|期|数)(?:果)?|假如|假设|若|一旦|是否|尚待|尚未|未作出|未予|并非|不(?:是|代表|构成)")
_CURRENT_OUTCOME = re.compile(r"(?:本案|本院|本庭|本委)?(?:判决|裁定|裁决)(?:主文|结果)?(?:如下|为|[:：])|(?:本案)?(?:办理结果|结案小结|审\(办\)结果|审办结果)[:：]")
_PRIOR_OUTCOME_LEAD = re.compile(r"(?:原审|一审|前审|前次|上次|上一次|此前|先前)(?:法院)?$")
_OPERATIVE_CONTENT = re.compile(r"支付|偿还|给付|归还|返还|赔偿|补偿|承担|负担|驳回|撤销|维持|确认|准许|不予|责令|履行|解除|交付|腾退|迁出|停止侵害|赔礼道歉|恢复原状|判处|免予|宣告|无罪|有期徒刑|拘役|罚金|死刑|无期徒刑|缓刑|收缴|没收")
# These describe the availability of information, not a negative disposition.
# In particular, "未记载到账" is neither "已到账" nor "尚未到账".
_OUTCOME_INFORMATION_GAP = re.compile(
    r"(?:不|未|没有|尚未)(?:直接|明确|具体|详细|予以)?(?:记载|载明|说明|记述|提及|披露|反映|涉及|显示)"
    r"|(?:尚无|暂无|未见|缺乏|没有)(?:相关|任何|有效|充分)?(?:材料|证据|记录|信息)(?:可以|能够|足以)?(?:记载|显示|表明|证明)?"
    r"|(?:尚无|暂无|缺少)(?:判决|裁定|执行|办理|处理|裁判|结案)(?:情况|结果)?的?(?:信息|记录|材料)"
    r"|(?:尚|仍|目前)?(?:不清楚|不明确|不详|不明|未知|无法确认|不能确认|无法查明|不能查明|未(?:能)?(?:查明|核实|确认|明确))")
_NEGATIVE_OUTCOME_STATUS = re.compile(r"(?:尚未|未|没有|并未)[^。;；]{0,8}(?:履行|支付|收款|受偿)")
_OUTCOME_RECORD_SCOPE = re.compile(r"(?:本|该|此)(?:执行通知书|通知书?|文书|材料|报告|记录|说明|文件)(?:仅|只)(?:记载|载明|说明|记录)")


def _outcome_information_only(value: str, page: str, source_start: int) -> bool:
    """Check the actual sentence, including information qualifiers omitted by a quote.

    Do not scan unrelated sentences elsewhere in the document. A separately
    stated disposition can coexist with missing enforcement information; this
    veto only rejects a candidate without an independent result/status clause.
    The existing outcome guard still validates claims, conditions and context.
    """
    value_end, saw_gap = source_start + len(value), False
    for sentence in re.finditer(r"[^。!！?？;；]+", page):
        fragments = list(re.finditer(r"[^,，]+", sentence.group()))
        previous_gap = False
        previous_record_scope = False
        for index, fragment in enumerate(fragments):
            text = fragment.group()
            continuation = (re.match(r"^(?:或|或者|及|以及|是否)", text)
                            or re.search(r"(?:等信息|(?:情况|情形|部分)?除外)$", text))
            gap = bool(_OUTCOME_INFORMATION_GAP.search(text) or (previous_gap and continuation)
                       or (previous_record_scope and re.search(r"除外$", text)))
            # A bare afterposed qualifier still governs the preceding event;
            # an expressly different object (e.g. payment DATE) does not.
            if index + 1 < len(fragments) and _OUTCOME_INFORMATION_GAP.fullmatch(fragments[index + 1].group()):
                gap = True
            previous_gap = gap
            previous_record_scope = bool(_OUTCOME_RECORD_SCOPE.search(text)
                                         or (previous_record_scope and continuation))
            start = sentence.start() + fragment.start()
            end = sentence.start() + fragment.end()
            left, right = max(source_start, start), min(value_end, end)
            if left >= right:
                continue
            part = page[left:right]
            if gap:
                saw_gap = True
                continue
            if (_OUTCOME_EVENT.search(part) or _ACTUAL.search(part) or _NEGATIVE_OUTCOME_STATUS.search(part)
                    or (_CURRENT_OUTCOME.search(page[:left]) and _OPERATIVE_CONTENT.search(part))):
                return False
    return saw_gap


def _sentence_prefix(text: str, position: int) -> str:
    left = max(text.rfind(mark, 0, position) for mark in "。!！?？;；") + 1
    return text[left:position]


def _outcome_supported(field: str, value: str, quoted: str, contextual: str, page: str, source_start: int) -> bool:
    """An outcome word inside a prayer, allegation or cited case is not a result.

    Check the actual occurrence on the page, including qualifiers cropped out
    of a quote. Only an unqualified operative/result heading resets a preceding
    allegation; an other-case excerpt needs an explicit 本案 heading to reset.
    """
    if _outcome_information_only(value, page, source_start):
        return False
    event = _OUTCOME_EVENT.search(value)
    event_start = source_start + (event.start() if event else 0)
    prefix = page[:event_start]
    current_end = 0
    historical_end = 0
    # A value may include its own heading ("本院判决如下…"). Include that
    # marker's end, but never use a later heading to excuse an earlier claim.
    for marker in _CURRENT_OUTCOME.finditer(page[:source_start + len(value)]):
        if marker.start() > event_start:
            break
        lead = _sentence_prefix(page, marker.start())
        # A prior disposition reproduced inside this judgment is not today's
        # outcome. Only a later explicitly current tribunal heading can reset
        # that scope; it remains legitimate to revoke/affirm the prior judgment.
        if _PRIOR_OUTCOME_LEAD.search(lead):
            historical_end = marker.end()
            continue
        if _OUTCOME_PROPOSED.search(lead) or _OUTCOME_CLAIM.search(lead) or _OUTCOME_REFERENCE.search(lead):
            continue
        if _OUTCOME_REFERENCE.search(page[:marker.start()]) and not marker.group().startswith("本案"):
            continue
        if historical_end > current_end and not marker.group().startswith(("本案", "本院", "本庭", "本委")):
            continue
        current_end = marker.end()
    if historical_end > current_end:
        return False
    scope = prefix[current_end:]
    if _OUTCOME_REFERENCE.search(scope) or _OUTCOME_CLAIM.search(scope):
        return False
    if _OUTCOME_PROPOSED.search(_sentence_prefix(scope, len(scope))):
        return False
    return bool(_labelled((field, "办理结果", "咨询意见", "法律意见"), value, quoted, contextual)
                or event or (current_end and _OPERATIVE_CONTENT.search(value)) or _ACTUAL.search(value)
                or re.search(r"(?:尚未|未|没有|并未)[^。;；]{0,8}(?:履行|支付|收款|受偿)", value))


def _labelled(aliases, value: str, quoted: str, contextual: str) -> bool:
    """A field label must govern this literal value, not merely occur nearby."""
    labels = "|".join(re.escape(label) for label in sorted(aliases, key=len, reverse=True))
    pattern = r"(?:" + labels + r")(?:名称|姓名)?(?:\([^()]{1,12}\))?[:为是]*" + re.escape(value)
    for match in re.finditer(pattern, quoted):
        # Do not match 当事人 within 对方当事人, or convert a proposed role into
        # an accepted role. The qualifier is checked before the matched label.
        if match.start() and quoted[max(0, match.start() - 2):match.start()] == "对方":
            continue
        phrase = match.group()
        for start in _occurrences(contextual, phrase):
            prefix = re.split(r"[,，。;；:]", contextual[max(0, start - 12):start])[-1]
            if re.search(r"拟|计划|预计|假设|假如|并非|不是|尚未|不属于|非$", prefix):
                continue
            return True
    return False


def _single_identity_value(value: str) -> bool:
    """A name value cannot absorb the following role/signature explanation."""
    return bool(2 <= len(value) <= 120 and not re.search(r"[,，。;；:：!！?？、\[\]【】]", value)
                and not re.search(r"诉讼身份|本案(?:原告|被告|当事人)|签署日期|签字|盖章|以下简称|法定代表人[:：]?|之父|之母|等人$", value)
                and value.count("(") == value.count(")"))


def _identity_end(page: str, start: int, value: str) -> bool:
    """Check the actual page, so a short quote cannot conceal a name suffix."""
    tail = page[start + len(value):]
    # A printed signature/alias annotation is separate from the complete name;
    # it is not evidence of a signature. Other parentheses may be part of it.
    annotation = re.match(r"\((?:盖章|签字|签字盖章|以下简称(?:甲方|乙方|委托人|委托方))\)", tail)
    if annotation:
        tail = tail[annotation.end():]
    if not tail or tail[0] in "。;；!！?？":
        return True
    # Commas may introduce a separate role/record field, but not another name.
    # Known labels also handle an OCR line break compacted out of a form.
    label = r"(?:诉讼身份|身份|本公司|本单位|本人|本案|法定代表人|住所|住址|地址|联系地址|联系电话|电话|统一社会信用代码|身份证号|受托人|受托方|受委托人(?:姓名)?|承办律师|律师事务所|委托事项|委托范围|合同编号|起诉日期|材料备注|备注)"
    return bool(re.match(r"[,，](?:" + label + r"|系|为|是)", tail)
                or re.match(label + r"[:：]", tail))


def _local_client_party(value: str, quote: str, page: str, source_start: int, quote_start: int) -> bool:
    """Bind one complete client to an immediately adjacent, explicit party role.

    Use the full literal quote, because _clause deliberately stops before the
    second sentence in '委托人：甲公司。本公司是本案被告'. Never search ahead
    across another subject, infer a role from a bare client, or rewrite evidence.
    """
    if not _single_identity_value(value) or not _identity_end(page, source_start, value):
        return False
    label = r"(?:委托人|委托方|委托单位)(?:名称)?[:：]"
    end = source_start + len(value)
    anchor = re.search(label + re.escape(value) + r"$", page[:end])
    if not anchor or len(list(re.finditer(label, page))) != 1:
        return False
    # A quote cannot conceal an adverse header/condition on the actual page.
    prefix = page[:anchor.start()]
    if re.search(r"另案|其他案件|参考|案例|示例|模板|引用|引述|摘录|转述|声称|诉称|辩称|主张|"
                 r"拟|计划|假设|假如|如果|如法院|若|一旦|追加|(?:并非|不是|尚未|不属于)|代$|对方$|相对方$", prefix):
        return False
    role = re.match(r"(?:。(?P<company>本公司)(?:是|为)本案|[,，](?:本案)?诉讼身份(?:为|是)(?:本案)?)"
                    r"(?:原告|被告)(?=$|[。;；!！?？])", page[end:])
    if not role or (role['company'] and not value.endswith("公司")):
        return False
    binding_end = end + role.end()
    # Both the identity and the full role must be inside this exact occurrence
    # of the submitted quote; another occurrence cannot authorize a short one.
    if anchor.start() < quote_start or binding_end > quote_start + len(quote):
        return False
    # A following sentence may explicitly withdraw this very declaration,
    # even when omitted from the quote. Inspect only its local back-reference;
    # unrelated unpaid fees, unsigned forms or unreceived papers say nothing
    # about party identity and must not erase it.
    following = re.split(r"[。;；!！?？]", page[binding_end:].lstrip("。;；!！?？"), maxsplit=1)[0]
    backref = r"(?:上述|以上|前述|该|此)(?:的)?(?:诉讼身份|当事人身份|身份(?:声明)?|角色(?:声明)?|内容|陈述)"
    qualification = (r"(?:(?:仅|只是|仅仅)?(?:为|是|系|属于|作为)?(?:填写|参考)?(?:示例|假设|假定|拟定方案)|"
                     r"(?:并非|不是)(?:事实|真实(?:身份|陈述)?|本案(?:原告|被告))|"
                     r"(?:尚未|未)(?:确认|确定|核实)|(?:并)?不(?:属实|真实))")
    if re.match(backref + qualification, following):
        return False
    return _client_supported(value, quote, _clause(page, source_start, end),
                             page=page, source_start=source_start)


def _assigned_business_lawyer(value: str, quoted: str, contextual: str, page: str, source_start: int) -> bool:
    """A specialty role alone is not evidence that a lawyer handles this file.

    Require a single literal delegation tying this named lawyer to the engaged
    firm. Other parties' counsel, proposals and example/cited assignments stay
    unresolved. No document title, selected case type or distant name is used.
    """
    # A short quote must not hide an example/other-case heading on the page.
    if re.search(r"另案|其他案件|参考案例|案例参考|引用案例|填写示例|示例文本|参考模板", page[:source_start]):
        return False
    name = re.escape(value)
    role = r"(?:承办律师|代理律师|经办律师|负责律师|辩护人|法律顾问律师|顾问律师|项目律师)"
    scope = r"(?:本案|本项目|本合同|本单位)?(?:一审|二审|侦查阶段|审查起诉阶段)?"
    named_role = (r"(?:" + scope + role + r"[:为是]*" + name + r"|" + name +
                  r"(?:律师)?(?:(?:担任|作为|为)" + scope + role + r"|(?:办理|承办)(?:本案|本项目)))")
    delegation = r"(?:接受|受)[^,，。;；:]{0,35}?(?:委托|聘请)(?:后)?[,，]?(?:并|后)?"
    own_firm = r"(?:本所|我所)(?:已)?(?:" + delegation + r")?(?:现|已)?(?:指派|委派)"
    engaged_firm = r"(?:委托人|委托方|聘方)(?:现|已)?(?:委托|聘请)[^,，。;；:]{2,40}律师事务所(?:指派|委派)"
    named_firm = r"[^,，。;；:]{2,40}律师事务所(?:分所)?" + delegation + r"(?:指派|委派)"
    subjects = [own_firm, engaged_firm, named_firm]
    # A contractual party alias is not a law firm merely because it assigns a
    # person. Resolve it only against an explicit entrusted-firm declaration on
    # this same page, preceding the assignment. Never carry aliases across files.
    for party in ("甲方", "乙方"):
        binding = (r"(?:" + party + r"\((?:受托人|受托方)\)|(?:受托人|受托方)\(" + party +
                   r"\))[:为是]+[^,，。;；:()]{2,40}律师事务所(?:分所)?")
        matches = list(re.finditer(binding, page[:source_start]))
        competing = re.search(re.escape(party) + r"[:为是]+", page[:source_start])
        if len(matches) == 1 and not competing and not re.search(r"对方|相对方|拟|未|参考|案例|示例|模板", _sentence_prefix(page, matches[0].start())):
            subjects.append(re.escape(party) + r"(?:现|已)?(?:指派|委派)")
    pattern = r"(?:" + "|".join(subjects) + r")" + named_role
    uncertain = re.compile(r"拟|计划|预计|假设|假如|是否|并非|不是|尚未|没有|并未|未经委托|未接受委托|请|建议|要求|希望|承诺|对方|相对方|另案|其他案件|参考|案例|示例|模板|引用|主张|声称|陈述|称")
    for match in re.finditer(pattern, quoted):
        for start in _occurrences(contextual, match.group()):
            subject = match.group().split("指派", 1)[0].split("委派", 1)[0]
            if (not uncertain.search(contextual[:start])
                    and not re.search(r"对方|相对方|拟|计划|预计|尚未|没有|未接受|请求|恳请|声称|主张|参考|案例|示例|模板", subject)
                    and not re.search(r"是否|假如|假设", contextual[start:])):
                return True
    return False


def _same_page_entrusted_assignment(value: str, quoted: str, page: str, source_start: int) -> bool:
    """Resolve two explicit assignment forms, never an unbound firm pronoun.

    A notice must name one client and one recipient/entrusted firm, and state
    that client's engagement of 贵所. A power of attorney may instead directly
    name the firm's appointed lawyer as its trustee. All anchors stay on this
    source page; no classification, other-page identity or default firm is used.
    """
    reference = r"另案|其他案件|参考案例|案例参考|仅供参考|引用|引述|转述|声称|自称|据称|示例|范例|范本|模板|(?:第三人|第三方|对方|相对方)(?:称|陈述|提交|提供)"
    adverse = r"拟|计划|预计|假设|假如|是否|尚未|没有|并未|并非|不是|未(?:由|予|能|曾)?|请求|恳请|希望|建议|要求|名义|冒用|声称|主张|对方|相对方|第三人|第三方"
    if re.search(reference, page[:source_start]) or re.search(r"助理|实习|秘书|员工|工作人员|法务|待定|待指定|未指定", value):
        return False
    if re.search(r"(?:上述|该|本次)(?:律师)?(?:指派|委派)(?:并)?(?:未生效|尚未生效|未确定|不存在|已撤销|已撤回|仅为拟议)", page):
        return False
    # A unique direct client label is required, not merely a party's name.
    clients = list(re.finditer(r"(?:委托人|委托方)(?:名称)?[:为是]+([^,，。;；:()]{2,60})", page))
    if (len(clients) != 1 or clients[0].end() > source_start
            or re.search(adverse, _sentence_prefix(page, clients[0].start()))):
        return False
    client = clients[0].group(1)
    firm = r"[^,，。;；:()]{2,40}?律师事务所(?:分所)?"
    declarations = list(re.finditer(
        r"(?:致|受托人|受托方|受托律所|[甲乙]方\((?:受托人|受托方)\))[:为是]+(?P<firm>" + firm + r")", page))
    if (not declarations or len({m.group("firm") for m in declarations}) != 1
            or any(re.search(adverse, _sentence_prefix(page, m.start())) for m in declarations)
            or any(re.match(r"拟|计划|预计|尚未|未(?:确认|委托|聘请)|并非|不是|不属于|对方|相对方|第三人|第三方|请|名义|希望|建议|要求", m.group("firm")) for m in declarations)):
        return False
    name = r"(?P<person>" + re.escape(value) + r")"
    addressed = (r"贵所(?:现|已)?(?:指派|委派)" + name + r"(?:律师)?(?:为|担任|作为)"
                 r"(?:本案|本项目|本合同)(?:一审|二审)?(?:承办律师|代理律师|经办律师|负责律师|辩护人|项目律师)")
    trustee = r"受托人[:为是]+(?P<firm>" + firm + r")(?:现|已)?(?:指派|委派)的(?:律师)?" + name + r"(?:律师)?"
    # Do not accept a name substring, an assistant, or the first of a list.
    end = r"(?=[。;；!！?？]|$)"
    for kind, pattern in (("addressed", addressed), ("trustee", trustee)):
        for match in re.finditer(pattern + end, quoted):
            for start in _occurrences(page, match.group()):
                if start + match.start("person") - match.start() != source_start:
                    continue
                # A shortened quote cannot hide a name/role suffix or another
                # appointee. Check the same phrase's end in the actual page.
                phrase_end = start + len(match.group())
                if phrase_end < len(page) and page[phrase_end] not in "。;；!！?？":
                    continue
                if re.search(adverse + r"|请|若|如果", _sentence_prefix(page, start)):
                    continue
                if kind == "addressed":
                    if any(m.end() > start for m in declarations):
                        continue
                    owner = r"(?:本公司|本单位|本人|委托人|委托方|" + re.escape(client) + r")"
                    engagement = owner + r"(?:现|已|特|兹)?(?:委托|聘请)贵所(?:代理|办理|承办|提供)"
                    bindings = list(re.finditer(engagement, page[:start]))
                    if not any(not re.search(adverse + r"|请|若|如果", _sentence_prefix(page, m.start()))
                               for m in bindings):
                        continue
                else:
                    if ("授权委托书" not in page[:start]
                            or match.group("firm") != declarations[0].group("firm")
                            or len(re.findall(r"受托人[:为是]+", page)) != 1):
                        continue
                return True
    return False


def _explicit_entrusted_firm(value: str, quoted: str, page: str, source_start: int) -> bool:
    if not value.endswith(("律师事务所", "律师事务所分所")):
        return False
    if re.search(r"另案|参考案例|引用案例|示例文本|参考模板", page[:source_start]):
        return False
    pattern = r"(?:[甲乙]方\((?:受托人|受托方)\)|(?:受托人|受托方|受聘方)(?:\([甲乙]方\))?)[:为是]+" + re.escape(value)
    for match in re.finditer(pattern, quoted):
        for start in _occurrences(page, match.group()):
            if not re.search(r"对方|相对方|拟|计划|未|非|参考|案例|示例|模板", _sentence_prefix(page, start)):
                return True
    return False


_COURT_NUMBER = re.compile(r"\(\d{4}\)[\u3400-\u9fffA-Za-z0-9]{2,30}号")
_EXECUTION_NUMBER = re.compile(r"\(\d{4}\)[\u3400-\u9fffA-Za-z0-9]{2,20}?执(?:恢)?\d+号")
_NUMBER_REFERENCE = re.compile(r"另案|其他案件|参考|案例|引用|援引|执行依据|依据|原审|原判|对应判决|相关判决|诉称|辩称|主张|拟|计划|假设")


def _court_header_supported(value: str, raw_page: str, source_start: int) -> bool:
    """Bind a complete court name to this page's actual judicial heading.

    Retain line structure, unlike the generic literal comparison. A title
    mentioned near a court name does not make a directory, letter or cited
    judgment the present document. This establishes the issuing court on the
    supplied page, not that an unmarked full copy belongs to the current case.
    """
    if (not re.fullmatch(r"[\u3400-\u9fffA-Za-z0-9()·-]{3,70}法院", value)
            or value.count("法院") != 1
            or re.search(r"拟|假设|计划|致|送达|引用|参考|模板|摘录", value)):
        return False
    # The local recall and model candidates share the same bounded heading
    # parser. Match the literal occurrence, not a repeated court in the body.
    from source_court_evidence import extract_court_header_candidate
    for number in set(_COURT_NUMBER.findall(_compact(raw_page))):
        candidate = extract_court_header_candidate(raw_page, number)
        if (candidate and _compact(candidate['value']) == value
                and _compact(raw_page).find(value) == source_start):
            return True
    numbered_lines = [(number, _compact(line)) for number, line in enumerate(raw_page.splitlines())
                      if _compact(line)]
    lines = [line for _, line in numbered_lines]
    if len(lines) < 3:
        return False
    index = 0
    while index < min(2, len(lines)) and lines[index] in {"中华人民共和国", "正本", "副本"}:
        index += 1
    if source_start != sum(map(len, lines[:index])):
        return False
    court_lines = 1
    if lines[index] != value:
        # OCR may wrap the complete court name once. Preserve physical line
        # adjacency; never skip a blank, intervening label or punctuation.
        if (index + 1 >= len(lines)
                or numbered_lines[index + 1][0] != numbered_lines[index][0] + 1
                or lines[index] + lines[index + 1] != value):
            return False
        court_lines = 2
    # A cropped quote cannot conceal an explicit disclaimer about this very
    # page. Merely discussing an earlier judgment in the body is not a veto.
    page = _compact(raw_page)
    if re.search(r"(?:本页|本件|本裁判|本文书|上述|以上)(?:内容|文书|判决书)?"
                 r"(?:均|仅|只|所载)?(?:为|系|是)"
                 r"[^。;；!！?？]{0,16}(?:参考|示例|模板|样式|摘录|原审|前审|另案)", page):
        return False
    title_pattern = r"(?:(?:民事|刑事|行政)?(?:判决书|裁定书|调解书)|传票|受理(?:案件)?通知书)"
    title_index = index + court_lines
    if title_index >= len(lines):
        return False
    consumed = 1
    title = lines[title_index]
    if not re.fullmatch(title_pattern, title):
        if title_index + 1 >= len(lines) or not re.fullmatch(title_pattern, title + lines[title_index + 1]):
            return False
        consumed = 2
    number_index = title_index + consumed
    if number_index >= len(lines):
        return False
    number = re.sub(r"^(?:案号|本案案号)[:：]", "", lines[number_index])
    # An execution/preservation court is not automatically the trial court.
    # Missing or unrecognised heading numbers stay for review, not guessed.
    return bool(re.fullmatch(r"\(\d{4}\)[\u3400-\u9fffA-Za-z0-9]{1,20}"
                             r"(?:民|刑|行)(?:初|终|再|申|抗)\d+号", number))


def _case_number_supported(field, value, quoted, contextual, page, source_start):
    if not _COURT_NUMBER.fullmatch(value):
        return False
    execution = bool(_EXECUTION_NUMBER.fullmatch(value))
    if field == "执行案号" and not execution:
        return False
    if field == "案号" and "执" in value:
        return False
    # A numbered citation inside the body is not this document's own number.
    prefix = _sentence_prefix(page, source_start)
    if _NUMBER_REFERENCE.search(prefix):
        return False
    historical = re.search(r"参考案例|引用案例|另案", page[:source_start])
    if historical and not re.search(r"本案(?:执行)?案号[:为是]*$", prefix):
        return False
    labels = ("本案执行案号", "执行案号", "案号") if field == "执行案号" else ("本案案号", "案号", "法院收案号", "案件编号", "仲裁案号")
    if _labelled(labels, value, contextual, contextual):
        return True
    # Unlabelled numbers must occupy the actual document heading, not an
    # arbitrary occurrence. No classification result supplies missing evidence.
    first = _COURT_NUMBER.search(page)
    return bool(page == value or (first and first.start() == source_start and source_start < 180
                and re.search(r"判决书|裁定书|调解书|起诉状|起诉书|执行通知书|执行立案通知书|受理通知书|传票", page[:source_start])))


def _explicit_employer_client_address(value, quoted, contextual, page, source_start):
    """No cross-document/client-name guessing: this page must bind both roles."""
    bindings = list(re.finditer(r"聘方(?:暨|即)委托人[:为是]+[^,，。;；:]{2,60}", page[:source_start]))
    if len(bindings) != 1:
        return False
    binding = bindings[0]
    if re.search(r"对方|相对方|拟|计划|尚未|未|参考|案例|示例|模板", _sentence_prefix(page, binding.start())):
        return False
    if re.search(r"对方|相对方|律所|事务所|受聘方|受托人|受托方", _sentence_prefix(page, source_start)):
        return False
    if re.search(r"对方|相对方|受聘方|受托人|受托方|律师事务所", page[binding.end():source_start]):
        return False
    return _labelled(("聘方住所", "聘方地址", "聘方联系地址", "联系地址"), value, quoted, contextual)


def validated_fact_field(field, value, quote, page_text):
    """Return the evidence-checked storage key; never rewrite source values.

    A model's generic 案号 may designate a literal execution number. Route that
    number before conflict/deduplication checks; all other explicit fields retain
    their key, and citations/unknown procedure codes remain unaccepted.
    """
    if not all(isinstance(item, str) for item in (field, value, quote, page_text)):
        return None
    target = "执行案号" if field == "案号" and _EXECUTION_NUMBER.fullmatch(_compact(value)) else field
    return target if validate_fact(target, value, quote, page_text) else None


def _fee_terms_preserved(value: str, page: str, source_start: int) -> bool:
    """Keep explicit fee periods/stages/conditions rather than accepting a cut amount.

    Only fee-term clauses are checked. A separate statement that payment proof
    is absent is not a price term, and never establishes paid/unpaid status.
    """
    # An explicit fee section can contain several sentences. The first amount
    # alone drops a later risk fee or payment prerequisite. Keep the entire
    # bounded section; punctuation may differ only at its final boundary.
    sections = list(re.finditer(r"收费约定[:：]", page[:source_start + 1]))
    if sections:
        section = sections[-1]
        following = page[section.end():]
        boundary = re.search(r"(?:合同(?:载明)?签订日期|合同签署日期|合同填写日期|合同编号|收案日期|结案日期|委托事项|代理阶段|审级|承办律师|律师事务所|委托人|案由)[:：]", following)
        entry = following[:boundary.start()] if boundary else following
        end = section.end() + len(entry)
        if section.end() <= source_start < end:
            lead = _sentence_prefix(page, section.start())
            if re.search(r"(?:拟|计划|预计|未约定|没有约定|不是|不代表|对方|相对方)[^。;；,，:：]{0,12}$", lead):
                return False
            return (0 < len(entry) <= 800 and
                    value.rstrip('。;；') == entry.rstrip('。;；'))
    # Form text has already had line wraps removed. Limit this check to the
    # governing fee entry, not an earlier 代理阶段 or a later 收案日期 field.
    label_pattern = r"收费标准|服务费标准|法律顾问费|顾问律师费|法律服务费|律师费|代理费|辩护费|顾问费"
    end = source_start + len(value)
    labels = list(re.finditer(label_pattern, page[max(0, source_start - 60):end]))
    if not labels:
        return True  # The existing field-label guard still rejects no anchor.
    offset = max(0, source_start - 60)
    inside = [match for match in labels if offset + match.start() >= source_start]
    label_start = offset + (inside[0] if inside else labels[-1]).start()
    lead = _sentence_prefix(page, label_start)
    agreement = re.search(r"约定[^。;；,，:：]{0,20}$", lead)
    start = label_start - len(agreement.group()) if agreement else label_start
    stops = [position for mark in "。!！?？;；" if (position := page.find(mark, end)) >= 0]
    right = min(stops) if stops else len(page)
    next_field = re.search(r"(?:收案日期|结案日期|合同填写日期|合同(?:载明)?签订日期|合同签署日期|合同编号|委托事项|代理阶段|审级|承办律师|律师事务所|委托人|案由)[:：]", page[end:right])
    if next_field:
        right = end + next_field.start()
    contextual = page[start:right]
    qualifiers = re.compile(
        r"/(?:年|月|季|日|小时|件)|每(?:年|月|季|日|小时|件|期)|"
        r"\d{4}年度?|一审|二审|再审|侦查阶段|审查起诉阶段|"
        r"分[零一二三四五六七八九十\d]+期|首期|尾款|"
        r"按|仅|如|若|一旦|回款|另行约定|后(?:支付|计收|收取)")
    for clause in re.split(r"[,，。;；]", contextual):
        if not qualifiers.search(clause):
            continue
        # A complete phrase and a label+terms value describe the same literal
        # fee. Do not require a repeated 约定 outside the submitted value.
        terms = re.sub(r"^(?:双方)?约定[:：]?", "", clause)
        if terms and terms not in value:
            return False
    return True


def _semantic_supported(field: str, value: str, quoted: str, contextual: str, page: str, source_start: int, *, raw_page: str = '') -> bool:
    """Every extraction field requires its own role/amount/event evidence.

    Literal occurrence alone only proves that a string is present. Ambiguous
    roles and unknown fields fail closed; the caller retains them for review.
    """
    label = lambda aliases: _labelled(aliases, value, quoted, contextual)
    escaped = re.escape(value)
    if field == "律师事务所":
        if _explicit_entrusted_firm(value, quoted, page, source_start):
            return True
        if label(("律师事务所", "受托律所", "承办律所", "代理律所")):
            return True
        return bool(value.endswith(("律师事务所", "律师事务所分所")) and
                    re.search(r"(?:委托诉讼代理人|委托代理人|受托人|承办律师)[:为是]*[^。;；]{0,40}" + escaped + r"律师", quoted))
    if field == "承办律师":
        if not re.fullmatch(r"[\u3400-\u9fffA-Za-z·.、,，]{2,50}", value) or "事务所" in value:
            return False
        return label(("承办律师", "代理律师", "经办律师", "负责律师")) or bool(
            _labelled(("委托诉讼代理人", "委托代理人", "受托人"), value, quoted, contextual)
            and re.search(escaped + r"[,，]?[^。;；]{0,35}律师", quoted)) or _assigned_business_lawyer(value, quoted, contextual, page, source_start) or _same_page_entrusted_assignment(value, quoted, page, source_start)
    if field == "当事人":
        if not _single_identity_value(value) or not _identity_end(page, source_start, value):
            return False
        if label(("当事人",)):
            return True
        # Client and litigation party are distinct. Only an explicit same-person
        # declaration binds both; a bare client/relative/representative does not.
        dual = r"(?:委托人|委托方|委托单位)(?:暨|即)(?:本案)?(?:被告人|原告|被告|被申请人|申请人|被上诉人|上诉人)[:：]+"
        return bool(re.search(dual + escaped, quoted)
                    and _client_supported(value, quoted, contextual, page=page, source_start=source_start))
    if field == "对方当事人":
        # Defendant/applicant labels alone do not establish the client's side.
        return label(("对方当事人", "对方", "相对方", "相对人"))
    if field == "案由":
        return label(("案由", "纠纷类型", "争议类型", "罪名", "项目事项", "顾问事项")) or bool(
            value.endswith("纠纷") and re.search(r"(?:因|关于|与)[^。;；]{0,30}" + escaped + r"(?:一案|案件)", quoted))
    if field == "案件或项目名称":
        return label(("案件或项目名称", "项目名称", "案件名称"))
    if field in ("案号", "法院收案号", "执行案号"):
        return _case_number_supported(field, value, quoted, contextual, page, source_start)
    if field == "审理法院":
        if not value.endswith("法院"):
            return False
        return label(("审理法院", "受理法院", "管辖法院", "审判法院"))
    if field == "合同号":
        return bool(re.search(r"\d", value) and
                    (label(("委托合同编号", "委托代理合同编号", "委托合同号")) or
                     (_ENGAGEMENT_FORM.search(page) and label(("合同编号", "合同号")))))
    if field == "收费标准":
        prefix = _sentence_prefix(page, source_start)
        # Check the original occurrence before shortening the fee entry. A
        # cropped quote cannot remove its prerequisite or a narrated claim;
        # colons/commas do not end either scope, unlike sentence boundaries.
        if (re.search(r"(?:若|如(?:果)?|假如|一旦|仅当|只有)[^。;；]{0,40}$", prefix)
                or re.search(r"(?:声称|转述|引述|诉称|辩称|主张)[^。;；]{0,24}$", prefix)):
            return False
        # An agreed price and an actual receipt are different facts. This
        # branch never turns either one into a currently due/payment amount.
        if (_ACTUAL.search(value) or re.search(r"已付|已收|实收|收讫", value)
                or not _fee_terms_preserved(value, page, source_start)):
            return False
        fee = re.search(r"(?:\d|[零一二三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟]+)[\d.,]*\s*(?:万元|元|%|小时|件)|百分之[零一二三四五六七八九十百]+|免费|免收|不收费|无偿", value)
        labels = ("收费标准", "收费约定", "服务费标准", "律师费", "代理费", "辩护费", "法律服务费", "法律顾问费", "顾问律师费", "顾问费")
        governed = r"(?:" + "|".join(labels) + r")[:为是]*(?:人民币)?" + escaped
        if re.search(r"另案|参考案例|引用案例|示例文本|参考模板", page[:source_start]):
            return False
        fee_context = prefix[-80:] + (value[:fee.start()] if fee else "")
        qualifier = r"(?:对方|相对方|拟|计划|预计|尚未|未约定|没有约定|不(?:是|代表))"
        if re.search(qualifier + r"[^:。;；,，]{0,16}(?:" + "|".join(labels) + r")[:为是]*(?:人民币)?$", fee_context):
            return False
        # The model may preserve the whole agreement sentence, including its
        # operative verb. Recognize that bounded form without stripping terms.
        complete = re.match(r"^约定(?:(?:本案|本项目|一审|二审|再审|侦查阶段|审查起诉阶段)|\d{4}年度?){0,2}(?:" + "|".join(labels) + r")", value)
        # A standalone base fee + actual-recovery clause can name its own fee
        # without a separate “收费约定:” label. Accept the complete structure
        # only in an engagement document, with no narrated/conditional prefix
        # or omitted following fee sentence.
        base_recovery = False
        if not prefix and re.fullmatch(r"基础(?:代理费|律师费)\d+(?:\.\d+)?(?:万元|元)[,，]按实际回款金额另收\d+(?:\.\d+)?%[。]?", value):
            from document_title_review import title_evidence
            heading = title_evidence(raw_page)
            following = page[source_start + len(value):].lstrip('。;；')
            boundary = not following or re.match(r"(?:合同(?:载明)?签订日期|合同签署日期|合同编号|承办律师|委托事项|代理阶段)[:：]", following)
            base_recovery = bool(heading and heading['verified'] and heading['doc_type']=='contract' and boundary)
        return bool(fee and (complete or base_recovery or label(labels) or re.search(governed, quoted) or
                             re.search(r"(?:约定|收取|计收|支付)[^。;；]{0,12}" + escaped, quoted) and re.search("|".join(labels), value)))
    if field == '委托人传真':
        digits = re.sub(r'\D', '', value)
        prefix = _sentence_prefix(page, source_start)
        return bool(7 <= len(digits) <= 18 and re.fullmatch(r'[+\d()\-]+', value)
                    and re.search(r'(?:^|[,，:：])(?:本案)?(?:委托人|委托方)(?:联系)?传真(?:号码)?[:为是]*$', prefix)
                    and label(('委托人传真', '委托方传真', '委托人联系传真', '委托方联系传真',
                               '委托人传真号码', '委托方传真号码')))
    if field == "委托人电话":
        digits = re.sub(r"\D", "", value)
        return bool(7 <= len(digits) <= 18 and label(("委托人电话", "委托人联系电话", "委托方电话", "委托方联系电话")))
    if field == "地址":
        return (label(("委托人地址", "委托人住所", "委托人联系地址", "委托方地址", "委托方住所"))
                or _explicit_employer_client_address(value, quoted, contextual, page, source_start))
    if field in ("结案小结", "审（办）结果", "审(办)结果", "审办结果", "办案小结"):
        return _outcome_supported(field, value, quoted, contextual, page, source_start)
    if any(word in field for word in ("实收", "已收", "收款", "回款", "受偿", "到账", "履行", "满意", "服务质量意见", "服务评价", "客户评价")):
        # These fields are governed by the stricter event/feedback guards below.
        if any(word in field for word in ("实收", "已收", "收款", "回款", "受偿", "到账")):
            return bool(re.search(r"\d|[壹贰叁肆伍陆柒捌玖拾佰仟]", value) or _ACTUAL.search(value) or re.search(r"未|没有", value))
        if "履行" in field:
            return bool(_ACTUAL.search(value) or re.search(r"(?:尚未|未|没有|并未)[^。;；]{0,8}履行", value))
        return True
    # Future field additions do not silently acquire an unrestricted validator.
    return label((field,))


def _date_supported(field: str, value: str, quote_clause: str, page_clause: str, page: str) -> bool:
    if not re.search(r"\d|[〇零一二三四五六七八九十]", value):
        return False
    escaped = re.escape(value)

    def asserted(pattern: str, *, bare_receipt: bool = False) -> bool:
        for match in re.finditer(pattern, quote_clause):
            phrase = match.group()
            for position in _occurrences(page_clause, phrase):
                # A later disclaimer about payment does not qualify an earlier
                # receiving date. Inspect the event's own nearby prefix only.
                prefix = page_clause[max(0, position - 12):position]
                prefix = re.split(r"[,，]", prefix)[-1]
                if _FUTURE.search(prefix + phrase):
                    continue
                if bare_receipt and _COURT_RECEIPT.search(prefix):
                    continue
                return True
        return False

    if field == "收案日期":
        office_labels = r"(?:律师事务所|律所|本所)(?:的)?收案|(?:接受|接获)(?:本案)?委托"
        if asserted(r"(?:" + office_labels + r")(?:日期|时间|日)?[:为是于]*" + escaped):
            return True
        if asserted(r"(?:律师事务所|律所|本所)于" + escaped + r"(?:正式)?(?:接受委托|收案)"):
            return True
        # A bare 收案日期 is acceptable in a law-office engagement form, but a
        # court's receiving/filing date or a date elsewhere in the quote is not.
        return bool(_ENGAGEMENT_FORM.search(page)
                    and asserted(r"收案(?:日期|时间|日)?[:为是于]*" + escaped, bare_receipt=True))
    return asserted(r"(?:结案|办结)(?:日期|时间|日)?[:为是于]*" + escaped) or asserted(r"于" + escaped + r"(?:正式)?(?:结案|办结)")


def _client_supported(value: str, quote_clause: str, page_clause: str, *, page: str = "", source_start: int = 0) -> bool:
    if not _single_identity_value(value):
        return False
    escaped = re.escape(value)
    # “受委托人” is the agent, never an alternative spelling of the client.
    # Check the full source as well as the quote, which may crop off “受”.
    explicit_pattern = r"(?<!受)(?:委托人|委托方|委托单位)(?:名称)?(?:\(甲方\))?[)】\]:：]*" + escaped
    narrative_pattern = escaped + r"(?:现|已|特)?委托(?:本所|我所|[^,，。;；]{0,24}(?:律师事务所|律师))"
    explicit = (re.search(explicit_pattern, quote_clause)
                and re.search(explicit_pattern + r"$", page[:source_start + len(value)]))
    narrative = (re.search(narrative_pattern, quote_clause)
                 and re.match(narrative_pattern, page[source_start:]))
    if explicit and not _identity_end(page, source_start, value):
        explicit = None
    if narrative:
        # A delegated person's name in “甲代/为乙委托…” is not the subject.
        # Require the full narrative subject, not a suffix of a company/name.
        previous = page[source_start - 1:source_start] if source_start else ""
        if previous and previous not in ",，。;；!！?？:":
            narrative = None
    if not (explicit or narrative):
        # A literal identity declaration may bind one person to two roles. A
        # defendant label alone, a relative acting for them, or a cropped name
        # does not establish the client. Check boundaries in the source clause
        # as well as the quote, so a shortened quote cannot hide a suffix.
        role = r"(?:被告人|原告|被告|被申请人|申请人|被上诉人|上诉人)"
        pattern = (r"(?:委托人|委托方|委托单位)(?:暨|即)(?:本案)?" + role +
                   r"[:：]+" + escaped + r"(?=$|[。!！?？;；])")
        if not re.search(pattern, quote_clause):
            return False
        if re.search(r"另案|其他案件|参考案例|引用案例|填写示例|示例文本|参考模板|(?:对方|相对方)(?:材料|提供|提交)|拟(?:列|认定|委托)|计划(?:委托|列)|声称|转述|引述|诉称|辩称|主张", page[:source_start]):
            return False
        governed = False
        for match in re.finditer(pattern, page_clause):
            prefix = page_clause[:match.start()]
            if not re.search(r"拟|计划|预计|假设|假如|并非|不是|尚未|不属于|对方|相对方|参考|案例|示例|模板|引用|引述|另案|其他案件|声称|转述|诉称|辩称|主张|非$", prefix):
                governed = True
                break
        if not governed:
            return False
    # Do not turn '拟委托' or a rejected/negated role into an actual engagement.
    return not re.search(r"(?:拟|计划|尚未|未|并非|不是)[^,，。;；]{0,10}(?:委托|" + escaped + r")", page_clause)


def _preserves_qualifiers(value: str, page_clause: str, trigger: re.Pattern) -> bool:
    """Reject '已支付' cut from '如已支付…' and '满意' cut from '不满意'."""
    for match in trigger.finditer(page_clause):
        prefix = page_clause[max(0, match.start() - 28):match.start()]
        source_qualifiers = [item.group() for item in _FUTURE.finditer(prefix)]
        source_qualifiers += [item.group() for item in _NEGATION.finditer(prefix[-6:])]
        if source_qualifiers and not all(qualifier in value for qualifier in source_qualifiers):
            return False
    return True


def _sensitive_supported(field: str, value: str, quote_clause: str, page_clause: str) -> bool:
    satisfaction_field = any(word in field for word in ("满意", "服务质量意见", "服务评价", "客户评价"))
    money_field = any(word in field for word in ("实收", "已收", "收款", "回款", "受偿", "到账"))
    performance_field = "履行" in field
    positive = _ACTUAL.search(value)
    satisfaction = _SATISFACTION.search(value)
    if satisfaction_field or satisfaction:
        if not _preserves_qualifiers(value, page_clause, _SATISFACTION):
            return False
        if not re.search(r"(?:委托人|客户|委托方)(?:对[^,，。;；]{0,24})?(?:表示|评价|意见|反馈|认为|称|确认|评为|提出|建议|要求)|(?:委托人|客户|委托方)(?:对[^,，。;；]{0,20})?不?满意", quote_clause):
            return False
        if _FUTURE.search(page_clause) and not _FUTURE.search(value):
            return False
    if positive or money_field or performance_field:
        if not _preserves_qualifiers(value, page_clause, _ACTUAL):
            return False
        # Explicit negative status is useful evidence; keep its qualifier.
        if re.search(r"(?:尚未|未|没有|并未)(?:实际|全部|足额|部分)?(?:履行|支付|付款|收到|收款|到账|受偿)", value):
            return True
        if not _ACTUAL.search(quote_clause):
            return False
        if _FUTURE.search(page_clause):
            return False
        if re.search(r"(?:判决|裁定|判令|责令|调解协议|约定)[^。;；]{0,50}(?:支付|付款|履行)", page_clause):
            return False
    return True


def validate_fact(field, value, quote, page_text) -> bool:
    """Accept literal evidence only when its field-specific meaning is supported.

    All fields require exact source inclusion (ignoring OCR whitespace and
    full-width forms) plus a semantic role/event anchor. These checks may reject
    valid but ambiguous text; callers must not fabricate a substitute value.
    """
    if not all(isinstance(item, str) and item.strip() for item in (field, value, quote, page_text)):
        return False
    from fee_settlement_evidence import FIELDS as SETTLEMENT_FIELDS, validate_settlement_fact
    if field in SETTLEMENT_FIELDS:
        return validate_settlement_fact(field, value, quote, page_text)
    if field in ('委托人','承办律师','律师事务所'):
        from source_engagement_evidence import poa_fact_supported
        if poa_fact_supported(field,value,quote,page_text):return True
    if _compact(field) == "审级":
        # Retainer scope is not a judicial stage. Preserve the whole quote and
        # actual page occurrence so cropped history/conditions cannot vanish.
        from trial_level_evidence import validate_trial_level
        return validate_trial_level(value, quote, page_text)
    if _compact(field) == "对方当事人":
        # Preserve the complete quote: independent client, litigation-role and
        # opposing-party declarations may span adjacent sentences. The helper
        # requires every link in this same source; it never joins arbitrary
        # names from another page or guesses which litigant we represent.
        from linked_party_evidence import same_page_opponent_supported
        if same_page_opponent_supported(value, quote, page_text):
            return True
    # Stage identity labels rely on original page/line structure. The pure
    # helper performs its own literal and semantic checks before any whitespace
    # compaction in this legacy path, so an intervening header cannot erase the
    # service-subject boundary. Other fields retain their existing validation.
    if _compact(field) in ("阶段工作情况", "顾问协议状态"):
        from stage_fact_evidence import validate_stage_fact
        return validate_stage_fact(_compact(field), value, quote, page_text)
    def comparison_text(text):
        compact = _compact(text)
        # Identity, project-name, fee and other fields retain the original
        # comparison policy, even when their literal value resembles a number.
        if field not in ("结案小结", "审(办)结果", "审办结果", "办案小结"):
            return compact
        # OCR sometimes reads a legal document's paired year delimiter 〔〕 as
        # (). Only an explicit administrative/prosecutorial number with a fixed
        # identifier suffix and 第<digits>号 qualifies. Do not make arbitrary
        # parentheses, names, years, tail numbers or amounts fuzzy. This is a
        # comparison-only copy; callers retain the original value and quote.
        legal_year = (r"(?P<prefix>[\u3400-\u9fffA-Za-z]{1,30}(?:罚字|罚决字|罚决|刑诉字|刑诉))"
                      r"(?:〔(?P<square>[0-9]{4})〕|\((?P<round>[0-9]{4})\))"
                      r"(?P<tail>第[0-9]{1,20}号)"
                      r"(?=$|[。!！?？;；,，:：)】\]]|"
                      r"(?:行政处罚决定书?|处罚决定书?|不起诉决定书|起诉书|通知书)"
                      r"(?=$|[。!！?？;；,，:：)】\]]))")
        return re.sub(legal_year, lambda match: match['prefix'] + '(' +
                      (match['square'] or match['round']) + ')' + match['tail'], compact)

    field = _compact(field)
    value, quote, page = map(comparison_text, (value, quote, page_text))
    if quote not in page or value not in quote:
        return False
    for quote_start in _occurrences(page, quote):
        for value_start in _occurrences(quote, value):
            page_start = quote_start + value_start
            quoted = _clause(quote, value_start, value_start + len(value))
            contextual = _clause(page, page_start, page_start + len(value))
            if field in ("收案日期", "结案日期"):
                supported = _date_supported(field, value, quoted, contextual, page)
            elif field in ("委托人", "委托人名称", "委托方"):
                supported = _client_supported(value, quoted, contextual, page=page, source_start=page_start)
            else:
                supported = (_semantic_supported(field, value, quoted, contextual, page, page_start, raw_page=page_text)
                             and _sensitive_supported(field, value, quoted, contextual))
                if field == "审理法院" and not supported:
                    supported = _court_header_supported(value, page_text, page_start)
                if field == "当事人" and not supported:
                    supported = _local_client_party(value, quote, page, page_start, quote_start)
            if supported:
                return True
    return False
