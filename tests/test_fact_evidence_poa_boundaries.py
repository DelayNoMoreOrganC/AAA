"""Fictional power-of-attorney boundaries; no model requests or client data."""
import pytest

from fact_evidence import validate_fact


@pytest.mark.parametrize("next_label", ["受委托人", "受委托人姓名"])
@pytest.mark.parametrize("separator", ["\n", "\r\n", " "])
def test_client_name_ends_at_separately_labelled_trustee(next_label, separator):
    page = ("授权委托书\n委托人：星河演示公司" + separator + next_label
            + "：虚构程甲\n工作单位：虚构明理律师事务所\n职务：律师")
    assert validate_fact("委托人", "星河演示公司", "委托人：星河演示公司", page)


@pytest.mark.parametrize("page,quote,value", [
    ("受委托人：虚构程甲。", "受委托人：虚构程甲", "虚构程甲"),
    ("受委托人：虚构程甲。", "委托人：虚构程甲", "虚构程甲"),
    ("受委托方：星河演示公司。", "委托方：星河演示公司", "星河演示公司"),
    ("委托人：星河演示公司分公司\n受委托人姓名：虚构程甲", "委托人：星河演示公司", "星河演示公司"),
    ("委托人：星河演示公司、山海演示公司\n受委托人姓名：虚构程甲", "委托人：星河演示公司", "星河演示公司"),
    ("拟委托人：星河演示公司\n受委托人姓名：虚构程甲", "委托人：星河演示公司", "星河演示公司"),
    ("委托人：星河演示公司\n受委托人姓名待定", "委托人：星河演示公司", "星河演示公司"),
])
def test_trustee_boundary_does_not_accept_cropped_or_proposed_identity(page, quote, value):
    assert not validate_fact("委托人", value, quote, page)
