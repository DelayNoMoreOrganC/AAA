"""Read committed human corrections; no OCR, model, snapshot or source file I/O."""
from copy import deepcopy
from .experience_rules import ExperienceError, digest
from .task_sources import source_version

KINDS = {"catalog", "classification", "field"}


def human_field_record(task, field, value, *, actor_id, org_id, edited_at):
    """Source receipt for an explicit field save, including an intentional blank."""
    return {"method":"human", "value":value, "edited_at":edited_at, "actor_id":actor_id,
            "org_id":org_id, "case_id":task.case_id, "task_id":task.id,
            "source_version":task.source_version, "field":field,
            "base_revision":task.revision, "applied_revision":task.revision + 1}


def _failure():
    raise ExperienceError("EXPERIENCE_HUMAN_DECISION_REQUIRED")


def _current_manifest(task, case):
    manifest = task.source_manifest
    return (isinstance(manifest, list) and bool(manifest)
            and all(isinstance(row, dict) and type(row.get('file_id')) is str and row['file_id']
                    and type(row.get('sha256')) is str and len(row['sha256']) == 64
                    and all(c in '0123456789abcdef' for c in row['sha256'])
                    and type(row.get('pages')) is int and row['pages'] > 0
                    and type(row.get('doc_type')) is str and row['doc_type'] for row in manifest)
            and source_version(manifest, case.case_type, case.stage or "") == task.source_version)


def correction(task, case, kind, key):
    if type(kind) is not str or kind not in KINDS or type(key) is not str or not key:
        _failure()
    fields, manual = task.fields or {}, task.manual_fields or {}
    if not isinstance(fields, dict) or not isinstance(manual, dict):
        _failure()
    if kind == "catalog":
        records = manual.get("_review_decisions") or {}
        record = records.get(key) if isinstance(records, dict) else None
        if not isinstance(record, dict) or record.get("action") not in ('skip','not_applicable','acknowledged'):
            _failure()
        # These older decisions have no source/actor receipt. Keep a candidate
        # for review but never treat this as a release-quality source binding.
        return {"record":deepcopy(record), "verified_binding":False}
    if not _current_manifest(task, case):
        raise ExperienceError("EXPERIENCE_STALE_SOURCE")
    if kind == "classification":
        from .document_classification import DECISIONS, _hash, classification_options
        records = fields.get(DECISIONS) or {}
        record = records.get(key) if isinstance(records, dict) else None
        if not isinstance(record, dict):
            _failure()
        start, end, revision = record.get("start_page"), record.get("end_page"), record.get("revision")
        source = next((r for r in task.source_manifest if r.get("file_id") == record.get("file_id")
                       and r.get("sha256") == record.get("sha256")), None)
        if (not source or type(start) is not int or type(end) is not int
                or type(source.get("pages")) is not int or not 0 <= start <= end < source["pages"]
                or record.get("source_doc_type") != source.get("doc_type")
                or record.get("case_type") != case.case_type or record.get("stage", "") != (case.stage or "")
                or type(revision) is not int or not 1 <= revision <= task.revision
                or type(record.get("actor_id")) is not str or not record["actor_id"]
                or key != _hash([case.case_type, source["file_id"], source["sha256"], start, end])
                or (record.get("doc_type"), record.get("catalog_seq")) not in
                   {(r["doc_type"],r["catalog_seq"]) for r in classification_options(case.case_type)}
                or any(r.get("unit_key") == key for r in fields.get("_classification_review",[]) if isinstance(r,dict))):
            raise ExperienceError("EXPERIENCE_STALE_SOURCE")
        return {"record":deepcopy(record), "verified_binding":True}
    if key.startswith("_") or key not in manual or fields.get(key) != manual[key]:
        _failure()
    provenance = fields.get("_provenance") or {}
    if not isinstance(provenance, dict):
        _failure()
    refs = provenance.get(key) or []
    refs = refs if isinstance(refs, list) else [refs]
    human = next((r for r in reversed(refs) if isinstance(r,dict) and r.get("method") == "human"), None)
    if (not human or human.get("value") != manual[key]
            or type(human.get("actor_id")) is not str or not human["actor_id"]):
        _failure()
    bound = (human.get("org_id") == case.org_id and human.get("case_id") == task.case_id
             and human.get("task_id") == task.id and human.get("source_version") == task.source_version
             and human.get("field") == key and type(human.get("applied_revision")) is int
             and 1 <= human["applied_revision"] <= task.revision)
    return {"record":deepcopy(human), "verified_binding":bound}


def origin_digest(kind, key, record):
    return digest({"kind":kind,"key":key,"record":record})


def available_corrections(task, case):
    """Return selectable keys/status only, never correction values or reasons."""
    fields, manual = task.fields or {}, task.manual_fields or {}
    if not isinstance(fields,dict) or not isinstance(manual,dict):
        return []
    maps = [("catalog",manual.get("_review_decisions")),
            ("classification",fields.get("_document_classifications")),
            ("field",{k:None for k in manual if not k.startswith("_")})]
    result=[]
    for kind, records in maps:
        if not isinstance(records,dict):
            continue
        for key in records:
            if type(key) is not str:
                continue
            try:
                found=correction(task,case,kind,key)
            except ExperienceError:
                continue
            result.append({"source_kind":kind,"decision_key":key,
                           "verified_binding":found["verified_binding"],
                           "status":"available" if found["verified_binding"] else "needs_source_confirmation"})
    return result
