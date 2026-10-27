"""Pure, bounded links from a same-page engagement to one opposing party.

This does not infer the represented side from a party list, bind different pages,
assert that an engagement was signed, or decide the current procedural stage.
All three anchors must occur in the same literal submitted quote and source span.
Unknown/multiple/corrected identities stay unaccepted. No I/O or model calls.
"""
from __future__ import annotations

import re
import unicodedata


_CLIENT_LABEL = re.compile(
    r"(?:委托人|委托方|委托单位)(?:名称)?(?:(?:暨|即)(?:本案)?(?P<role>原告|被告))?[:：]")
_REFERENCE = re.compile(
    r"另案|其他案件|其它案件|参考案例|引用案例|案例摘录|填写示例|示例文本|参考模板|举例|假设|假定|假如|"
    r"声称|宣称|主张|据称|转述|引述|诉称|辩称|摘录")
_PREFIX = re.compile(
    r"(?:拟|计划|准备|预计|尚未|并未|未曾|不是|并非|不属于|若|如果|仅为|对方|相对方|第三人)"
    r"[^。;；!！?？]{0,24}$")
_BACKREF = re.compile(
    r"(?:上述|以上|前述|该|此)(?:的)?(?:身份|角色|关系|委托|陈述|内容)"
    r"[^。;；!！?？]{0,24}(?:拟|假设|假定|示例|参考|不属实|不真实|不是|并非|未确认|未核实|尚未|撤回|更正|纠正|暂定|待[^。;；]{0,12}(?:确认|核实)|为条件)")
_CORRECTION = re.compile(
    r"(?:更正|纠正|变更|撤回)[^。;；!！?？]{0,50}(?:身份|角色|委托|原告|被告)|"
    r"(?:身份|角色|委托)[^。;；!！?？]{0,24}(?:已变更|已撤回)")
_ENTITY_END = re.compile(r"(?:公司|银行|合作社|委员会|协会|中心|事务所|研究所|医院|学校|政府|局)$")
_NAME_BAD = re.compile(
    r"[,，。;；:：!！?？、/|&]|以及|等人|等公司|以下简称|法定代表人|代理人|之父|之母|之子|之女|"
    r"原告|被告|委托人|(?:公司|银行|合作社|委员会|事务所)(?:和|与|及)|"
    r"(?:公司|银行)(?:的)?(?:员工|职员|法定代表人)")


def _compact(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def _single_name(value):
    if (not 2 <= len(value) <= 120 or _NAME_BAD.search(value)
            or value.count("(") != value.count(")") or value.endswith("等")):
        return False
    # Do not turn a joined personal-name list into a single individual. This is
    # deliberately conservative; a genuine unusual name remains for review.
    if not _ENTITY_END.search(value) and len(value) >= 5 and re.search(r".{2,}(?:和|与|及).{2,}", value):
        return False
    return bool(re.fullmatch(r"[\w\u3400-\u9fff().·-]+", value))


def _subject_matches(subject, client):
    if subject == client:
        return True
    if subject == "本公司":
        return client.endswith("公司")
    if subject == "本单位":
        return bool(_ENTITY_END.search(client))
    return subject == "本人" and not _ENTITY_END.search(client) and len(client) <= 30


def _identity(page, label):
    """Return one explicit name/role binding and its complete end position."""
    tail = page[label.end():]
    if label['role']:
        match = re.match(r"(?P<name>[^。;；!！?？,，:：]{2,120})[。;；!！?？]", tail)
        if match:
            return match['name'], label['role'], label.end() + match.end()
        return None
    match = re.match(r"(?P<name>[^。;；!！?？,，:：]{2,120})(?P<stop>[。;；,，])", tail)
    if not match:
        return None
    client = match['name']
    after = tail[match.end():]
    if match['stop'] in ",，":
        role = re.match(r"(?:本案)?诉讼身份(?:为|是)(?:本案)?(?P<role>原告|被告)[。;；!！?？]", after)
    else:
        subject = r"(?P<subject>本公司|本单位|本人|" + re.escape(client) + r")"
        role = re.match(subject + r"(?:是|为|系)本案(?P<role>原告|被告)[。;；!！?？]", after)
        if role and not _subject_matches(role['subject'], client):
            return None
    if not role:
        return None
    return client, role['role'], label.end() + match.end() + role.end()


def _relationship_pattern(client):
    """One shared grammar for finding and validating the direct engagement."""
    actor = r"(?P<actor>本公司|本单位|本人|" + re.escape(client) + r")"
    firm = r"(?:贵所|本所|[^。;；!！?？,，:：]{2,40}律师事务所(?:分所)?)"
    return re.compile(actor + r"(?:现|已)?(?:委托|授权)" + firm
        + r"[,，]?代理(?:本案)?与(?:本案)?(?P<role>原告|被告)[:：]?"
        + r"(?P<name>[^。;；!！?？:：]{2,120}?)之间(?:的)?"
        + r"[^。;；!！?？]{1,100}(?:纠纷|诉讼|案件|一案)[。;；!！?？]")


def _same_subject_conflict(page, client, own_role):
    """Detect direct, same-subject role/authority corrections outside the quote.

    This checks declarations about the bound client, not arbitrary appearances
    of 原告/被告 in claims or procedural descriptions.
    """
    actors = [re.escape(client)]
    actors.extend(re.escape(s) for s in ("本公司", "本单位", "本人")
                  if _subject_matches(s, client))
    actor = r"(?:" + "|".join(actors) + r")"
    start = r"(?:^|[。;；!！?？,，])" + actor
    roles = re.finditer(start + r"(?:现|仍|已|已经)?(?P<op>是|为|系|不是|并非|不属于)"
                        r"(?:本案)?(?P<role>原告|被告)(?=$|[。;；!！?？,，])", page)
    for match in roles:
        negative = match['op'] in ("不是", "并非", "不属于")
        if (negative and match['role'] == own_role) or (not negative and match['role'] != own_role):
            return True
    uncertain = start + r"[^。;；!！?？]{0,16}(?:未确认|未核实|暂定|拟列|不确定)[^。;；!！?？]{0,16}(?:身份|角色|原告|被告)"
    withdrawn = start + r"[^。;；!！?？]{0,12}(?:撤回|撤销|解除|终止)[^。;；!！?？]{0,12}(?:委托|授权)"
    return bool(re.search(uncertain, page) or re.search(withdrawn, page))


def same_page_opponent_binding(value, quote, page_text) -> dict[str, str] | None:
    """Accept only a complete, single opposing name directly bound in context.

    Supported evidence declares the unique client and its 本案原告/被告 role,
    then directly entrusts counsel to act against the named opposite-role party.
    Both role directions, explicit dual-role labels, people/entities and OCR
    whitespace are handled. Bare party tables and cross-page joins are not.
    """
    if not all(isinstance(v, str) and v.strip() for v in (value, quote, page_text)):
        return None
    value, quote, page = map(_compact, (value, quote, page_text))
    if not _single_name(value) or quote not in page or value not in quote:
        return None
    labels = list(_CLIENT_LABEL.finditer(page))
    if len(labels) != 1 or _REFERENCE.search(page) or _BACKREF.search(page) or _CORRECTION.search(page):
        return None
    label = labels[0]
    if (_PREFIX.search(page[:label.start()])
            or re.search(r"(?:受|代理|代|转|前|原|非)$", page[:label.start()])):
        return None
    identity = _identity(page, label)
    if identity is None:
        return None
    client, own_role, identity_end = identity
    if not _single_name(client) or client == value or _same_subject_conflict(page, client, own_role):
        return None
    opposite_role = "原告" if own_role == "被告" else "被告"
    relationship = _relationship_pattern(client)
    # The declaration and relation must be adjacent within this bounded block:
    # an intervening company's sentence cannot lend its 本公司 to this client.
    relation = relationship.match(page, identity_end)
    if (relation is None or not _subject_matches(relation['actor'], client)
            or relation['role'] != opposite_role or relation['name'] != value
            or not _single_name(relation['name'])):
        return None
    block_start, block_end = label.start(), relation.end()
    if any(marker in page[block_start:block_end] for marker in ("拟", "计划", "预计", "尚未", "并未", "未曾", "假如", "如果")):
        return None
    # Additional explicit litigant declarations must agree with the sole pair;
    # do not silently keep the first member of an expanded or corrected roster.
    if re.search(r"(?:另有|另列|新增|追加|共同)(?:原告|被告)", page):
        return None
    roster = re.finditer(r"(?:^|[。;；!！?？])(?:本案)?(?P<role>原告|被告)[:：](?P<name>[^。;；!！?？,，]{2,120})(?=$|[。;；!！?？,，])", page)
    for item in roster:
        expected = client if item['role'] == own_role else value
        if item['name'] != expected:
            return None
    # A second full opposing relation also prevents selecting just one entity.
    if len(list(relationship.finditer(page))) != 1:
        return None
    position = 0
    while (position := page.find(quote, position)) >= 0:
        if position <= block_start and position + len(quote) >= block_end:
            return {"client": client, "own_role": own_role,
                    "opponent": value, "opponent_role": opposite_role}
        position += max(1, len(quote))
    return None


def same_page_opponent_supported(value, quote, page_text) -> bool:
    """Compatibility boolean; binding alone does not reconcile other pages.

    Workflow callers can use ``same_page_opponent_binding`` to compare this
    page's client/role with current accepted identity and unresolved conflicts.
    The returned comparison strings never replace stored original value/quote.
    """
    return same_page_opponent_binding(value, quote, page_text) is not None


def extract_same_page_opponent_candidates(page_text) -> list[dict[str, str]]:
    """Return at most one complete, literal same-page opponent candidate.

    This is a bounded source scan, independent of a model-supplied quotation.
    It shares the existing grammar and acceptance gate; it does not decide the
    whole case's client, override human values, or resolve conflicting facts.
    A caller must apply those case-level guards before storing this candidate.

    At most 20,000 original characters are examined, never a truncated prefix.
    Stored value/quote retain source spelling and whitespace. If NFKC offsets
    cannot be mapped exactly back to a contiguous original substring, no
    candidate is returned. No source I/O or additional OCR/model call occurs.
    """
    if not isinstance(page_text, str) or not page_text.strip() or len(page_text) > 20_000:
        return []
    characters, offsets = [], []
    for index, original in enumerate(page_text):
        for character in unicodedata.normalize("NFKC", original):
            if not character.isspace():
                characters.append(character)
                offsets.append(index)
    page = "".join(characters)
    # Per-character normalization is not always whole-string normalization
    # (e.g. a decomposed combining sequence). Fail closed instead of guessing.
    if page != _compact(page_text):
        return []
    labels = list(_CLIENT_LABEL.finditer(page))
    if len(labels) != 1:
        return []
    label = labels[0]
    identity = _identity(page, label)
    if identity is None:
        return []
    client, _own_role, identity_end = identity
    if not _single_name(client):
        return []
    relation = _relationship_pattern(client).match(page, identity_end)
    if relation is None:
        return []
    quote = page_text[offsets[label.start()]:offsets[relation.end() - 1] + 1]
    value = page_text[offsets[relation.start("name")]:offsets[relation.end("name") - 1] + 1]
    if (len(quote) > 1500 or _compact(quote) != page[label.start():relation.end()]
            or _compact(value) != relation["name"]):
        return []
    # Prefixes, later corrections, additional parties and all other semantic
    # conditions remain owned by the same validator used for model candidates.
    if same_page_opponent_binding(value, quote, page_text) is None:
        return []
    return [{"field": "对方当事人", "value": value, "quote": quote}]


def current_party_binding_supported(ref, fields) -> bool:
    """Recheck a persisted opponent link against the current confirmed client.

    Legacy/other bindings retain their existing validation paths. Only this
    helper's binding is guarded here; the caller still owns current source
    scope, target-field conflicts and preservation of all conflicting facts.
    A source page or same-case filename alone never establishes current client.
    """
    if not isinstance(ref, dict):
        return False
    if ref.get("binding") != "same_page_opponent":
        return True
    if not isinstance(fields, dict) or not isinstance(ref.get("subject"), str):
        return False
    subject = _compact(ref["subject"])
    if not _single_name(subject):
        return False
    keys = ("委托人", "委托人名称", "委托方")
    conflicts = fields.get("_field_conflicts") or []
    if not isinstance(conflicts, list):
        return False
    if any(not isinstance(item, dict) or
           (item.get("field") in keys and item.get("resolved") is not True)
           for item in conflicts):
        return False
    provenance = fields.get("_provenance")
    if not isinstance(provenance, dict):
        return False
    names = set()
    confirmed = False
    for key in keys:
        value = fields.get(key)
        if value is not None and not isinstance(value, str):
            return False
        value = _compact(value or "")
        refs = provenance.get(key) or []
        refs = [refs] if isinstance(refs, dict) else refs
        if not isinstance(refs, list):
            return False
        matching = [item for item in refs if isinstance(item, dict)
                    and isinstance(item.get("value"), str)
                    and _compact(item["value"]) == value]
        if not value:
            # An explicit human blank cannot be replaced by an inherited alias.
            if key in fields and any(item.get("method") == "human" for item in matching):
                return False
            continue
        if not _single_name(value):
            return False
        names.add(value)
        if any(item.get("method") in ("human", "local_agent", "visual_agent_local_evidence")
               for item in matching):
            confirmed = True
    return confirmed and names == {subject}
