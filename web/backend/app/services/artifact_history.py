"""Retain the last published generation independently of current delivery.

Only server-created, previously verified manifests are accepted. This pointer
is private storage metadata; it never makes an obsolete output downloadable as
the current revision and is not a source of case facts.
"""
from copy import deepcopy


def last_published_generation(task):
    for value in (getattr(task, "artifacts", None), getattr(task, "previous_artifacts", None)):
        if (isinstance(value, dict) and value.get("valid") is True
                and isinstance(value.get("result_dir"), str) and value["result_dir"]
                and isinstance(value.get("artifacts"), list) and value["artifacts"]):
            return deepcopy(value)
    return None


def retain_published_generation(task):
    previous = last_published_generation(task)
    if previous is not None:
        task.previous_artifacts = previous
