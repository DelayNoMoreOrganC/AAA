"""Bounded, extractive intake drafts from one complete, classified pleading.

No requests, OCR, execution of document instructions, or invented case facts.
The text remains an attributed allegation, never a judicial finding.
"""
from __future__ import annotations

import re
from copy import deepcopy

from document_title_review import title_evidence

BINDING = "complaint_intake_excerpt"
LIMIT = 260


def compact(text):
    return re.sub(r"\s+", "", str(text or ""))


def _page_use_notice(line):
    """Recognize only a whole, bounded document-use label, not legal prose.

    Position is checked by the caller. Restrict both the subject and suffix:
    a contract use restriction or a party's allegation about fabricated evidence
    must not disappear just because it contains '仅供' or '虚构'.
    """
    purpose = r"(?:内部培训|教学|演示|系统测试|排版校验|验收)"
    label = (r"(?:(?:本|此)(?:材料|文档|文件))?仅(?:供|用于)" + purpose + r"(?:使用)?"
             r"|(?:完全)?(?:虚构|模拟)(?:教学|培训|演示|测试|验收)?材料")
    suffix = r"(?:[，,](?:无真实(?:身份|个人信息|印章)(?:[、或及](?:身份|个人信息|印章))*|不涉及真实(?:个人信息|身份信息)))?"
    return bool(re.fullmatch(r"(?:" + label + r")" + suffix + r"[。.]?", line))


def _body_text(pages):
    """Discard repeated running headers only in the derived reading view.

    Keep the complete, unchanged pages for provenance. Do not remove repeated
    sentences, party declarations or section headings as if they were furniture.
    """
    lines = [[compact(line) for line in p["quote"].splitlines() if compact(line)] for p in pages]
    counts = {}
    for page in lines:
        for line in set(page[:3] + page[-1:]):
            if not re.search(r"[。；;：:]|事实|理由|请求|诉请", line):
                counts[line] = counts.get(line, 0) + 1
    return "".join(line for page in lines for i, line in enumerate(page)
                   if not ((i < 3 or i == len(page) - 1)
                           and (counts.get(line, 0) > 1 or _page_use_notice(line))))


def _complete_clauses(text):
    """Split only outside balanced brackets; never cut a condition in half.

    Return complete clauses and the unpunctuated tail. Invalid nesting is not
    repaired or guessed. Periods in decimals and numbered items are not stops.
    """
    pairs = {'（': '）', '(': ')', '【': '】'}
    stack, clauses, start = [], [], 0
    for index, char in enumerate(text):
        if char in pairs:
            stack.append(pairs[char])
        elif char in pairs.values():
            if not stack or stack.pop() != char:
                return None
        elif char in '。；;' and not stack:
            clauses.append(text[start:index + 1])
            start = index + 1
    return None if stack else (clauses, text[start:])


def collect(fields, *, page_cache, allowed_sources, document_units):
    """Store a bounded source bundle, not a field or a confirmation."""
    from pleading_sources import collect as collect_sources, pack
    fields.pop("_intake_complaint_source", None)
    documents = collect_sources(document_units, page_cache, allowed_sources)
    if not documents: return
    source = pack(documents)
    if summarize(source):
        fields["_intake_complaint_source"] = source


def summarize(source):
    if not isinstance(source, dict):
        return None
    if 'documents' in source:
        return common_brief(source)
    pages = source.get("pages")
    if not isinstance(pages, list) or not 1 <= len(pages) <= 8:
        return None
    if any(not isinstance(p, dict) or not isinstance(p.get("source_path"), str) or not p["source_path"]
           or type(p.get("page")) is not int or p["page"] < 1
           or not isinstance(p.get("quote"), str) or not 0 < len(p["quote"]) <= 18000 for p in pages):
        return None
    if any(p["source_path"] != pages[0]["source_path"] or p["page"] != pages[0]["page"] + n
           for n, p in enumerate(pages)):
        return None
    title = title_evidence(pages[0]["quote"])
    if not title or not title["verified"] or title["doc_type"] != "complaint":
        return None
    text = _body_text(pages)
    # Support either common order. Keep the literal phrases intact, including
    # conditions, negative wording, amounts and attribution inside a sentence.
    request_heading = r"(?:诉讼请求|诉请事项|请求事项)"
    fact_heading = r"事实(?:与|和|及|、)?理由"
    requests = re.search(request_heading + r"[:：]?(.*?)(?=" + fact_heading + r"[:：]?|此致|$)", text)
    # A cross-reference is not a fact paragraph. Follow a genuine continuation
    # heading within this same, already validated pleading; never another unit.
    facts = re.search(fact_heading + r"(?:[（(]续[）)])?(?![:：]?(?:详见|参见|见|请见|另见))[:：]?(.*?)(?=" + request_heading + r"[:：]?|此致|$)", text)
    if not requests or not facts:
        return None

    normalized_facts = re.sub(r"^[一二三四五六七八九十\d]+[、.．)）]", "", facts[1])
    normalized_requests=re.sub(r"^[一二三四五六七八九十\d]+[、.．)）]", "", requests[1])
    fact_clauses = _complete_clauses(normalized_facts)
    request_clauses = _complete_clauses(normalized_requests)
    if fact_clauses is None or request_clauses is None:
        return None
    fact = ""
    for sentence in fact_clauses[0]:
        if len(fact + sentence) > 150:
            break
        fact += sentence
    if len(fact) < 4:
        fact = ""
    # Keep every short request literally, including negative, alternative and
    # limited liability clauses. A short first item alone is not the whole claim.
    request = (normalized_requests if request_clauses[0] and not request_clauses[1]
               and 4 <= len(normalized_requests) <= 110 else "")
    # Structured loan pleadings often put a long interest formula in item 1.
    # Summarize only the explicit relief categories; never crop that formula
    # into a misleading amount/rate or report claimed debt as adjudicated debt.
    loan = requests[1]
    loan_principal = re.search(r"(?:判令|请求判令|请求判决)被告[^。；;]{0,45}(?:清偿|偿还|支付)(?:拖欠的?|尚欠的?)?(?:贷款|借款)?本金", loan)
    loan_fee = re.search(r"[;；]2[、.．]判令被告向原告支付律师费\d", loan)
    loan_security = re.search(r"[;；]3[、.．]判令原告对被告提供抵押的[^;；]{1,160}处置款享有优先受偿权[;；]", loan)
    loan_costs = re.search(r"[;；]4[、.．]判令被告承担本案全部诉讼费用。$", loan)
    qualified_relief = re.search(
        r"不要求|不请求|不承担|不包括|不得|不再|不应|不超过|无需|无须|未到期|撤回|变更|抵扣|扣减|仅限|若|如果|除非|"
        r"以[^。；;]{0,30}为限|在[^。；;]{0,30}范围内", loan)
    if not request and not qualified_relief and all((loan_principal, loan_fee, loan_security, loan_costs)):
        first_item = loan[loan_principal.start():loan_fee.start()]
        if all(word in first_item for word in ("利息", "罚息", "复利")):
            request = "清偿借款本金及利息、罚息、复利，支付律师费，对抵押物处置款优先受偿，并由被告承担诉讼费用。"
    if not request and loan_principal and not qualified_relief:
        # Describe the categories of relief, never crop an interest formula or
        # silently remove a guarantor/security claim. Exact sums remain in source.
        relief = ["偿还借款本金"]
        for word in ("利息", "罚息", "复利"):
            if word in loan: relief.append(word)
        if "律师费" in loan: relief.append("律师费")
        if "连带" in loan: relief.append("承担连带责任")
        if "优先受偿" in loan: relief.append("对担保财产优先受偿")
        if "诉讼费" in loan: relief.append("承担诉讼费用")
        request = "请求" + "、".join(relief) + "，具体金额及计算方式见诉状。"
    if fact and "被告逾期还款时间：" in facts[1] and len(fact) <= 120:
        fact += "诉状列明被告逾期还款情况。"
    # A single snippet may omit the dispute or requested relief. Do not turn
    # it into a seemingly complete intake summary or cut a monetary sentence.
    if not fact or not request:
        return None
    label = "诉请概括：" if request not in requests[1] else "诉请摘录："
    value = "原告诉称：" + fact + label + request
    return value if len(value) <= LIMIT else None


def draft(fields, units, scope):
    source = fields.get("_intake_complaint_source")
    value = summarize(source)
    if not value:
        return None
    from pleading_sources import unpack, references
    documents = unpack(source)
    pages = references(source)
    candidates = [u for u in units if u.doc_type == "complaint"]
    if len(candidates) != len(documents) or any(not any(
            str(u.doc_id) == d['doc_id'] and u.source_path == d['pages'][0]['source_path']
            and u.start_page+1 == d['pages'][0]['page'] and u.end_page+1 == d['pages'][-1]['page']
            for u in candidates) for d in documents):
        return None
    # The caller validates each anchor against the current manifest.
    refs = [{**deepcopy(p), "method": "complaint_excerpt", "field": "案情简介",
             "value": value, "binding": BINDING} for p in pages]
    if 'documents' in source:
        from pleading_parties import digest
        for ref in refs: ref['bundle_digest'] = digest(source)
    if not all(scope(ref) for ref in refs):
        return None
    reasons = ['multiple_pleading_versions'] if 'documents' in source and value.startswith('各份诉状共同记载') else ['attributed_pleading_excerpt']
    return value, refs, reasons


def current_support(ref, fields):
    source = fields.get("_intake_complaint_source")
    value = summarize(source)
    expected = ref.get("input_value") if ref.get("method") == "derived_form_draft" else ref.get("value")
    if not value or value != expected or value != fields.get("案情简介"):
        return None
    if 'documents' in source:
        from pleading_parties import digest
        if ref.get('bundle_digest') != digest(source): return None
    from pleading_sources import references
    pages = references(source)
    if not any(all(ref.get(k) == p[k] for k in ("source_path", "page", "quote")) for p in pages):
        return None
    return pages


def common_brief(source):
    """Keep provably identical material without choosing a pleading version.

    Differing relief is explicitly incomplete. Never intersect arbitrary words
    or remove a liability condition to manufacture an agreed claim.
    """
    from pleading_sources import unpack
    from pleading_parties import roster
    documents = unpack(source)
    if len(documents) < 2: return None
    names = [roster(d) for d in documents]
    if any(n is None for n in names) or any(n['原告'] != names[0]['原告'] for n in names): return None
    summaries = [summarize(d) for d in documents]
    if all(summaries) and len(set(summaries)) == 1 and all(n == names[0] for n in names):
        return summaries[0]
    facts, relief = [], []
    for document in documents:
        text = _body_text(document['pages'])
        fact = re.search(r'事实(?:与|和|及|、)?理由[:：]([^。]{4,140}。)', text)
        if not fact: return None
        facts.append(fact[1])
        request = re.search(r'(?:诉讼请求|诉请事项|请求事项)[:：]?(.*?)(?=事实(?:与|和|及|、)?理由|此致|$)', text)
        if not request: return None
        # Only this positive, explicit liability-limited request is summarized.
        # Amount/rates and other relief are not inferred from an OCR-truncated tail.
        match = re.search(r'(?:^|】|[、.．])判令[一二三四五六七八九十\d]*被告'
            r'(在继承[^，,。；;（）()]{2,30}遗产的范围内)(?:向原告)?'
            r'(?:清偿|偿还)(?:贷款|借款)本金(\d+(?:\.\d{1,2})?)元', request[1])
        qualified = re.search(r'不请求|不要求|不承担|不包括|无需|无须|不得|不超过|扣减|抵扣|撤回|变更|若|如果|除非|另案|反诉', request[1])
        relief.append(f'请求被告{match[1]}清偿借款本金{match[2]}元。' if match and not qualified else '')
    if len(set(facts)) != 1: return None
    common = relief[0] if all(relief) and len(set(relief)) == 1 else ''
    value = '各份诉状共同记载：' + facts[0] + ('共同诉请：'+common if common else '')
    value += '不同诉状的当事人或诉请记载存在差异，完整诉请及采用版本待核对。'
    return value if len(value) <= LIMIT else None
