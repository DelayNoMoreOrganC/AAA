import pytest

from app.services.preview_fields import (
    build_preview,
    sanitize_preview_custom_values,
    sanitize_preview_styles,
    sanitize_preview_updates,
)


@pytest.mark.parametrize(
    ("case_label", "expected_label"),
    [
        ("刑事", "本所代理或辩护的当事人"),
        ("行政", "本所代理的当事人"),
        ("非诉", "项目委托人"),
        ("法律顾问", "顾问单位"),
    ],
)
def test_preview_uses_case_specific_role_labels(case_label, expected_label):
    preview = build_preview("档案卷宗", {"案件类别": case_label, "当事人": "甲"})
    by_key = {item["key"]: item for item in preview["fields"]}
    assert by_key["当事人"]["label"] == expected_label
    assert by_key["当事人"]["value"] == "甲"


def test_preview_update_rejects_fields_outside_selected_form():
    cleaned = sanitize_preview_updates(
        "质量监督卡",
        {"委托人": "不应写入", "法院收案号": "（2024）粤0605号", "承办律师": "李律师"},
    )
    assert cleaned == {"法院收案号": "（2024）粤0605号", "承办律师": "李律师"}


def test_fax_archive_number_and_retention_have_editable_slots_without_defaults():
    fields={'委托人传真':'0000-12345678','档案号':'虚构归档-2026-001','保存年限':'经律所核定值'}
    approval={r['key']:r['value'] for r in build_preview('立案审批表',fields)['fields']}
    cover={r['key']:r['value'] for r in build_preview('档案卷宗',fields)['fields']}
    assert approval['传真']==fields['委托人传真']
    assert cover['档案号']==fields['档案号'] and cover['保存期限']==fields['保存年限']
    assert sanitize_preview_updates('立案审批表',{'传真':'0000-87654321','档案号':'other'})=={'传真':'0000-87654321'}
    assert sanitize_preview_updates('档案卷宗',{'档案号':'archive','保存期限':'manual'})=={'档案号':'archive','保存期限':'manual'}
    blank={r['key']:r['value'] for r in build_preview('档案卷宗',{})['fields']}
    assert blank['档案号']==blank['保存期限']==''
    fields.update(传真='',保存期限='',_provenance={'传真':[{'method':'human','value':''}],
                                               '保存期限':[{'method':'human','value':''}]})
    assert next(r for r in build_preview('立案审批表',fields)['fields'] if r['key']=='传真')['value']==''
    assert next(r for r in build_preview('档案卷宗',fields)['fields'] if r['key']=='保存期限')['value']==''


def test_preview_fields_follow_word_template_writable_cells():
    close_report = build_preview("结案报告表", {})
    assert [item["key"] for item in close_report["fields"]] == [
        "案件类别",
        "委托人",
        "案件或项目名称",
        "结案小结",
        "委托人对服务质量意见",
        "应收业务费",
        "已收业务费",
        "尚欠业务费",
        "应退业务费",
        "结案日期",
    ]

    quality_card = build_preview("质量监督卡", {})
    assert [item["key"] for item in quality_card["fields"]] == [
        "律师事务所",
        "法院收案号",
        "承办律师",
        "委托人联系地址及电话",
    ]


def test_preview_styles_keep_only_supported_cell_formatting():
    cleaned = sanitize_preview_styles(
        "送达材料清单",
        {
            "line:法院文件清单:0": {
                "fontFamily": 'KaiTi, STKaiti, "Noto Serif CJK SC", serif',
                "fontSize": "14pt",
                "fontWeight": "bold",
                "textAlign": "center",
                "color": "#AABBCC",
                "position": "fixed",
            },
            "invalid:key:extra": {"fontSize": "100pt"},
        },
    )
    assert cleaned == {
        "line:法院文件清单:0": {
            "fontFamily": 'KaiTi, STKaiti, "Noto Serif CJK SC", serif',
            "fontSize": "14pt",
            "fontWeight": "bold",
            "textAlign": "center",
            "color": "#aabbcc",
        }
    }


def test_client_feedback_is_blank_by_default_and_can_be_saved():
    preview = build_preview("结案报告表", {})
    by_key = {item["key"]: item for item in preview["fields"]}
    assert not by_key["委托人对服务质量意见"]["value"]
    feedback = "委托人提出需改进沟通频率"
    assert sanitize_preview_updates("结案报告表", {"委托人对服务质量意见": feedback}) == {
        "委托人对服务质量意见": feedback,
    }


def test_preview_custom_text_boxes_use_stable_layout_keys():
    cleaned = sanitize_preview_custom_values(
        "立案审批表",
        {
            "p0-b0-r6-c0": "承办律师补充意见",
            "../../unsafe": "ignored",
            "p0-b0-r99-c1": "x" * 6000,
        },
    )
    assert cleaned["p0-b0-r6-c0"] == "承办律师补充意见"
    assert len(cleaned["p0-b0-r99-c1"]) == 5000
    assert "../../unsafe" not in cleaned
