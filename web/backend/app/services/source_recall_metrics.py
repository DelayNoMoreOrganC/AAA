"""Fixed-size, content-free accounting for cached-source recall invocations.

Counts measure checked pages and accepted evidence records, not unique fields or
currently valid facts. Prior counts are recorded historical calls, including
calls before full reanalysis; they never establish current evidence support.
"""
from __future__ import annotations

COUNTERS = (
    "pages_checked", "accepted_count", "rejected_count", "additional_page_reads",
    "additional_model_requests", "skipped_oversized_pages",
)
FIELDS = ("对方当事人", "审理法院")


def _counts(raw):
    raw = raw if isinstance(raw, dict) else {}
    complete = all(type(raw.get(key)) is int and raw[key] >= 0 for key in COUNTERS)
    result = {key: raw[key] if type(raw.get(key)) is int and raw[key] >= 0 else 0 for key in COUNTERS}
    conflicts = raw.get("conflict_fields")
    if not isinstance(conflicts, list):
        conflicts = []
        complete = False
    result["conflict_fields"] = [field for field in FIELDS if field in conflicts]
    return result, complete


def _prior(previous):
    prior, _ = _counts(None)
    complete = previous is None
    if isinstance(previous, dict):
        current, current_complete = _counts(previous)
        if previous.get("scope") == "this_analysis_call":
            older = previous.get("prior")
            prior, older_complete = _counts(older)
            complete = (isinstance(older, dict) and older.get("history_complete") is True
                        and older_complete and current_complete
                        and previous.get("status") in ("completed", "snapshot_reused"))
            # Reuse is a zero-work observation, not another recorded call.
            if previous.get("status") == "snapshot_reused":
                current, _ = _counts(None)
        else:
            # Old flat records may already have lost supplement metrics. Keep
            # what was recorded without claiming to reconstruct that history.
            complete = False
        for key in COUNTERS:
            prior[key] += current[key]
        prior["conflict_fields"] = [field for field in FIELDS
                                    if field in prior["conflict_fields"] or field in current["conflict_fields"]]
    prior.update(scope="prior_recorded_analysis_calls", history_complete=complete)
    return prior


def combine_source_recall_metrics(current, *, previous=None, reused=False):
    """Keep flat counts current; fold prior observations once without a tree.

    Absent old/new metrics stay absent for compatibility. A reused checkpoint
    explicitly records zero current work. A missing/invalid new measurement is
    distinguished from a completed measured call. Only fixed safe keys survive.
    """
    if current is None and previous is None:
        return None
    counters, complete = _counts(current)
    if reused:
        counters, _ = _counts(None)
        status = "snapshot_reused"
    else:
        status = "completed" if complete else "not_recorded"
    counters.update(scope="this_analysis_call", status=status, prior=_prior(previous))
    return counters
