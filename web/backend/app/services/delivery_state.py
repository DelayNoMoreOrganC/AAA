"""A usable draft is downloadable, but is never a formal completion."""


def is_draft(task):
    manifest = getattr(task, "artifacts", None) or {}
    return (getattr(task, "phase", "") == "draft_ready"
            and manifest.get("delivery_kind") == "draft")


def has_delivery(task):
    status = getattr(getattr(task, "status", None), "value", getattr(task, "status", None))
    return status == "done" or (status == "awaiting_review" and is_draft(task))
