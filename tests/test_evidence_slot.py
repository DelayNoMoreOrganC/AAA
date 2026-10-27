# -*- coding: utf-8 -*-
"""证据材料槽业务规则测试（无 OCR 依赖）。

规则：
- 「证据材料清单」即证据材料段的起始页 → 切到 evidence 槽。
- 无法辨别具体类型的文书一律归入「证据材料」槽。
"""

import archive_catalog as ac
import document_segmenter as ds
import pytest
from pdf_doc_locator import segment_by_catalog, _evidence_seq, _trial_seq


def _evidence_seq_for(case="civil"):
    return _evidence_seq(ac.get_catalog(case))


def _trial_seq_for(case="civil"):
    return _trial_seq(ac.get_catalog(case))


def test_judgment_body_keeps_trial_slot():
    """阶段锁定（§3）：裁判正文引用「证据/答辩」不得被证据锚点夺走。

    判决书正文常出现「原告提交下列证据」「被告没有答辩亦没有提供证据」，
    这些页必须留在审判槽(seq14)，不得切到证据(seq7)。
    """
    trial = _trial_seq_for()
    ev = _evidence_seq_for()
    pages = [
        "广东省佛山市南海区人民法院 民事判决书 (2014) 佛南法民二初字第480号 "
        "原告招商银行股份有限公司佛山分行……",
        "原告在诉讼中提交下列证据：经审查认定……",
        "两被告没有答辩亦没有提供证据。经审查，原告的证据来源合法，"
        "与本案相关联，本院予以确认，据此认定原告所述事实属实。",
        "一、被告曾立言应履行合同项下债务：1、归还贷款本金……",
        "审判长 郭焕桃 审判员 曾婉慧 书记员曹悦",
    ]
    units = segment_by_catalog(pages, "civil", log=lambda *a, **k: None)
    trial_units = [u for u in units if u.catalog_seq == trial]
    assert trial_units, "应存在审判槽单元"
    covered = set()
    for u in trial_units:
        covered.update(range(u.start_page, u.end_page + 1))
    # 判决书首页 + 正文(含证据/答辩引用) + 落款 均应留在审判槽
    assert {0, 1, 2, 3, 4}.issubset(covered), (
        f"裁判正文页应留在审判槽 seq{trial}，实际覆盖 {sorted(covered)}；"
        f"evidence={ev}"
    )
    # 关键断言：没有页被误切到证据槽
    ev_units = [u for u in units if u.catalog_seq == ev]
    assert not ev_units, (
        f"裁判正文不应被证据锚点夺走，但出现 evidence 段 {ev_units}"
    )


def test_evidence_list_starts_evidence_section():
    ev = _evidence_seq_for()
    pages = [
        "委托代理合同\n甲方：张三  乙方：某律师事务所\n服务内容……",
        "证据材料清单\n序号 名称 页数\n1 银行流水 3\n2 借条 1",
        "银行流水明细\n2019-01-01 转账 100000 元……",
        "借条\n今借到张三人民币壹拾万元整……",
    ]
    units = segment_by_catalog(pages, "civil", log=lambda *a, **k: None)
    # 「证据材料清单」所在页应为 evidence 段起始
    ev_units = [u for u in units if u.catalog_seq == ev]
    assert ev_units, "应存在 evidence 槽单元"
    start = min(u.start_page for u in ev_units)
    assert start == 1, f"证据材料段起始页应为「证据材料清单」页(1)，实际 {start}"
    # 清单之后无法辨别的页（银行流水/借条）应折叠进 evidence 槽
    covered = set()
    for u in ev_units:
        covered.update(range(u.start_page, u.end_page + 1))
    assert {1, 2, 3}.issubset(covered), f"证据页应归入 evidence 槽，实际覆盖 {covered}"



def test_trial_blocks_complaint_contract_citation():
    """阶段锁定兜底：裁判正文引用「送达起诉状副本」「《委托代理合同》」不得夺页。

    判决书正文常引用起诉状/合同名称，这些是正文引用而非新文书起点，
    必须留在审判槽(seq14)，不得切回起诉状(seq5)或合同(seq3)。
    """
    trial = _trial_seq_for()
    pages = [
        "广东省佛山市禅城区人民法院 民事判决书 (2019) 粤0604民初22131号 "
        "原告：佛山农村商业银行股份有限公司……",
        "被告金百纳公司辩称：确认本案借款……",
        "本院于2019年9月18日按《借款合同》约定司法送达地址向被告送达起诉状副本。"
        "截至庭审之日被告仍未还款。",
        "关于律师费。因案涉《民事委托代理合同》所约定的前期律师费的50%视为本案"
        "生效时间为支付条件……",
        "二、被告应于本判决生效之日起十日内向原告支付律师费1500元……",
    ]
    units = segment_by_catalog(pages, "civil", log=lambda *a, **k: None)
    trial_units = [u for u in units if u.catalog_seq == trial]
    assert trial_units, "应存在审判槽单元"
    covered = set()
    for u in trial_units:
        covered.update(range(u.start_page, u.end_page + 1))
    assert {0, 1, 2, 3, 4}.issubset(covered), (
        f"裁判正文页应留在审判槽 seq{trial}，实际覆盖 {sorted(covered)}"
    )
    seqs = {u.catalog_seq for u in units}
    assert 5 not in seqs, "裁判正文引用「起诉状」不得切回起诉状槽"
    assert 3 not in seqs, "裁判正文引用「委托代理合同」不得切回合同槽"

def test_real_complaint_and_contract_pages_still_classified():
    """起诉状/合同首页锚点在页首标题区，收紧 validate 后仍应正确识别类型。

    卷首(证据外)委托代理合同留在合同槽 seq3。
    """
    pages = [
        "民事委托代理合同 合同编号：202001号 甲方：张三 乙方：某律师事务所"
        " 第一条 代理范围 第二条 代理权限 第三条 律师费 第四条 甲方义务"
        " 第五条 合同变更 第六条 违约责任 第七条 争议解决 第八条 合同生效……",
        "民事委托代理合同 续页 委托期限届满后本合同自动终止……",
        "民事起诉状 原告：张三 住所地：某市某区 被告：李四 住所地：某市某区 "
        "诉讼请求：1、请求被告偿还借款……",
    ]
    units = segment_by_catalog(pages, "civil", log=lambda *a, **k: None)
    seqs = {u.catalog_seq for u in units}
    types = {u.doc_type for u in units}
    assert 5 in seqs, "真正的起诉状首页应识别为起诉状槽"
    assert ds.DOC_TYPE_CONTRACT in types, "真正的委托代理合同首页应识别为 contract 类型"
    assert 3 in seqs, "卷首(证据外)委托代理合同应留在合同槽 seq3"


def test_evidence_section_contract_goes_to_evidence():
    """证据段内的委托代理合同归证据(seq7)，不留在合同槽(seq3)。

    合同副本作为证据提交以证明律师费支出；证据外另有合同(重复)时只保留证据外。
    """
    ev = _evidence_seq_for()
    pages = [
        "民事委托代理合同 合同编号：A 卷首合同 甲方：张三 乙方：某律所……",  # 卷首合同 p0
        "民事起诉状 原告：张三 ……",  # 起诉状 p1
        "证据材料清单 序号 名称 ……",  # 证据清单 p2
        "民事委托代理合同 合同编号：A 续 甲方：张三 乙方：某律所……",  # 证据段合同副本 p3
        "民事委托代理合同 续页 ……",  # 续 p4
    ]
    units = segment_by_catalog(pages, "civil", log=lambda *a, **k: None)
    contract_units = [u for u in units if u.catalog_seq == 3]
    assert contract_units, "卷首合同应留在 seq3"
    assert contract_units[0].start_page == 0, "卷首合同 p0 在 seq3"
    ev_units = [u for u in units if u.catalog_seq == ev]
    assert ev_units, "证据段合同副本应归入证据槽 seq7"
    covered = set()
    for u in ev_units:
        covered.update(range(u.start_page, u.end_page + 1))
    assert {3, 4}.issubset(covered), (
        f"证据段内合同副本 p3-p4 应归 seq7，实际覆盖 {sorted(covered)}"
    )
def test_unidentifiable_unit_falls_into_evidence():
    ev = _evidence_seq_for()
    pages = [
        "某说明材料\n关于本案的一些情况说明……",   # 无明确文书类型
        "（续）补充说明若干……",
    ]
    units = segment_by_catalog(pages, "civil", log=lambda *a, **k: None)
    assert units, "应至少切出一个单元"
    for u in units:
        assert u.catalog_seq == ev, (
            f"无法辨别类型应归入 evidence 槽 seq{ev}，实际 seq{u.catalog_seq}"
        )
        assert u.doc_type == ds.DOC_TYPE_EVIDENCE


@pytest.mark.parametrize("title", ["证据附页", "补充证据材料", "原告证据目录", "第二组证据清单", "补充证据材料附页", "虚构证据附页"])
def test_standalone_evidence_heading_exits_judgment_without_layout(title):
    pages = ["示例市人民法院\n民事判决书\n判决如下：被告支付货款。",
             "本院认为原告提交的证据能够证明合同关系。",
             title + "\n序号1\n所附民事判决书仅为证据副本。",
             "流水记录续页，没有独立文书标题。"]
    units = segment_by_catalog(pages, "civil", config={}, log=lambda *_: None)
    slots = {page: unit.catalog_seq for unit in units for page in range(unit.start_page, unit.end_page + 1)}
    assert slots == {0: 14, 1: 14, 2: 7, 3: 7}
    assert sum(unit.end_page - unit.start_page + 1 for unit in units) == 4


@pytest.mark.parametrize("line", ["本院认为证据材料", "原告提交证据材料", "根据证据清单", "《证据清单》", "证据材料表明被告尚未支付。"])
def test_judgment_body_evidence_references_are_not_independent_titles(line):
    pages = ["示例市人民法院\n民事判决书\n判决如下", line + "\n法院继续论述事实及认定。"]
    units = segment_by_catalog(pages, "civil", config={}, log=lambda *_: None)
    assert all(unit.catalog_seq == 14 for unit in units)


def test_96_evidence_appendices_cannot_be_swallowed_by_prior_judgment():
    pages = ["委托代理合同\n委托人：虚构甲", "授权委托书\n授权律师办理本案", "民事起诉状\n原告：虚构甲", "民事判决书\n判决如下：被告支付货款。"]
    pages += [f"补充证据附页\n样本{index:03d}\n无新的案件事实。" for index in range(5, 101)]
    units = segment_by_catalog(pages, "civil", config={}, log=lambda *_: None)
    slots = {page: unit.catalog_seq for unit in units for page in range(unit.start_page, unit.end_page + 1)}
    assert len(slots) == 100
    assert all(slots[page] == 7 for page in range(4, 100))
    assert [(unit.start_page, unit.end_page) for unit in units if unit.doc_type == ds.DOC_TYPE_JUDGMENT] == [(3, 3)]
    from case_outcome import build_outcome_from_units
    outcome = build_outcome_from_units({}, units, {"": pages}, "\n".join(pages))["结案小结"]
    assert "货款" in outcome
    assert "附页" not in outcome and "样本" not in outcome and "无新的案件事实" not in outcome
