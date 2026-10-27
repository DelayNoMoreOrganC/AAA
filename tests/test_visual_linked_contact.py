"""Bounded end-of-run contact association, synthetic pages and mock transport."""
from types import SimpleNamespace
import pytest

import visual_document_workflow as workflow
import visual_archive_agent as agent
from tests.test_visual_document_workflow import (
    classified, extracted, fact, mock_client, offline_only, pdf, run,
)
from tests.test_visual_cached_evidence import seed_title_cache


CLIENT = "演示星云科技有限公司"
OTHER = "演示远山科技有限公司"
ADDRESS = "演示市样例区演示路88号"
PHONE = "000-00000000"


@pytest.mark.parametrize("contact_first", [True, False])
def test_named_contact_links_after_all_documents_independent_of_reading_order(tmp_path, monkeypatch, contact_first):
    identity = f"委托人：{CLIENT}。受托人：演示明序律师事务所。"
    contact = f"聘方名称：{CLIENT}。联系地址：{ADDRESS}。联系电话：{PHONE}。"
    sources = [pdf(tmp_path, name=f"{n}.pdf", texts=[text]) for n, text in enumerate(
        (contact, identity) if contact_first else (identity, contact))]
    contact_key, identity_key = ("f1p1", "f2p1") if contact_first else ("f2p1", "f1p1")
    calls = []
    original_read = agent.CasePages.read
    def read(self, key):
        if key not in self.read_pages:
            calls.append(key)
        return original_read(self, key)
    monkeypatch.setattr(agent.CasePages, "read", read)
    def respond(ctx, messages, _):
        if ctx["phase"] == "classification": return classified(ctx)
        key = ctx["本组选读页面"][0]
        if key == identity_key:
            return extracted(ctx, [fact(key, CLIENT, quote=f"委托人：{CLIENT}。")])
        return extracted(ctx, [
            {**fact(key, ADDRESS, "地址", f"联系地址：{ADDRESS}。"),
             "supporting_sources": [{"source_path": "PRIVATE_OUTSIDE", "page": 99}], "subject": OTHER},
            fact(key, PHONE, "委托人电话", f"联系电话：{PHONE}。"),
        ])
    client = mock_client(monkeypatch, respond)
    _, fields, metadata, _ = run(sources)
    assert fields == {"委托人": CLIENT, "地址": ADDRESS, "委托人电话": PHONE}
    assert sorted(calls) == ["f1p1", "f2p1"] and client.metrics["model_requests"] == 5
    for field, value, label in (("地址", ADDRESS, "联系地址"), ("委托人电话", PHONE, "联系电话")):
        ref = metadata["_provenance"][field][0]
        assert ref["source_path"] == sources[0 if contact_first else 1].path and ref["page"] == 1
        assert ref["value"] == value and ref["quote"] == f"{label}：{value}。"
        assert ref["binding"] == "client_contact"
        assert ref["supporting_sources"] == [{**metadata["_provenance"]["委托人"][0], "field": "委托人"}]
    assert all(item["resolution"] == "accepted_after_linked_evidence" for item in metadata["_fact_review"])
    metrics = metadata["_agent_summary"]["this_run_metrics"]
    assert metrics["linked_contact_review"] == {"candidates": 2, "accepted": 2,
        "additional_page_reads": 0, "additional_model_requests": 0}
    assert metrics["targeted_fact_review"]["accepted"] == 0  # Not a model-recheck success.
    assert "PRIVATE_OUTSIDE" not in str(metadata)
    assert not metadata["_field_conflicts"]


def test_later_client_conflict_suppresses_link_even_after_a_matching_client(tmp_path, monkeypatch):
    texts = [f"委托人：{CLIENT}。", f"聘方名称：{CLIENT}。联系地址：{ADDRESS}。", f"委托人：{OTHER}。"]
    sources = [pdf(tmp_path, name=f"{n}.pdf", texts=[text]) for n, text in enumerate(texts)]
    def respond(ctx, *_):
        if ctx["phase"] == "classification": return classified(ctx)
        key = ctx["本组选读页面"][0]
        if key == "f2p1": return extracted(ctx, [fact(key, ADDRESS, "地址", f"联系地址：{ADDRESS}。")])
        return extracted(ctx, [fact(key, CLIENT if key == "f1p1" else OTHER)])
    client = mock_client(monkeypatch, respond)
    _, fields, metadata, _ = run(sources)
    assert fields == {"委托人": CLIENT} and client.metrics["model_requests"] == 7
    assert metadata["_field_conflicts"][0]["field"] == "委托人"
    assert len(metadata["_provenance"]["委托人"]) == 2
    assert metadata["_agent_summary"]["this_run_metrics"]["linked_contact_review"]["accepted"] == 0
    assert all("resolution" not in item for item in metadata["_fact_review"])


def test_linked_address_cannot_overwrite_an_already_accepted_different_address(tmp_path, monkeypatch):
    old = "演示市先前路1号"
    sources = [pdf(tmp_path, name="identity.pdf", texts=[f"委托人：{CLIENT}。委托人地址：{old}。"]),
               pdf(tmp_path, name="contact.pdf", texts=[f"聘方名称：{CLIENT}。联系地址：{ADDRESS}。"])]
    def respond(ctx, *_):
        if ctx["phase"] == "classification": return classified(ctx)
        if ctx["document_id"] == "d1":
            return extracted(ctx, [fact(value=CLIENT), fact(value=old, field="地址", quote=f"委托人地址：{old}。")])
        return extracted(ctx, [fact("f2p1", ADDRESS, "地址", f"联系地址：{ADDRESS}。")])
    client = mock_client(monkeypatch, respond)
    _, fields, metadata, _ = run(sources)
    assert fields == {"委托人": CLIENT, "地址": old}
    assert client.metrics["model_requests"] == 4  # Existing field has no targeted recheck.
    conflict, = metadata["_field_conflicts"]
    assert conflict["field"] == "地址" and conflict["values"] == [old, ADDRESS]
    assert conflict["source"]["binding"] == "client_contact"
    assert len(metadata["_provenance"]["地址"]) == 2


@pytest.mark.parametrize("bad_page", [
    f"聘方名称：{OTHER}。联系地址：{ADDRESS}。",
    f"聘方名称：{CLIENT}、{OTHER}。联系地址：{ADDRESS}。",
    f"聘方名称：{CLIENT}。律所联系地址：{ADDRESS}。",
    f"引用案例。聘方名称：{CLIENT}。联系地址：{ADDRESS}。",
])
def test_bad_contact_context_stays_unresolved_without_new_requests(tmp_path, monkeypatch, bad_page):
    sources = [pdf(tmp_path, name="identity.pdf", texts=[f"委托人：{CLIENT}。"]),
               pdf(tmp_path, name="contact.pdf", texts=[bad_page])]
    def respond(ctx, *_):
        if ctx["phase"] == "classification": return classified(ctx)
        return extracted(ctx, [fact(value=CLIENT)] if ctx["document_id"] == "d1" else
                         [fact("f2p1", ADDRESS, "地址", f"联系地址：{ADDRESS}。")])
    client = mock_client(monkeypatch, respond)
    _, fields, metadata, _ = run(sources)
    assert fields == {"委托人": CLIENT} and client.metrics["model_requests"] == 5
    assert metadata["_agent_summary"]["this_run_metrics"]["linked_contact_review"]["accepted"] == 0
    assert all("resolution" not in item for item in metadata["_fact_review"])


@pytest.mark.parametrize("key,allowed,seen", [
    ("f1p2", {"f1p1"}, {"f1p1", "f1p2"}),
    ("f1p2", {"f1p1", "f1p2"}, {"f1p1"}),
])
def test_out_of_scope_contact_is_not_saved_for_a_later_link(key, allowed, seen):
    pages = SimpleNamespace(pages={"f1p1": ("synthetic.pdf", 0), "f1p2": ("synthetic.pdf", 1)},
        read_pages={"f1p1", "f1p2"}, texts={"synthetic.pdf": ["", f"聘方名称：{CLIENT}。联系地址：{ADDRESS}。"]},
        read=lambda *_: pytest.fail("A rejected scope cannot read even cached data"))
    pending = []
    verified, rejected, _, _ = workflow._verify_facts(
        [fact(key, ADDRESS, "地址", f"联系地址：{ADDRESS}。")], pages, allowed, seen, set(), set(),
        deferred_contacts=pending)
    assert not verified and not pending and rejected[0]["reason_code"] == "invalid_candidate_scope"


def test_no_contact_is_invented_from_cached_text_without_a_model_candidate(tmp_path, monkeypatch):
    source = pdf(tmp_path)
    seed_title_cache(monkeypatch, {"f1p1": f"委托人：{CLIENT}。联系地址：{ADDRESS}。"})
    client = mock_client(monkeypatch, lambda ctx, *_: classified(ctx) if ctx["phase"] == "classification"
                         else extracted(ctx, [fact(value=CLIENT)]))
    _, fields, metadata, _ = run([source])
    assert fields == {"委托人": CLIENT} and client.metrics["model_requests"] == 2
    assert metadata["_agent_summary"]["this_run_metrics"]["linked_contact_review"]["candidates"] == 0


def test_rejected_batch_cannot_leave_deferred_contact_to_commit_later(tmp_path, monkeypatch):
    source = pdf(tmp_path, texts=[f"委托人：{CLIENT}。聘方名称：{CLIENT}。联系地址：{ADDRESS}。"])
    def respond(ctx, messages, _):
        if ctx["phase"] == "classification": return classified(ctx)
        if len(messages) == 2:
            return {"tool": "record_fields", "document_id": "d99", "facts": [
                fact(value=CLIENT), fact(value=ADDRESS, field="地址", quote=f"联系地址：{ADDRESS}。") ]}
        return extracted(ctx, [fact(value=CLIENT)])
    client = mock_client(monkeypatch, respond)
    _, fields, metadata, _ = run([source])
    assert fields == {"委托人": CLIENT} and client.metrics["model_requests"] == 3
    assert metadata["_agent_summary"]["this_run_metrics"]["linked_contact_review"]["candidates"] == 0
