"""Keep unrelated saved draft wording during an explicit field edit.

Compare both sides under the same current derivation rules, so a renderer or
generator upgrade cannot masquerade as a consequence of the user's edit.
Initial analysis and explicit maintenance regeneration do not use this path.
"""
from copy import deepcopy
import hashlib


def _digest(value):
    return hashlib.sha256(str(value or '').encode('utf-8')).hexdigest()


def preserve_unaffected_drafts(original, before_projection, after_projection):
    from ..core.v4_bridge import load
    drafts=load('form_drafts')
    result=deepcopy(after_projection)
    old_meta=original.get('_form_drafts') or {}
    def status(fields,key):return ((fields.get('_form_drafts') or {}).get('fields') or {}).get(key) or {}
    def refs(fields,key):return (fields.get('_form_draft_sources') or {}).get(key) or []
    for key in drafts.DRAFT_FIELDS:
        old=status(original,key);before=status(before_projection,key);after=status(result,key)
        value=original.get(key,'')
        if (old.get('status') not in ('generated','insufficient','not_applicable')
                or old.get('value_digest')!=_digest(value)
                or drafts._human_value(original,key)
                or before.get('status') not in ('generated','insufficient','not_applicable')
                or before!=after or before_projection.get(key)!=result.get(key)
                or refs(before_projection,key)!=refs(result,key)):
            continue
        # Never restore a nonempty old draft if current evidence no longer
        # supports a draft, or if any of its old inputs no longer qualify.
        old_refs=refs(original,key)
        current_refs=refs(before_projection,key)
        if (not isinstance(old_refs,list) or not isinstance(current_refs,list)
                or value and (before.get('status')!='generated' or not old_refs)
                or any(ref not in current_refs for ref in old_refs)):
            continue
        if key in original:result[key]=deepcopy(value)
        else:result.pop(key,None)
        retained=deepcopy(old)
        retained.setdefault('generator_version',old_meta.get('version'))
        result['_form_drafts']['fields'][key]=retained
        result['_form_draft_sources'][key]=deepcopy(old_refs)
        history=(original.get('_provenance') or {}).get(key)
        if history is None:result.get('_provenance',{}).pop(key,None)
        else:result.setdefault('_provenance',{})[key]=deepcopy(history)
    return result
