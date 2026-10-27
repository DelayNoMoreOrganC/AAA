# -*- coding: utf-8 -*-
"""文书类型二次校验回归测试（纯逻辑，无 OCR/Word 依赖）。

重点防回归：_validate_document_type 的 execution 分支曾因引用未定义的
`prefix_200` 抛出 NameError，导致整条切分链路崩溃、doc_spans 归零、
识别率从可用直接掉到 0。本测试遍历各分支，确保任何输入都不抛异常，
并覆盖 execution 关键判定路径。
"""

import pdf_doc_locator as pdl
import document_segmenter as ds


ALL_DOC_TYPES = [
    ds.DOC_TYPE_EXECUTION,
    ds.DOC_TYPE_JUDGMENT,
    ds.DOC_TYPE_RULING,
    ds.DOC_TYPE_MEDIATION,
    ds.DOC_TYPE_INDICTMENT,
    ds.DOC_TYPE_APPEAL,
    ds.DOC_TYPE_POA,
    ds.DOC_TYPE_INVOICE,
    ds.DOC_TYPE_SUMMONS,
]


def test_validate_never_raises_across_types():
    """任意文本 × 任意类型都不得抛异常（含曾崩溃的 execution 分支）。"""
    samples = [
        "",
        "短",
        "执行通知书 " * 50,  # 触发 execution indicator 分支（曾崩溃点）
        "民事裁定书\n本院认为……" + "正文" * 100,
        "强制执行申请" + "甲" * 300,
        "民事判决书\n如不服本判决" + "乙" * 300,
        "授权委托书 委托人 授权",
        "上诉状 不服一审",
    ]
    for text in samples:
        for dt in ALL_DOC_TYPES:
            # 不应抛出任何异常
            assert pdl._validate_document_type(text, dt) in (True, False)


def test_execution_indicator_branch():
    """前段含执行标识但无普通裁定书前缀 → 判为 execution（曾在此抛 NameError）。"""
    text = "执行通知书\n申请执行人……" + "内容" * 200
    assert pdl._validate_document_type(text, ds.DOC_TYPE_EXECUTION) is True


def test_execution_core_keyword():
    assert pdl._validate_document_type("执行裁定书 终结本次执行", ds.DOC_TYPE_EXECUTION) is True


def test_ruling_excludes_execution():
    """裁定书但满足执行条件的，不应被判为普通 ruling。"""
    text = "执行裁定书\n终结本次执行程序"
    assert pdl._validate_document_type(text, ds.DOC_TYPE_RULING) is False


def test_judgment_basic():
    assert pdl._validate_document_type("民事判决书 如不服本判决", ds.DOC_TYPE_JUDGMENT) is True
    # 含执行裁定书强标识时不应判为 judgment
    assert pdl._validate_document_type("执行裁定书 判决书", ds.DOC_TYPE_JUDGMENT) is False
