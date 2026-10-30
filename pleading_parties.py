"""Closed pleading rosters, kept separate from the represented client's role.

Pure local source derivation. No inference of representation from plaintiff /
defendant labels and no inference of filing, service or approval from a pleading.
"""
from copy import deepcopy
import hashlib
import json
import re

from document_title_review import title_evidence
from fact_evidence import validate_fact

BINDING = 'pleading_parties'
FIELDS = ('当事人', '对方当事人', '案件或项目名称', '地址')
ROLE = re.compile(r'(?:^|[。;；\n])\s*(原告|被告|第三人)(?:[一二三四五六七八九十\d]+)?\s*[:：]\s*')
RISK = re.compile(r'反诉|追加当事人|变更当事人|主体变更|变更诉讼主体|参考案例|引用案例|另案|填写示例|参考模板')


def compact(value):
    return re.sub(r'\s+', '', str(value or ''))


def digest(source):
    return hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def roster(source):
    if not isinstance(source, dict): return None
    pages = source.get('pages')
    if not isinstance(pages, list) or not 1 <= len(pages) <= 8: return None
    if any(not isinstance(p, dict) or not isinstance(p.get('source_path'), str) or not p['source_path']
           or type(p.get('page')) is not int or p['page'] < 1 or not isinstance(p.get('quote'), str)
           or not 0 < len(p['quote']) <= 18000 for p in pages): return None
    if any(p['source_path'] != pages[0]['source_path'] or p['page'] != pages[0]['page'] + i
           for i, p in enumerate(pages)): return None
    title = title_evidence(pages[0]['quote'])
    if not title or not title['verified'] or title['doc_type'] != 'complaint': return None
    text = '\n'.join(p['quote'] for p in pages)
    if RISK.search(text): return None
    end = re.search(r'(?:诉讼请求|诉请事项|请求事项|事实(?:与|和|及|、)?理由)\s*[:：]', text)
    if not end: return None  # A roster at the page edge may continue.
    header = text[:end.start()]
    matches = list(ROLE.finditer(header))
    possible_roles = list(re.finditer(r'(?:^|[。;；\n])\s*(?:原告|被告|第三人)[^。;；\n]{0,24}[:：]', header))
    if {m.start() for m in matches} != {m.start() for m in possible_roles}: return None
    names = {'原告': [], '被告': [], '第三人': []}
    for i, match in enumerate(matches):
        block = header[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(header)]
        boundary = re.search(r'[，,。;；]', block)
        # The next role match owns its preceding period/newline. A single
        # completed identity before that delimiter must not lose its last name.
        if not boundary and (i + 1 == len(matches) or len(block.strip().splitlines()) != 1): return None
        values = compact(block[:boundary.start()] if boundary else block).split('、')
        if any(not 2 <= len(value) <= 100 or re.search(r'[:：/()（）]|等人|等公司|不详|待定|未提供|原告|被告|委托|住所', value)
               for value in values): return None
        names[match[1]].extend(values)
    if not names['原告'] or not names['被告']: return None
    all_names = sum(names.values(), [])
    if len(all_names) != len(set(all_names)): return None
    matter = re.search(r'(?:^|[。;；\n])\s*案由\s*[:：]\s*([^。;；\n]{2,60})', header)
    return {**names, '案由': compact(matter[1]) if matter else ''}


def collect_source(fields, units, page_cache, allowed_sources):
    fields.pop('_pleading_parties_source', None)
    from pleading_sources import collect, pack
    documents = collect(units, page_cache, allowed_sources)
    if documents and all(roster(d) for d in documents):
        fields['_pleading_parties_source'] = pack(documents)


def client_ref(fields):
    value = fields.get('委托人')
    if not value or any(r.get('field') == '委托人' and not r.get('resolved') for r in fields.get('_field_conflicts', [])): return None
    refs = fields.get('_provenance', {}).get('委托人', [])
    refs = [refs] if isinstance(refs, dict) else refs
    for ref in reversed(refs):
        if not isinstance(ref, dict) or ref.get('value') != value: continue
        if ref.get('method') == 'human': return {**deepcopy(ref), 'field': '委托人'}
        # A complete independently validated POA roster is a client source,
        # unlike a party roster derived from this same pleading. Preserve the
        # full original POA and its subject binding, not just the model's name.
        if (ref.get('method') in ('local_agent', 'visual_agent_local_evidence')
                and ref.get('derivation') == 'labelled_poa_roster' and not ref.get('binding')
                and isinstance(ref.get('source_path'), str) and type(ref.get('page')) is int):
            from source_engagement_evidence import poa_reference_supported
            if poa_reference_supported('委托人', value, ref, fields):
                return {**deepcopy(ref), 'field': '委托人'}
        # The original quote must explicitly identify the client. A derived
        # roster or the name alone cannot become its own identity foundation.
        if (ref.get('method') in ('local_agent', 'visual_agent_local_evidence')
                and not ref.get('binding') and not ref.get('derivation')
                and isinstance(ref.get('source_path'), str) and type(ref.get('page')) is int
                and validate_fact('委托人', value, ref.get('quote'), ref.get('quote'))):
            return {**deepcopy(ref), 'field': '委托人'}
    return None


def values_for(fields):
    from pleading_sources import unpack
    source = fields.get('_pleading_parties_source')
    if isinstance(source, dict) and 'documents' in source:
        documents = unpack(source)
        if not documents or not all(roster(d) for d in documents): return {}, None
        candidates = [values_for({**fields, '_pleading_parties_source': d}) for d in documents]
        common = {k:v for k,v in candidates[0][0].items()
                  if all(row.get(k) == v for row,_ in candidates)}
        return common, candidates[0][1]
    names = roster(fields.get('_pleading_parties_source'))
    if not names: return {}, None
    values = {}
    cause = names['案由']
    if cause and cause.endswith('纠纷'):
        values['案件或项目名称'] = '、'.join(names['原告']) + '诉' + '、'.join(names['被告']) + '的' + cause
    client = client_ref(fields)
    if client:
        value = compact(client['value'])
        roles = [role for role in ('原告', '被告') if value in names[role]]
        if len(roles) == 1:
            values['当事人'] = client['value']
            values['对方当事人'] = '、'.join(names['被告' if roles[0] == '原告' else '原告'])
            address = represented_address(fields['_pleading_parties_source'], value)
            if address:
                values['地址'] = address
    return values, client


def represented_address(source, client):
    """Read one represented party's stated residence, never a service finding.

    Called only after the complete roster and independent client identity have
    been checked. Joint-party shorthand and competing/qualified addresses are
    left for review. No opposing party or counsel's address can fill this slot.
    """
    text = '\n'.join(p['quote'] for p in source['pages'])
    end = re.search(r'(?:诉讼请求|诉请事项|请求事项|事实(?:与|和|及|、)?理由)\s*[:：]', text)
    if not end:
        return None
    header = text[:end.start()]
    roles = list(ROLE.finditer(header))
    for i, role in enumerate(roles):
        if role[1] not in ('原告', '被告'):
            continue
        block = header[role.end():roles[i + 1].start() if i + 1 < len(roles) else len(header)]
        boundary = re.search(r'[，,。;；]', block)
        if not boundary or compact(block[:boundary.start()]) != client:
            continue
        # A representative's/contact person's details belong to that person.
        own = re.split(r'法定代表人|负责人|委托(?:诉讼)?代理人|代理律师|联系人', block[boundary.end():], maxsplit=1)[0]
        if re.search(r'原住所|原住址|曾住|曾用地址|户籍|现住|迁|变更|不详|不明|待核|待定|未提供|拟|送达地址', own):
            return None
        labels = list(re.finditer(r'(?:^|[，,。;；\n])\s*(?:住所地|住所|住址|地址)\s*[:：]?\s*', own))
        if len(labels) != 1:
            return None
        tail = own[labels[0].end():]
        stop = re.search(r'[，,。;；]|(?:联系电话|电话|手机|传真|邮编|身份证|统一(?:社会)?信用代码)\s*[:：]', tail)
        if not stop:
            # The next role owns its period/newline. Only allow the completed
            # block boundary, not the final uncapped section before requests.
            if i + 1 == len(roles):
                return None
            raw = tail
        else:
            raw = tail[:stop.start()]
            if stop[0] in ('，', ',') and not re.match(
                    r'\s*(?:联系电话|电话|手机|传真|邮编|身份证|统一(?:社会)?信用代码|法定代表人|负责人)\s*[:：]', tail[stop.end():]):
                return None
        address = compact(raw)
        if (not 3 <= len(address) <= 120 or re.search(r'[:：?？]|未|不详|待|未知|原告|被告|案由|代理|律师', address)):
            return None
        return address
    return None


def current_support(ref, fields):
    if not isinstance(ref, dict) or ref.get('binding') != BINDING: return None
    field = ref.get('input_field') if ref.get('method') == 'derived_form_draft' else ref.get('field')
    value = ref.get('input_value') if ref.get('method') == 'derived_form_draft' else ref.get('value')
    if field not in FIELDS or fields.get(field) != value: return None
    if any(r.get('field') == field and not r.get('resolved') for r in fields.get('_field_conflicts', [])): return None
    source = fields.get('_pleading_parties_source')
    values, client = values_for(fields)
    if values.get(field) != value or ref.get('bundle_digest') != digest(source): return None
    first = source['pages'][0]
    if any(ref.get(k) != first[k] for k in ('source_path', 'page', 'quote')): return None
    if field != '案件或项目名称' and ref.get('client_support') != client: return None
    if field != '案件或项目名称' and client is None: return None
    from pleading_sources import references
    return references(source) + ([client] if field != '案件或项目名称' and client.get('method') != 'human' else [])


def reference_supported(field, value, ref, fields):
    return ref.get('field') == field and ref.get('value') == value and current_support(ref, fields) is not None


def recall(fields, provenance, conflicts, *, page_cache, allowed_sources, document_units, manual_fields, method, fact_review):
    collect_source(fields, document_units, page_cache, allowed_sources)
    context = {**fields, '_provenance': provenance, '_field_conflicts': conflicts}
    values, client = values_for(context)
    from pleading_sources import unpack
    documents = unpack(fields.get('_pleading_parties_source'))
    if len(documents) > 1:
        candidates = [(d, values_for({**context, '_pleading_parties_source':d})[0]) for d in documents]
        for field in FIELDS:
            choices = [{**deepcopy(d['pages'][0]), 'value': row[field]} for d,row in candidates if row.get(field)]
            distinct = list(dict.fromkeys(r['value'] for r in choices))
            if len(distinct) > 1 and field not in manual_fields and not any(r.get('field') == field for r in conflicts):
                conflicts.append({'field':field, 'values':distinct, 'sources':choices,
                                  'reason_code':'multiple_pleading_versions'})
    if client and client.get('method') != 'human':
        location = (client.get('source_path'), client.get('page'))
        if (location not in allowed_sources or not validate_fact('委托人', client['value'],
                client.get('quote'), page_cache.get(location))):
            for field in ('当事人', '对方当事人', '地址'):
                values.pop(field, None)
    count = 0
    for field, value in values.items():
        refs = provenance.get(field, []); refs = [refs] if isinstance(refs, dict) else refs
        if (field in manual_fields or any(r.get('method') == 'human' for r in refs)
                or any(r.get('field') == field and not r.get('resolved') for r in conflicts)): continue
        source = fields['_pleading_parties_source']
        ref = {**deepcopy(source['pages'][0]), 'method': method, 'field': field, 'value': value,
               'binding': BINDING, 'derivation': BINDING, 'bundle_digest': digest(source),
               'client_support': deepcopy(client) if field != '案件或项目名称' else None}
        if fields.get(field) and fields[field] != value:
            conflicts.append({'field': field, 'values': [fields[field], value], 'source': ref,
                              'reason_code': 'pleading_roster_conflict'})
            continue
        if ref in refs: continue
        fields[field] = value; provenance[field] = refs + [ref]; count += 1
        for issue in fact_review:
            if issue.get('field') == field and any(issue.get('source_path') == p['source_path'] and issue.get('page') == p['page'] for p in source['pages']):
                issue['resolution'] = 'field_supported_by_cached_source'
    return count
