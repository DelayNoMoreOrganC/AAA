"""Keep evidence-group membership separate from document identity and facts.

All operations are metadata-only. Invalid/stale groups remain in audit storage,
but cannot combine review decisions or make OCR warnings advisory.
"""
import copy
import json
import os

VERSION = 'evidence-group-v1'


def _path(value):
    return os.path.normcase(os.path.abspath(value)) if isinstance(value,str) and value else ''


def _ids(value):
    return (isinstance(value,list) and all(type(n) is int and n >= 0 for n in value)
            and len(value)==len(set(value)))


def _member(unit):
    return {'doc_id':unit.doc_id,'source_path':unit.source_path,'page_start':unit.start_page+1,
            'page_end':unit.end_page+1,'doc_type':unit.doc_type,
            'catalog_seq':unit.manual_catalog_seq if unit.manual_catalog_seq is not None else unit.catalog_seq}


def bind_groups(groups, units):
    """Bind exact current spans; a binding is not proof of attachment contents."""
    output=copy.deepcopy(groups or [])
    by_id={u.doc_id:u for u in units}
    if len(by_id)!=len(units):
        raise ValueError('EVIDENCE_GROUP_DUPLICATE_DOCUMENT_ID')
    for group in output:
        if not isinstance(group,dict):
            continue
        binding={'version':VERSION,'status':'unresolved','members':[]}
        group['document_binding']=binding
        if group.get('mapping_error'):
            continue
        ids,anchors=group.get('doc_ids'),group.get('anchors')
        if (not _ids(ids) or not ids or not _ids(anchors) or not set(anchors)<=set(ids)
                or any(n not in by_id for n in ids)):
            continue
        members=[_member(by_id[n]) for n in ids]
        lo,hi=group.get('start_page'),group.get('end_page')
        if (type(lo) is not int or type(hi) is not int or group.get('index_page')!=lo
                or not 1<=lo<=hi or members[0]['page_start']!=lo or members[-1]['page_end']!=hi
                or any(m['doc_type']!='evidence' or _path(m['source_path'])!=_path(group.get('source_path'))
                       or m['catalog_seq']!=members[0]['catalog_seq'] or not lo<=m['page_start']<=m['page_end']<=hi for m in members)
                or any(b['page_start']!=a['page_end']+1 for a,b in zip(members,members[1:]))):
            continue
        entries=group.get('entries')
        if (not isinstance(entries,list) or any(not isinstance(e,dict) or not _ids(e.get('doc_ids'))
                or not set(e['doc_ids'])<=set(ids[1:]) for e in entries)):
            continue
        binding.update(status='current',members=members)
    return output


def merge_groups(previous, incoming, mapping, units):
    """Remap all references, preserve both imports, deduplicate exact replays."""
    additions=copy.deepcopy(incoming or [])
    for group in additions:
        if not isinstance(group,dict):
            continue
        lists=[(group,'doc_ids'),(group,'anchors')]
        entries=group.get('entries')
        if isinstance(entries,list):
            lists.extend((e,'doc_ids') for e in entries if isinstance(e,dict))
        if any(not _ids(row.get(key)) or any(n not in mapping or type(mapping[n]) is not int for n in row[key])
               for row,key in lists):
            group['mapping_error']='unbound_document_reference'
            continue
        for row,key in lists:
            row[key]=[mapping[n] for n in row[key]]
    merged=[];seen=set()
    for group in bind_groups([*copy.deepcopy(previous or []),*additions],units):
        identity=json.dumps(group,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        if identity not in seen:
            seen.add(identity);merged.append(group)
    return merged


def matches_span(group, span):
    """Check a current queue span against bound membership, not IDs alone.

    Legacy groups have no binding and retain their prior behavior; upgraded
    analysis binds them when merging. Other callers still check manifest scope.
    """
    binding=group.get('document_binding')
    if binding is None:
        return True
    if (not isinstance(binding,dict) or binding.get('version')!=VERSION
            or binding.get('status')!='current' or group.get('mapping_error')):
        return False
    return any(isinstance(m,dict) and all(m.get(k)==span.get(k) for k in
        ('doc_id','page_start','page_end','doc_type','catalog_seq'))
        and _path(m.get('source_path'))==_path(group.get('source_path')) for m in binding.get('members') or [])


def matches_unit(group, unit):
    # Validate the source path too: different files can share local IDs/pages.
    return _path(group.get('source_path'))==_path(unit.source_path) and matches_span(group,_member(unit))
