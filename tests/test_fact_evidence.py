"""Fictional evidence: no customer materials or external requests."""
import pytest
from pathlib import Path
import runpy

from fact_evidence import validate_fact


@pytest.mark.parametrize("field,value,quote,page,expected", [
    ("收案日期", "2026年3月3日", "起诉日期：2026年3月3日", "委托代理合同。律所收案日期：2026年2月20日。起诉日期：2026年3月3日", False),
    ("收案日期", "2026年2月20日", "律所收案日期：2026年2月20日", "委托代理合同。律所收案日期：2026年2月20日。起诉日期：2026年3月3日", True),
    ("收案日期", "2026年2月20日", "收案日期：2026年2月20日", "委托代理合同\n收案日期：2026年2月20日", True),
    ("收案日期", "2026年3月3日", "法院收案日期：2026年3月3日", "虚构法院立案通知。法院收案日期：2026年3月3日。代理人：虚构律师事务所", False),
    ("收案日期", "2026年3月3日", "判决日期：2026年3月3日", "虚构判决书。判决日期：2026年3月3日", False),
    ("收案日期", "2026年2月20日", "本所于2026年2月20日接受委托", "本所于2026年2月20日接受委托。", True),
    ("收案日期", "2026年2月20日", "收案日期：2026年2月20日", "收案日期：2026年2月20日", False),
    ("收案日期", "2026年2月20日", "接受委托日期：2026年2月20日", "计划接受委托日期：2026年2月20日", False),
    ("结案日期", "2026年6月1日", "判决日期：2026年6月1日", "判决日期：2026年6月1日", False),
    ("结案日期", "2026年6月1日", "结案日期：2026年6月1日", "结案报告。结案日期：2026年6月1日", True),
    ("结案日期", "2026年6月1日", "本案于2026年6月1日结案", "本案于2026年6月1日结案。", True),
    ("结案日期", "2026年6月1日", "结案日期：2026年6月1日", "预计结案日期：2026年6月1日", False),
])
def test_dates_require_the_correct_event(field, value, quote, page, expected):
    assert validate_fact(field, value, quote, page) is expected


@pytest.mark.parametrize("value,quote,page,expected", [
    ("星河演示公司", "原告：星河演示公司", "民事起诉状。原告：星河演示公司", False),
    ("星河演示公司", "甲方：星河演示公司", "委托合同。甲方：星河演示公司", False),
    ("星河演示公司", "委托人：星河演示公司", "委托人：星河演示公司", True),
    ("星河演示公司", "甲方（委托人）：星河演示公司", "甲方（委托人）：星河演示公司", True),
    ("星河演示公司", "星河演示公司委托本所代理", "星河演示公司委托本所代理。", True),
    ("星河演示公司", "委托人：星河演示公司", "拟委托人：星河演示公司", False),
])
def test_client_requires_engagement_not_litigation_role(value, quote, page, expected):
    assert validate_fact("委托人", value, quote, page) is expected


@pytest.mark.parametrize("field,value,quote,expected", [
    ("履行情况", "支付10000元", "判决被告支付10000元", False),
    ("履行情况", "已履行", "被告已履行", True),
    ("履行情况", "履行完毕", "尚未履行完毕", False),
    ("履行情况", "尚未履行完毕", "尚未履行完毕", True),
    ("结案小结", "已支付10000元", "被告承诺已支付10000元后提供凭证", False),
    ("结案小结", "已支付10000元", "如被告已支付10000元，则撤回申请", False),
    ("结案小结", "已实际支付10000元", "银行回单记载被告已实际支付10000元", True),
    ("结案小结", "判决被告支付10000元", "判决被告支付10000元", True),
    ("收款金额", "10000元", "判决被告支付10000元", False),
    ("已收业务费", "10000元", "收据：实收律师费10000元", True),
    ("收款金额", "10000元", "预计实际收到10000元", False),
    ("结案小结", "已受偿", "申请人参与分配，但尚未确定受偿款；如已受偿应予扣除", False),
    ("委托人对服务质量意见", "满意", "本所希望委托人满意", False),
    ("委托人对服务质量意见", "满意", "委托人表示不满意", False),
    ("委托人对服务质量意见", "不满意", "委托人表示不满意", True),
    ("委托人对服务质量意见", "满意", "委托人对服务质量表示满意", True),
    ("委托人对服务质量意见", "希望改善沟通", "委托人提出希望改善沟通", True),
])
def test_completed_actions_and_feedback_are_not_inferred(field, value, quote, expected):
    assert validate_fact(field, value, quote, quote) is expected


def test_quote_cannot_crop_out_condition_or_negation_on_page():
    assert not validate_fact("履行情况", "已履行", "被告已履行", "若被告已履行，则通知本所。")
    assert not validate_fact("委托人对服务质量意见", "满意", "满意", "委托人表示不满意。")


@pytest.mark.parametrize("field", ["结案小结", "审（办）结果", "审(办)结果", "审办结果", "办案小结"])
@pytest.mark.parametrize("page", [
    "原告诉称：请求法院判决被告支付一百万元。",
    "诉讼请求：法院判决被告支付一百万元。",
    "申请人请求法院判决被告支付一百万元。",
    "原告主张：法院判决被告支付一百万元。",
    "拟由法院判决被告支付一百万元。",
    "如果法院判决被告支付一百万元，则另行协商。",
    "是否由法院判决被告支付一百万元，尚未确定。",
    "另案参考材料。法院判决被告支付一百万元。",
    "引用案例：法院判决被告支付一百万元。",
    "另案判决摘录。本院判决如下：法院判决被告支付一百万元。",
])
def test_outcome_cannot_turn_requests_proposals_conditions_or_other_cases_into_current_disposition(field, page):
    value = "法院判决被告支付一百万元"
    assert not validate_fact(field, value, value, page)


@pytest.mark.parametrize("value,page", [
    ("裁定终结执行", "申请事项：请求裁定终结执行。"),
    ("出具法律意见书", "本所计划出具法律意见书。"),
    ("咨询意见为修改付款条款", "拟提供的咨询意见为修改付款条款。"),
    ("已实际支付一百万元", "原告诉称：被告已实际支付一百万元。"),
    ("被告应当支付一百万元", "原告诉称：请求法院判决如下：被告应当支付一百万元。"),
    ("被告应当支付一百万元", "参考案例。判决如下：被告应当支付一百万元。"),
])
def test_outcome_source_context_is_required_even_for_business_or_performance_wording(value, page):
    assert not validate_fact("结案小结", value, value, page)


@pytest.mark.parametrize("value,page", [
    ("法院判决被告支付一百万元", "本案法院判决被告支付一百万元。"),
    ("被告应当支付一百万元", "本院判决如下：被告应当支付一百万元。"),
    ("被告应当支付一百万元", "原告诉称：请求支付二百万元。本院判决如下：被告应当支付一百万元。"),
    ("本院判决如下：被告应当支付一百万元", "原告诉称：请求支付二百万元。本院判决如下：被告应当支付一百万元。"),
    ("驳回原告其他诉讼请求", "本院判决如下：一、被告应当支付一百万元；二、驳回原告其他诉讼请求。"),
    ("终结本次执行程序", "本院裁定如下：终结本次执行程序。"),
    ("被告应当支付一百万元", "另案裁判仅供参考。本案判决如下：被告应当支付一百万元。"),
    ("咨询意见为补充付款条款", "咨询意见为补充付款条款。"),
    ("已出具法律意见书", "办理结果：已出具法律意见书。"),
    ("代书定稿已交付委托人", "本案办理结果：代书定稿已交付委托人。"),
    ("尚未支付一百万元", "履行情况记录：尚未支付一百万元。"),
])
def test_current_explicit_dispositions_and_business_results_remain_supported(value, page):
    assert validate_fact("结案小结", value, value, page)


def test_a_current_operative_obligation_is_not_actual_payment_and_repeated_quotes_use_their_own_context():
    value = "被告应当支付一百万元"
    page = "本院判决如下：" + value + "。"
    assert validate_fact("结案小结", value, value, page)
    assert not validate_fact("履行情况", value, value, page)
    assert not validate_fact("收款金额", "一百万元", "一百万元", page)
    repeated = "原告诉称：请求法院判决被告支付一百万元。本院判决如下：法院判决被告支付一百万元。"
    assert validate_fact("结案小结", "法院判决被告支付一百万元", "法院判决被告支付一百万元", repeated)


def test_a_previous_operative_heading_does_not_make_unrelated_footer_text_an_outcome():
    page = "本院判决如下：被告支付一百万元。书记员：虚构记录员。"
    assert not validate_fact("结案小结", "虚构记录员", "虚构记录员", page)


def test_literal_origin_and_whitespace_guards():
    assert validate_fact("案号", "（2026）虚民初1号", "案号：（2026）虚民初1号", "案号： （2026）虚民初 1号")
    assert not validate_fact("案号", "编造案号", "原文案号", "原文案号")
    assert not validate_fact("案号", "原文案号", "原文案号", "另一个页面")
    assert not validate_fact("案号", "", "", "原文案号")
    assert not validate_fact("案号", None, "原文案号", "原文案号")


def test_actual_synthetic_demo_contract_and_complaint_have_distinct_dates():
    # Load the project's real synthetic demonstration strings; never customer data.
    pages = runpy.run_path(str(Path(__file__).parents[1] / "web/backend/app/services/demo_materials.py"))["PAGES"]
    contract = "\n".join([pages[0][0], *pages[0][1]])
    complaint = "\n".join([pages[1][0], *pages[1][1]])
    assert validate_fact("收案日期", "2026年3月1日", "收案日期：2026年3月1日", contract)
    assert not validate_fact("收案日期", "2026年3月3日", "起诉日期：2026年3月3日", complaint)
    # OCR may merge all physical line breaks without sentence punctuation.
    assert validate_fact("收案日期", "2026年3月1日", "收案日期：2026年3月1日", contract.replace("\n", ""))


@pytest.mark.parametrize("field", ["委托人", "当事人", "对方当事人", "承办律师", "律师事务所", "案由", "案号", "审理法院", "审级", "合同号", "收案日期", "结案日期", "收费标准", "委托人电话", "地址", "结案小结", "未知新增字段"])
@pytest.mark.parametrize("value,quote", [("占位记录", "样本行01：占位记录"), ("材料索引", "校验行02：材料索引")])
def test_unrelated_verbatim_text_never_becomes_a_field(field, value, quote):
    assert not validate_fact(field, value, quote, "证据附页\n" + quote)


@pytest.mark.parametrize("field,value,quote,page", [
    ("承办律师", "张示例", "证人：张示例", "证人：张示例"),
    ("律师事务所", "星河演示律师事务所", "对方律师事务所：星河演示律师事务所", "对方律师事务所：星河演示律师事务所"),
    ("当事人", "星河演示公司", "对方当事人：星河演示公司", "对方当事人：星河演示公司"),
    ("对方当事人", "星河演示公司", "被告：星河演示公司", "被告：星河演示公司"),
    ("案由", "买卖合同纠纷", "证据名称：买卖合同纠纷", "证据名称：买卖合同纠纷"),
    ("审理法院", "示例市人民法院", "送达地址：示例市人民法院", "送达地址：示例市人民法院"),
    ("审级", "一审", "参考一审意见", "参考一审意见"),
    ("合同号", "借款2026-001", "合同编号：借款2026-001", "借款合同\n合同编号：借款2026-001"),
    ("收费标准", "5000元", "货款5000元", "货款5000元"),
    ("委托人电话", "13800000000", "对方当事人电话：13800000000", "对方当事人电话：13800000000"),
    ("地址", "示例市示例路1号", "对方地址：示例市示例路1号", "对方地址：示例市示例路1号"),
    ("承办律师", "陈示例", "承办律师：陈示例", "拟承办律师：陈示例"),
])
def test_plausible_value_still_requires_the_correct_role(field, value, quote, page):
    assert not validate_fact(field, value, quote, page)


@pytest.mark.parametrize("field,value,quote,page", [
    ("律师事务所", "岭南演示律师事务所", "律师事务所：岭南演示律师事务所", None),
    ("律师事务所", "岭南演示律师事务所", "委托代理人：陈示例，岭南演示律师事务所律师", None),
    ("承办律师", "陈示例", "承办律师：陈示例", None),
    ("承办律师", "陈示例", "受托人：陈示例，岭南演示律师事务所律师", None),
    ("当事人", "星河演示公司", "当事人：星河演示公司", None),
    ("对方当事人", "远山演示公司", "对方当事人：远山演示公司", None),
    ("案由", "买卖合同纠纷", "案由：买卖合同纠纷", None),
    ("案号", "（2026）粤0000民初1001号", "案号：（2026）粤0000民初1001号", None),
    ("审理法院", "示例市人民法院", "受理法院：示例市人民法院", None),
    ("合同号", "演示委托2026-001", "合同编号：演示委托2026-001", "委托代理合同\n合同编号：演示委托2026-001"),
    ("收费标准", "固定律师费人民币5000元", "收费标准：固定律师费人民币5000元", None),
    ("委托人电话", "13800000000", "委托人电话：13800000000", None),
    ("地址", "示例市示例路1号", "委托人地址：示例市示例路1号", None),
    ("结案小结", "咨询意见为补充付款条款", "咨询意见为补充付款条款", None),
    ("委托人", "虚构甲", "委托人：虚构甲", "法律咨询记录\n咨询日期：2026年3月3日\n委托人：虚构甲"),
])
def test_explicit_fictional_role_and_business_evidence_remains_supported(field, value, quote, page):
    assert validate_fact(field, value, quote, page or quote)


def test_retainer_scope_is_not_evidence_of_actual_trial_level():
    quote = "代理阶段：民事一审"
    assert not validate_fact("审级", "一审", quote, quote)


def test_all_contract_demo_identity_fee_and_date_labels_remain_valid():
    pages = runpy.run_path(str(Path(__file__).parents[1] / "web/backend/app/services/demo_materials.py"))["PAGES"]
    contract = "\n".join([pages[0][0], *pages[0][1]])
    expected = {"委托人": "星河演示贸易有限公司", "律师事务所": "岭南演示律师事务所", "承办律师": "陈示例",
                "对方当事人": "远山演示设备有限公司", "案由": "买卖合同纠纷", "收费标准": "固定律师费人民币5000元",
                "收案日期": "2026年3月1日"}
    for field, value in expected.items():
        assert validate_fact(field, value, field + "：" + value, contract), field
