"""Shared, data-only form layout used by browser PDF and editable DOCX."""

def _cell(**kwargs):
    return kwargs


def _row(height: float, *cells):
    return {"height": height, "cells": list(cells)}


def _table(columns, rows, class_name=""):
    return {"type": "table", "columns": columns, "rows": rows, "className": class_name}


APPROVAL_TABLE = _table(
    [18.9, 20.8, 11.3, 13.2, 35.8],
    [
        _row(8.2, _cell(text="案件类别", align="center"), _cell(field="案件类别", align="center"), _cell(text="合同号", align="center"), _cell(field="合同号", colspan=2)),
        _row(8.2, _cell(text="委 托 人", align="center"), _cell(field="委托人", colspan=2), _cell(text="当事人", align="center"), _cell(field="当事人")),
        _row(8.2, _cell(text="委托人电话", align="center"), _cell(field="委托人电话", colspan=2), _cell(text="传 真", align="center"), _cell(field="传真")),
        _row(8, _cell(text="收费标准", align="center"), _cell(field="收费标准"), _cell(text="地 址", align="center"), _cell(field="地址", colspan=2)),
        _row(8.5, _cell(text="对方当事人", align="center"), _cell(field="对方当事人", colspan=4)),
        _row(25, _cell(prefix="案情简介：", field="案情简介", colspan=5, multiline=True, className="top-cell")),
        _row(35, _cell(text="承办律师意见：", colspan=5, align="left", className="top-cell", allowCustomInput=True)),
        _row(35, _cell(text="主任审批意见：", colspan=5, align="left", className="top-cell", allowCustomInput=True)),
        _row(9, _cell(prefix="立案日期：", field="立案审批日期", colspan=5)),
        _row(12, _cell(text="备  注：", colspan=5, align="left", className="top-cell", allowCustomInput=True)),
    ],
)

ARCHIVE_TABLE = _table(
    [18.7, 20.8, 12.1, 16.1, 3.8, 28.5],
    [
        _row(8, _cell(text="案件类别", align="center"), _cell(field="案件类别", align="center"), _cell(text="合同号", align="center"), _cell(field="合同号", colspan=3)),
        _row(8, _cell(text="承办律师", align="center"), _cell(field="承办律师", colspan=5)),
        _row(8, _cell(text="委 托 人", align="center"), _cell(field="委托人", colspan=5)),
        _row(8, _cell(text="当 事 人", align="center"), _cell(field="当事人", colspan=5)),
        _row(8, _cell(text="对方当事人", align="center"), _cell(field="对方当事人", colspan=5)),
        _row(15, _cell(text="案   由", align="center"), _cell(field="案由", colspan=5, multiline=True)),
        _row(10.8, _cell(text="收案日期", align="center"), _cell(field="收案日期", colspan=2, align="center"), _cell(text="结案日期", align="center"), _cell(field="结案日期", colspan=2, align="center")),
        _row(14.6, _cell(text="审理法院", align="center"), _cell(field="审理法院", colspan=2, multiline=True), _cell(text="审 级", align="center"), _cell(field="审级", colspan=2, align="center")),
        _row(19, _cell(text="法院收案号", align="center"), _cell(field="法院收案号", colspan=5, multiline=True)),
        _row(23, _cell(text="审（办）结果", align="center"), _cell(field="审（办）结果", colspan=5, multiline=True)),
        _row(9, _cell(text="归档日期", align="center"), _cell(field="归档日期", colspan=5, align="center")),
        _row(10, _cell(text="立 卷 人", align="center"), _cell(field="立卷人", colspan=2, align="center"), _cell(text="卷内页数", colspan=2, align="center"), _cell(derived="volume_page_count", suffix=" 页", align="right")),
        _row(10, _cell(text="档 案 号", align="center"), _cell(field="档案号", colspan=2), _cell(text="保存年限", colspan=2, align="center"), _cell(field="保存期限")),
        _row(11, _cell(text="备    注", align="center"), _cell(text="", colspan=5)),
    ],
)

CLOSE_REPORT_TABLE = _table(
    [11.2, 7.3, 6.8, 29.3, 7.8, 10.3, 0.8, 26.8],
    [
        _row(12, _cell(text="案  件  类  别", colspan=3, align="center"), _cell(field="案件类别", colspan=5, align="center")),
        _row(12, _cell(text="委 托 人 名 称", colspan=3, align="center"), _cell(field="委托人", colspan=5)),
        _row(12, _cell(text="案件或项目名称", colspan=3, align="center"), _cell(field="案件或项目名称", colspan=5, multiline=True)),
        _row(43.4, _cell(text="结\n案\n小\n结", align="center"), _cell(field="结案小结", colspan=7, multiline=True, className="top-cell")),
        _row(44, _cell(text="委\n托\n人\n对\n服\n务\n质\n量\n意\n见", align="center", className="vertical-label"), _cell(field="委托人对服务质量意见", colspan=7, multiline=True, className="top-cell")),
        _row(12, _cell(text="应收业务费", colspan=2, align="center"), _cell(field="应收业务费", colspan=2, align="center"), _cell(text="已收业务费", colspan=3, align="center"), _cell(field="已收业务费", align="center")),
        _row(12, _cell(text="尚欠业务费", colspan=2, align="center"), _cell(field="尚欠业务费", colspan=2, align="center"), _cell(text="应退业务费", colspan=3, align="center"), _cell(field="应退业务费", align="center")),
        _row(20.7, _cell(text="承办律师\n意    见", colspan=2, align="center"), _cell(text="", colspan=6)),
        _row(22, _cell(text="主    任\n审批意见", colspan=2, align="center"), _cell(text="", colspan=6)),
        _row(12, _cell(text="结案日期", colspan=2, align="center"), _cell(field="结案日期", colspan=3, align="center"), _cell(text="备注", align="center"), _cell(text="", colspan=2)),
    ],
)

QUALITY_TABLE = _table(
    [13.3, 6.7, 20, 4.4, 17.8, 37.8],
    [
        _row(8.1, _cell(text="律师事务所", colspan=2, align="center"), _cell(field="律师事务所", colspan=4, align="center")),
        _row(8.2, _cell(text="案号", align="center"), _cell(field="法院收案号", colspan=3), _cell(text="承办律师", align="center"), _cell(field="承办律师")),
        _row(8, _cell(text="委托人联系地址及电话", colspan=3, align="center"), _cell(field="委托人联系地址及电话", colspan=3)),
    ],
)

DELIVERY_ROWS = [
    _row(20, _cell(text="序号", align="center"), _cell(text="材料名称", align="center"), _cell(text="页数", align="center"), _cell(text="送达\n时间", align="center"), _cell(text="送达人", align="center"), _cell(text="接收人", align="center"), _cell(text="备注", align="center")),
    _row(12.5, _cell(text="1", align="center"), _cell(text="委托代理合同", align="center"), _cell(text=""), _cell(text=""), _cell(text=""), _cell(text=""), _cell(text="")),
    _row(13, _cell(text="2", align="center"), _cell(text="委托人须知", align="center"), _cell(text="1", align="center"), _cell(text=""), _cell(text=""), _cell(text=""), _cell(text="")),
    _row(13, _cell(text="3", align="center"), _cell(text="律师所收款发票", align="center"), _cell(text="1", align="center"), _cell(text=""), _cell(text=""), _cell(text=""), _cell(text="")),
    _row(12.5, _cell(text="4", align="center"), _cell(text="质量监督卡", align="center"), _cell(text="1", align="center"), _cell(text=""), _cell(text=""), _cell(text=""), _cell(text="")),
]
for index in range(5):
    DELIVERY_ROWS.append(_row(13, _cell(text=str(index + 5), align="center"), _cell(linesField="法院文件清单", lineIndex=index, remainingLines=index == 4, multiline=True), *[_cell(text="") for _ in range(5)]))
DELIVERY_ROWS.append(_row(12.5, *[_cell(text="") for _ in range(7)]))
DELIVERY_TABLE = _table([6.9, 28.3, 6.6, 16.6, 12.9, 12.9, 10.2], DELIVERY_ROWS)

QUALITY_QUESTIONS = [
    "是否由律师事务所与委托人签订委托代理合同",
    "是否由律师事务所向委托人收取律师费并如实出具发票",
    "接受委托后承办律师是否在律师费外收取了其他额外报酬或财物",
    "接受委托前承办律师是否向委托人作过虚假承诺",
    "接受委托后承办律师是否有无正当理由而不按时出庭参加诉讼、仲裁或有其他拒绝辩护、代理现象",
    "接受委托后承办律师是否有敷衍推诿、不尽职尽责的现象",
    "在委托代理合同中约定代收有关法律文书的，承办律师是否及时向委托人送达判决书、调解书、裁定书等法律文书",
    "承办律师与委托人是否办妥本案有关证据资料的交接手续",
]

CLIENT_NOTICE = [
    "为了保障委托人、律师事务所及律师各方的合法权益，根据《中华人民共和国律师法》及《律师执业行为规范》等有关规定，律师接受委托的，应当告知委托人如下事项：",
    "一、委托人要求律师办理的事项应当合法，不得要求律师通过不正当手段与办案机关、政府部门及其工作人员进行沟通，不得要求承办律师对委托事项的办理结果作出承诺。",
    "二、委托人应当按照委托合同的约定，按时、足额支付律师费。以下情况律师事务所不予退费：（1）委托人同时委托他人的；（2）律师完成委托事项后，无正当理由委托人认为结果不理想，或者认为律师事务所收费过高的；（3）非因受托人原因，委托人终止委托合同的；（4）委托合同约定的其他情形。",
    "三、委托人的委托的诉讼或非诉讼事项均具有不同程度的法律风险，律师承办的业务受到办案机关、政府部门和相关当事方的制约，委托人的主张及律师的法律意见有部分或全部不被采纳的可能。",
    "四、委托人有权向承办律师了解委托事项的办理情况。",
    "五、律师执业必须遵守宪法和法律，恪守律师职业道德和执业纪律。律师执业必须以事实为根据，以法律为准绳。",
    "六、律师不得以诋毁其他律师事务所、律师，支付介绍费，向当事人明示或者暗示与办案机关、政府部门及其工作人员有特殊关系等不正当手段承揽业务，不得以不实宣传等方式承揽业务。",
    "七、律师承办业务，须由律师事务所与委托人签订书面委托合同，按有关规定收取律师费，并向委托人统一开具发票。律师不得私自接受委托，私自向委托人收取费用或财物。",
    "八、律师不得以非律师身份从事法律服务。",
    "九、委托人发现承办律师在履行委托合同过程中执业有违规行为的，可以向承办律师所在律师所、律师协会及司法行政部门投诉。",
    "委托人确认，委托人已知晓上述内容。",
]

# Preserved only for tracing the repository's historical source template.
# These unverified dates and contact numbers are not rendered as current advice.
HISTORICAL_NOTICE_REFERENCE = {
    "subtitle": "（2004年11月5日广东省律师协会第七届理事会第五次会议通过，2018年2月8日广东省律师协会第十一届常务理事会第八次会议修订）",
    "complaint_phones": "佛山市司法局：83331692；佛山市律师协会：83321801；禅城区司法局：66611111--4；南海区司法局：81210925；顺德区司法局：22830122；三水区司法局：87731873；高明区司法局：88882966",
    "verification": "historical_reference_unverified",
}

FORM_LAYOUTS = {
    "立案审批表": [{"title": "立 案 审 批 表", "subtitleFromOrganization": True, "blocks": [APPROVAL_TABLE]}],
    "档案卷宗": [{"title": "律师业务档案卷宗（诉讼类）", "subtitleFromOrganization": True, "titleClass": "archive-title", "blocks": [ARCHIVE_TABLE]}],
    "结案报告表": [{"title": "结 案 报 告 表", "subtitleFromOrganization": True, "blocks": [CLOSE_REPORT_TABLE]}],
    "送达材料清单": [{
        "title": "律师所送达材料清单",
        "blocks": [
            {"type": "paragraph", "className": "delivery-meta case-number", "runs": [{"text": "案号："}, {"field": "法院收案号"}]},
            {"type": "paragraph", "className": "delivery-meta", "runs": [{"text": "委托方："}, {"field": "委托人"}]},
            {"type": "paragraph", "className": "delivery-meta", "runs": [{"text": "承办律师："}, {"field": "承办律师"}]},
            {"type": "text", "className": "delivery-note", "text": "律师在接办案件中填写，若送达给当事人的内容多，律师可视情况在空白栏目添加。"},
            DELIVERY_TABLE,
        ],
    }],
    "质量监督卡": [
        {"title": "律 师 办 案 质 量 监 督 卡", "blocks": [
            QUALITY_TABLE,
            {"type": "questions", "questions": QUALITY_QUESTIONS},
            {"type": "text", "className": "quality-evaluation", "text": "9、对承办律师办理本案总的评价　　好□　较好□　一般□　较差□　差□"},
            {"type": "text", "className": "quality-suggestion", "text": "10、对律师办理本案的意见和建议（内容较多可另附页）"},
            {"type": "text", "className": "quality-signature", "text": "委托人（签章）：　　　　　　　　　年　　月　　日"},
            {"type": "text", "className": "quality-note", "text": "说明：此卡由律师事务所在办理委托手续时，与背面的《委托人须知》一起发给委托人，由委托人签收。案件办结后，请委托人填写此卡并及时交回律师事务所；如有不便，也可直接将此卡交该律师事务所的主管司法局或市律师协会。"},
        ]},
        {"title": "委 托 人 须 知", "subtitle": "历史参考待律所核定；现行适用内容请由律所确认。", "titleClass": "notice-title", "blocks": [
            *[{"type": "text", "className": "notice-paragraph", "text": text} for text in CLIENT_NOTICE],
            {"type": "text", "className": "notice-signature", "text": "委托人（签章）：　　　　　　　　　年　　月　　日"},
            {"type": "text", "className": "complaint-phones", "text": "投诉渠道：请向所属律所核实主管司法局及律师协会的现行渠道。"},
        ]},
    ],
}


def form_title(template_name: str, page: dict, fields: dict | None) -> str:
    title = page.get("title", "")
    if template_name == "档案卷宗":
        category = str((fields or {}).get("案件类别") or "").strip()
        if category in ("非诉", "顾问", "法律顾问", "仲裁", "咨询代书", "nonlit", "counsel", "arbitration", "consultation"):
            return "律师业务档案卷宗（非诉讼类）"
        if category not in ("民事", "刑事", "行政", "civil", "criminal", "admin"):
            return "律师业务档案卷宗"
    return title


