"""Independent-review counterexamples: cropped fee prerequisites and claims."""
import pytest

from fact_evidence import validate_fact


@pytest.mark.parametrize("page", [
    "若胜诉则约定律师费6600元。",
    "对方声称：约定律师费6600元。",
])
def test_cropped_fee_scope_is_not_an_unqualified_agreement(page):
    value = "约定律师费6600元"
    assert validate_fact("收费标准", value, value + "。", page) is False
