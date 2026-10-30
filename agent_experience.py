"""Declarative routing experience. No prompts, client facts, tools or file I/O.

This is a narrow first contract for boundary/reading guidance, not a learned
fact store. Signals are supplied by a source-bound caller; matching a rule
does not establish the truth of those signals or verify document contents.
"""
from copy import deepcopy
import hashlib
import json
from dataclasses import dataclass

VERSION = "experience-routing-v1"
BUSINESSES = {"civil", "admin", "criminal", "nonlit", "counsel"}
KINDS = {"contract", "contract_attachment", "receipt", "registration", "bank_screenshot",
         "evidence", "pleading", "defense", "opinion", "judgment", "ruling", "work_record"}
SIGNALS = {"explicit_component_link", "independent_title", "field_reference", "field_conflict",
           "unclear_image", "handwritten", "unknown_orientation", "signed_page",
           "missing_core_source", "unresolved_boundary", "verified_archive_only"}
ACTIONS = {"keep_component", "separate_document", "read_for_field", "retain_only"}
FIELDS = {"case_intro", "closing_summary", "handling_result", "parties", "fees", "dates"}


class ExperienceError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _choices(value, allowed, *, empty=False):
    if (not isinstance(value, list) or (not value and not empty)
            or any(type(item) is not str or item not in allowed for item in value)
            or len(value) != len(set(value))):
        raise ExperienceError("EXPERIENCE_CONTRACT_INVALID")
    return sorted(value)


def normalize(raw):
    keys = {"case_types", "document_kinds", "required_signals", "excluded_signals", "action", "target_fields"}
    if (not isinstance(raw, dict) or set(raw) != keys
            or type(raw.get("action")) is not str or raw["action"] not in ACTIONS):
        raise ExperienceError("EXPERIENCE_CONTRACT_INVALID")
    result = {"case_types": _choices(raw["case_types"], BUSINESSES),
              "document_kinds": _choices(raw["document_kinds"], KINDS),
              "required_signals": _choices(raw["required_signals"], SIGNALS),
              "excluded_signals": _choices(raw["excluded_signals"], SIGNALS, empty=True),
              "action": raw["action"], "target_fields": _choices(raw["target_fields"], FIELDS, empty=True)}
    required, excluded = set(result["required_signals"]), set(result["excluded_signals"])
    if required & excluded or (result["action"] == "read_for_field") != bool(result["target_fields"]):
        raise ExperienceError("EXPERIENCE_CONTRACT_INVALID")
    if result["action"] == "keep_component" and "explicit_component_link" not in required:
        raise ExperienceError("EXPERIENCE_COMPONENT_EVIDENCE_REQUIRED")
    if result["action"] == "retain_only":
        guards = {"field_reference", "field_conflict", "unclear_image", "handwritten",
                  "unknown_orientation", "missing_core_source", "unresolved_boundary"}
        if ("verified_archive_only" not in required or not guards <= excluded
                or set(result["document_kinds"]) - {"evidence", "bank_screenshot"}):
            raise ExperienceError("EXPERIENCE_READ_GUARDS_REQUIRED")
    return result


def match(rule, context):
    rule = normalize(rule)
    # All signals must be explicitly assessed true/false. Missing is unknown.
    if not isinstance(context, dict) or set(context) != {"case_type", "document_kind", "signals"}:
        return False
    signals = context["signals"]
    if (not isinstance(signals, dict) or set(signals) - SIGNALS
            or any(type(v) is not bool for v in signals.values())):
        return False
    return (context["case_type"] in rule["case_types"]
            and context["document_kind"] in rule["document_kinds"]
            and all(signals.get(k) is True for k in rule["required_signals"])
            and all(signals.get(k) is False for k in rule["excluded_signals"]))


def conflicts(left, right):
    left, right = normalize(left), normalize(right)
    if not set(left["case_types"]) & set(right["case_types"]):
        return False
    if not set(left["document_kinds"]) & set(right["document_kinds"]):
        return False
    if (set(left["required_signals"]) & set(right["excluded_signals"])
            or set(right["required_signals"]) & set(left["excluded_signals"])):
        return False
    pair = {left["action"], right["action"]}
    return pair in ({"keep_component", "separate_document"}, {"read_for_field", "retain_only"})


def freeze(rows, *, org_id, case_id):
    """Copy active versions; exclude BOTH sides of any applicable conflict."""
    included = []
    for row in rows:
        if row.org_id != org_id or row.state != "active" or (row.scope == "case" and row.case_id != case_id):
            continue
        payload = normalize(row.payload)
        if row.scope not in {"case", "firm", "general"} or digest(payload) != row.payload_digest:
            raise ExperienceError("EXPERIENCE_INTEGRITY_INVALID")
        included.append({"id": row.id, "revision": row.revision, "scope": row.scope,
                         "payload_digest": row.payload_digest, "payload": payload})
    included.sort(key=lambda row: row["id"])
    pairs = [[a["id"], b["id"]] for i, a in enumerate(included) for b in included[i + 1:]
             if conflicts(a["payload"], b["payload"])]
    blocked = {key for pair in pairs for key in pair}
    body = {"version": VERSION, "org_id": org_id, "case_id": case_id,
            "rules": [row for row in included if row["id"] not in blocked], "conflicts": pairs}
    return deepcopy({**body, "sha256": digest(body)})


def validate_snapshot(raw, *, org_id=None, case_id=None):
    """Validate a server-stored snapshot; its hash is integrity, not authority."""
    if (not isinstance(raw, dict) or set(raw) != {"version", "org_id", "case_id", "rules", "conflicts", "sha256"}
            or raw["version"] != VERSION or type(raw["org_id"]) is not str or not raw["org_id"]
            or type(raw["case_id"]) is not str or not raw["case_id"]
            or org_id is not None and raw["org_id"] != org_id
            or case_id is not None and raw["case_id"] != case_id):
        raise ExperienceError("EXPERIENCE_SNAPSHOT_INVALID")
    body = {key: value for key, value in raw.items() if key != "sha256"}
    if digest(body) != raw["sha256"] or not isinstance(raw["rules"], list) or not isinstance(raw["conflicts"], list):
        raise ExperienceError("EXPERIENCE_SNAPSHOT_INVALID")
    ids = set()
    for row in raw["rules"]:
        if (not isinstance(row, dict) or set(row) != {"id", "revision", "scope", "payload_digest", "payload"}
                or type(row["id"]) is not str or not row["id"] or row["id"] in ids
                or type(row["revision"]) is not int or row["revision"] < 1
                or type(row["scope"]) is not str or row["scope"] not in {"case", "firm", "general"}
                or row["payload"] != normalize(row["payload"]) or digest(row["payload"]) != row["payload_digest"]):
            raise ExperienceError("EXPERIENCE_SNAPSHOT_INVALID")
        ids.add(row["id"])
    for pair in raw["conflicts"]:
        if (not isinstance(pair, list) or len(pair) != 2 or any(type(x) is not str or not x or x in ids for x in pair)
                or pair[0] == pair[1]):
            raise ExperienceError("EXPERIENCE_SNAPSHOT_INVALID")
    if any(conflicts(a["payload"], b["payload"]) for i, a in enumerate(raw["rules"]) for b in raw["rules"][i+1:]):
        raise ExperienceError("EXPERIENCE_SNAPSHOT_INVALID")
    return deepcopy(raw)


@dataclass(frozen=True)
class ExperienceContext:
    """Private config capability, constructed from a task after authorization."""
    snapshot_json: str

    def __post_init__(self):
        validate_snapshot(json.loads(self.snapshot_json))

    @classmethod
    def from_snapshot(cls, snapshot, *, org_id, case_id):
        checked = validate_snapshot(snapshot, org_id=org_id, case_id=case_id)
        return cls(json.dumps(checked, ensure_ascii=False, sort_keys=True))

    @property
    def snapshot(self):
        return json.loads(self.snapshot_json)

    @property
    def identity(self):
        return self.snapshot["sha256"]

    def guidance(self, case_type):
        snapshot = self.snapshot
        # No organization, source task, case pointer, or historical text sent.
        return {"snapshot_sha256": self.identity,
                "rules": [r for r in snapshot["rules"] if case_type in r["payload"]["case_types"]],
                "precedence": "原件、来源依据、系统校验和当前人工决定优先。这些是有条件的建议，"
                              "未知条件不得视为满足；须先查看当前材料。不得据此生成事实、越过手填留白、"
                              "合并独立文书或跳过疑难页。归组仍须当前页与相关首页的依据。"}

    def matching(self, context):
        return [r for r in self.snapshot["rules"] if match(r["payload"], context)]


def require_context(value):
    if value is not None and type(value) is not ExperienceContext:
        raise ExperienceError("EXPERIENCE_CONTEXT_INVALID")
    return value
