#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 文本按文书类型分段"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# 调试输出函数
def log(msg: str):
    """调试输出"""
    print(msg)

DOC_TYPE_JUDGMENT = "judgment"
DOC_TYPE_EXECUTION = "execution"
DOC_TYPE_CONTRACT = "contract"
DOC_TYPE_AGENCY_NOTICE = "agency_notice"
DOC_TYPE_COMPLAINT = "complaint"
DOC_TYPE_OTHER = "other"
DOC_TYPE_UNKNOWN = "unknown"
DOC_TYPE_DEFAULT = "default"

# V4 新增文书类型常量
DOC_TYPE_POA = "poa"
DOC_TYPE_RULING = "ruling"
DOC_TYPE_MEDIATION = "mediation"
DOC_TYPE_INDICTMENT = "indictment"
DOC_TYPE_APPEAL = "appeal"
DOC_TYPE_SUMMONS = "summons"
DOC_TYPE_COURT_RECORD = "court_record"
DOC_TYPE_INVOICE = "invoice"
DOC_TYPE_EVIDENCE = "evidence"
DOC_TYPE_PLEA = "plea"
DOC_TYPE_AGENT_OPINION = "agent_opinion"
DOC_TYPE_REVIEW_RECORD = "review_record"
DOC_TYPE_GROUP_DISCUSSION = "group_discussion"
DOC_TYPE_PRESERVATION = "preservation"
DOC_TYPE_INVESTIGATION = "investigation"
DOC_TYPE_CLIENT_TALK = "client_talk"
# Distinct source-document kinds already present in the firm's five catalogs.
# A kind identifies material; it never certifies signing, performance or service.
DOC_TYPE_MEETING_RECORD = "meeting_record"
DOC_TYPE_LEGAL_WORK = "legal_work"
DOC_TYPE_CLIENT_INTRO = "client_intro"
DOC_TYPE_WORK_RECORD = "work_record"
DOC_TYPE_AGREEMENT_STATUS = "agreement_status"

DOC_TYPE_LABELS = {
    "intake_approval": "已有立案审批表",
    "closure_report": "已有律所结案报告表",
    "service_list": "已有律师所送达材料清单",
    "quality_card": "已有律师办案质量监督卡",
    "client_notice": "已有委托人须知",
    "firm_letter": "律师事务所函",
    "acceptance_notice": "普通受理通知书",
    DOC_TYPE_DEFAULT: "默认（综合文档）",
    DOC_TYPE_JUDGMENT: "判决书",
    DOC_TYPE_EXECUTION: "执行裁定书",
    DOC_TYPE_CONTRACT: "委托代理合同",
    DOC_TYPE_AGENCY_NOTICE: "委托代理通知书（不等同已签合同）",
    DOC_TYPE_COMPLAINT: "起诉状",
    DOC_TYPE_OTHER: "其他",
    DOC_TYPE_UNKNOWN: "未分类文书",
    # V4 新增标签
    DOC_TYPE_POA: "授权委托书",
    DOC_TYPE_RULING: "裁定书",
    DOC_TYPE_MEDIATION: "调解书",
    DOC_TYPE_INDICTMENT: "起诉书/抗诉书",
    DOC_TYPE_APPEAL: "上诉状/上诉书",
    DOC_TYPE_SUMMONS: "出庭通知书",
    DOC_TYPE_COURT_RECORD: "庭审笔录",
    DOC_TYPE_INVOICE: "发票/收费凭证",
    DOC_TYPE_EVIDENCE: "证据材料清单",
    DOC_TYPE_PLEA: "代理词/辩护词",
    DOC_TYPE_AGENT_OPINION: "代理/辩护意见",
    # 新增手动材料类型标签
    DOC_TYPE_REVIEW_RECORD: "阅卷笔录/谈话笔录",
    DOC_TYPE_GROUP_DISCUSSION: "集体讨论记录",
    DOC_TYPE_PRESERVATION: "诉讼保全/证据保全",
    DOC_TYPE_INVESTIGATION: "调查材料",
    DOC_TYPE_CLIENT_TALK: "谈话记录",
    DOC_TYPE_MEETING_RECORD: "刑事会见笔录",
    DOC_TYPE_LEGAL_WORK: "非诉法律意见、草拟文书及法律事务工作记录",
    DOC_TYPE_CLIENT_INTRO: "顾问聘方基本情况材料",
    DOC_TYPE_WORK_RECORD: "顾问法律事务工作记录及有关材料",
    DOC_TYPE_AGREEMENT_STATUS: "顾问协议存续、中止、终止情况材料",
}

ANCHORS = {
    "intake_approval": ("立案审批表", "接案审批表", "收案审批表"),
    "closure_report": ("结案报告表", "律师结案报告表"),
    "service_list": ("律师所送达材料清单", "律师事务所送达材料清单"),
    "quality_card": ("律师办案质量监督卡", "律师服务质量监督卡"),
    "client_notice": ("委托人须知",),
    DOC_TYPE_JUDGMENT: (
        "刑事判决书",
        "行政判决书",
        "民事判决书",
        "判决书",
    ),
    DOC_TYPE_EXECUTION: (
        "执行裁定书",
        "终结本次执行程序",
        "恢复执行",
        # 【新增】更多执行相关锚点，提高识别率
        "执行通知书",
        "执行通知",
        "执行立案",
        "执行案件",
        "强制执行",
        "执行申请",
        "执行法院",
        "执行庭",
        "执字",  # 案号常用字头
        "执恢",
        "执异",
    ),
    DOC_TYPE_CONTRACT: (
        "委托代理合同",
        "法律服务合同",
        "代理合同",
        # 【新增】更多合同相关锚点
        "法律顾问合同",
        "委托合同",
        "代理协议",
        "法律服务协议",
        "民事代理合同",
        "刑事辩护合同",
    ),
    DOC_TYPE_COMPLAINT: (
        "行政起诉状",
        "民事起诉状",
        "起诉状",
    ),
    # V4 新增锚点
    DOC_TYPE_POA: (
        "授权委托书",
        "委托书",
    ),
    DOC_TYPE_RULING: (
        "裁定书",
    ),
    DOC_TYPE_MEDIATION: (
        "调解书",
    ),
    DOC_TYPE_INDICTMENT: (
        "起诉书",
        "公诉",
        "抗诉书",
    ),
    DOC_TYPE_APPEAL: (
        "上诉状",
        "上诉书",
    ),
    DOC_TYPE_SUMMONS: (
        "出庭通知书",
        "传票",
    ),
    DOC_TYPE_COURT_RECORD: (
        "庭审笔录",
        "开庭笔录",
    ),
    DOC_TYPE_INVOICE: (
        "发票",
        "收费凭证",
        "收据",
    ),
    DOC_TYPE_EVIDENCE: (
        "证据材料清单",
        "证据清单",
        "证据材料",
        "证据目录",
        "证据目录清单",
        # 证据清单常被 OCR 成无标题的表格，用表头列名作为锚点
        "证据名称",
        "证据来源",
    ),
    # 新增手动材料类型的OCR锚点（使用正确的doc_type常量作为键名）
    DOC_TYPE_REVIEW_RECORD: (
        "阅卷笔录",
        "谈话笔录",
        "会见笔录",
        "阅卷",
    ),
    DOC_TYPE_GROUP_DISCUSSION: (
        "集体讨论记录",
        "讨论记录",
        "集体讨论",
        "案件讨论",
    ),
    DOC_TYPE_PRESERVATION: (
        "诉讼保全",
        "证据保全",
        "先行给付",
        "保全申请书",
        "先予执行",
    ),
    DOC_TYPE_INVESTIGATION: (
        "调查材料",
        "调查笔录",
        "调查记录",
    ),
    DOC_TYPE_CLIENT_TALK: (
        "谈话记录",
        "委托人谈话",
        "当事人谈话",
    ),
    DOC_TYPE_PLEA: (
        "代理词",
        "辩护词",
    ),
    DOC_TYPE_AGENT_OPINION: (
        "代理意见",
        "辩护意见",
    ),
}

# 当事人之间的【业务合同/凭证】= 提交法院的证据(seq7)，非律所委托合同(seq3)。
# 仅当这些词作为「页面标题」（出现在页首）时才判证据，避免判决书正文引用《借款合同》误判。
BUSINESS_CONTRACT_TITLES = (
    "借款合同",
    "个人借款及担保合同",
    "购房借款及担保合同",
    "流动资金借款合同",
    "综合授信额度借款合同",
    "综合授信",
    "授信额度",
    "最高额保证担保合同",
    "最高额保证",
    "保证担保合同",
    "保证合同",
    "抵押合同",
    "担保合同",
    "分期还款协议",
    "借款借据",
    "借据",
    "购销合同",
    "买卖合同",
    "承兑协议",
    "欠息清单",
    "对账单",
)


FILENAME_HINTS = {
    DOC_TYPE_EXECUTION: ("执行裁定", "终本", "终结本次执行", "恢复执行", "execution"),
    DOC_TYPE_JUDGMENT: ("判决", "judgment"),
    DOC_TYPE_RULING: ("裁定", "ruling"),
    DOC_TYPE_MEDIATION: ("调解", "mediation"),
    DOC_TYPE_APPEAL: ("上诉", "appeal"),
    DOC_TYPE_INDICTMENT: ("起诉书", "公诉", "抗诉书", "indictment"),
    DOC_TYPE_COMPLAINT: ("起诉状", "答辩状", "答辩", "complaint"),
    DOC_TYPE_POA: ("授权委托", "授权", "委托书", "poa"),
    DOC_TYPE_CONTRACT: ("委托代理合同", "法律服务合同", "代理合同", "合同", "contract"),
    DOC_TYPE_SUMMONS: ("出庭通知", "传票", "summons"),
    DOC_TYPE_COURT_RECORD: ("笔录", "court_record"),
    DOC_TYPE_INVOICE: ("发票", "收费", "invoice"),
    DOC_TYPE_EVIDENCE: ("证据", "evidence"),
    DOC_TYPE_PLEA: ("代理词", "辩护词", "plea"),
    DOC_TYPE_AGENT_OPINION: ("代理意见", "辩护意见", "agent_opinion"),
    # 新增手动材料类型文件名提示
    DOC_TYPE_REVIEW_RECORD: ("阅卷", "谈话笔录", "会见笔录", "review"),
    DOC_TYPE_GROUP_DISCUSSION: ("讨论", "集体讨论", "discussion"),
    DOC_TYPE_PRESERVATION: ("保全", "先行给付", "preservation"),
    DOC_TYPE_INVESTIGATION: ("调查", "investigation"),
    DOC_TYPE_CLIENT_TALK: ("谈话", "client_talk"),
}


@dataclass
class DocumentSource:
    path: str
    doc_type: str = DOC_TYPE_DEFAULT
    pages: Optional[int] = None


@dataclass
class SegmentedText:
    segments: Dict[str, str] = field(default_factory=dict)
    full_text: str = ""

    def get(self, doc_type: str) -> str:
        return self.segments.get(doc_type, "")

    def combined_for_normalize(self) -> str:
        if self.full_text:
            return self.full_text
        parts = []
        for key in (
            DOC_TYPE_DEFAULT,
            DOC_TYPE_JUDGMENT,
            DOC_TYPE_EXECUTION,
            DOC_TYPE_CONTRACT,
            DOC_TYPE_COMPLAINT,
            DOC_TYPE_OTHER,
        ):
            text = self.segments.get(key, "")
            if text:
                parts.append(text)
        return "\n\n".join(parts)


def guess_doc_type_from_filename(path: str) -> str:
    name = (path or "").lower()
    for doc_type, hints in FILENAME_HINTS.items():
        if any(h in name for h in hints):
            return doc_type
    return DOC_TYPE_OTHER


def _find_anchor_positions(text: str) -> List[tuple]:
    """查找锚点位置，按优先级排序"""
    positions = []

    # 定义锚点优先级：更具体的锚点优先级更高
    ANCHOR_PRIORITY = {
        DOC_TYPE_INVOICE: 100,        # "发票"最具体
        DOC_TYPE_CONTRACT: 90,         # "委托代理合同"次之
        DOC_TYPE_SUMMONS: 85,          # "出庭通知书"比较具体
        DOC_TYPE_PLEA: 80,             # "代理词"比较具体
        DOC_TYPE_COURT_RECORD: 75,     # "庭审笔录"
        DOC_TYPE_AGENT_OPINION: 70,    # "代理意见"
        DOC_TYPE_REVIEW_RECORD: 65,    # "阅卷笔录"
        DOC_TYPE_GROUP_DISCUSSION: 60, # "集体讨论记录"
        DOC_TYPE_PRESERVATION: 55,     # "诉讼保全"
        DOC_TYPE_POA: 40,              # "授权委托书"较通用
        DOC_TYPE_COMPLAINT: 35,        # "起诉状"较通用
        DOC_TYPE_EVIDENCE: 20,         # "证据材料"最通用
        DOC_TYPE_JUDGMENT: 90,         # "判决书"具体
    }

    for doc_type, anchors in ANCHORS.items():
        for anchor in anchors:
            for m in re.finditer(re.escape(anchor), text):
                priority = ANCHOR_PRIORITY.get(doc_type, 50)
                positions.append((m.start(), doc_type, anchor, priority))

    # 按位置排序，如果位置相同则按优先级排序（高优先级在前）
    positions.sort(key=lambda x: (x[0], -x[3]))

    return positions


def segment_single_pdf_text(pdf_text: str, buffer: int = 500, log=print) -> SegmentedText:
    """单卷 PDF：按标题锚点切分文书段落"""
    if not pdf_text or len(pdf_text.strip()) < 50:
        return SegmentedText(full_text=pdf_text or "")

    log("       [ANCHOR_SCAN] 开始扫描锚点...")
    positions = _find_anchor_positions(pdf_text)
    if not positions:
        log("       [ANCHOR_SCAN] 未找到锚点")
        return SegmentedText(full_text=pdf_text)

    log(f"       [ANCHOR_SCAN] 找到{len(positions)}个锚点")
    segments: Dict[str, List[str]] = {}
    for i, (start, doc_type, anchor, priority) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(pdf_text)
        chunk_start = max(0, start - buffer)
        chunk = pdf_text[chunk_start:end].strip()
        if chunk:
            # 避免重复：同一doc_type只保留最高优先级的匹配
            if doc_type not in segments:
                segments[doc_type] = [chunk]
                log(f"       [ANCHOR] 优先级{priority}: {doc_type} <- \"{anchor[:30]}...\"")
            else:
                log(f"       [SKIP] 低优先级: {doc_type} <- \"{anchor[:30]}...\"")

    merged = {}
    for doc_type, chunks in segments.items():
        merged[doc_type] = "\n\n".join(chunks)

    log(f"       [ANCHOR_SCAN] 切分完成，识别到{len(merged)}种文书类型")
    return SegmentedText(segments=merged, full_text=pdf_text)

    merged = {}
    for doc_type, chunks in segments.items():
        merged[doc_type] = "\n\n".join(chunks)

    return SegmentedText(segments=merged, full_text=pdf_text)


def segment_from_sources(source_texts: Dict[str, str]) -> SegmentedText:
    """多文件模式：按 doc_type 直接映射；default 视为综合全文"""
    segments = {k: v for k, v in (source_texts or {}).items() if v and v.strip()}
    default_text = segments.pop(DOC_TYPE_DEFAULT, "")
    if default_text:
        segments.setdefault(DOC_TYPE_OTHER, "")
        segments[DOC_TYPE_OTHER] = (
            (segments[DOC_TYPE_OTHER] + "\n\n" + default_text).strip()
            if segments[DOC_TYPE_OTHER]
            else default_text
        )
    full = "\n\n".join(segments.values())
    return SegmentedText(segments=segments, full_text=full)


def build_segmented_from_units(
    units,
    page_texts_by_path: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, str]:
    """从 WF2 doc_spans + 页文本构建分路提取用 segments（路径 A 单卷）。"""
    by_seq = build_segmented_from_units_by_seq(units, page_texts_by_path)
    segments: Dict[str, str] = {}
    page_texts_by_path = page_texts_by_path or {}
    for u in units or []:
        dt = getattr(u, "doc_type", None) or DOC_TYPE_OTHER
        if dt in (DOC_TYPE_UNKNOWN, DOC_TYPE_DEFAULT):
            dt = DOC_TYPE_OTHER
        path = getattr(u, "source_path", "") or ""
        pages = page_texts_by_path.get(path) or []
        if pages and u.start_page is not None and u.end_page is not None:
            chunk = "\n".join(
                (pages[i] or "").strip()
                for i in range(u.start_page, min(u.end_page, len(pages) - 1) + 1)
            ).strip()
        else:
            chunk = ""
        if not chunk:
            continue
        segments[dt] = (segments.get(dt, "") + "\n\n" + chunk).strip()
    # V6：catalog_seq 14/15 优先覆盖 judgment/execution 分路
    if by_seq.get(DOC_TYPE_JUDGMENT):
        segments[DOC_TYPE_JUDGMENT] = by_seq[DOC_TYPE_JUDGMENT]
    if by_seq.get(DOC_TYPE_EXECUTION):
        segments[DOC_TYPE_EXECUTION] = by_seq[DOC_TYPE_EXECUTION]
    return segments


def build_segmented_from_units_by_seq(
    units,
    page_texts_by_path: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, str]:
    """按 catalog_seq 14/15 定向取判决/执行文本（V6 字段分路）。"""
    page_texts_by_path = page_texts_by_path or {}
    out: Dict[str, str] = {}

    def _chunk_unit(u) -> str:
        path = getattr(u, "source_path", "") or ""
        pages = page_texts_by_path.get(path) or []
        sp = getattr(u, "start_page", None)
        ep = getattr(u, "end_page", None)
        if not pages or sp is None or ep is None:
            return ""
        return "\n".join(
            (pages[i] or "").strip()
            for i in range(sp, min(ep, len(pages) - 1) + 1)
        ).strip()

    j_parts, e_parts = [], []
    for u in units or []:
        seq = getattr(u, "catalog_seq", None)
        c = _chunk_unit(u)
        if not c:
            continue
        if seq == 14:
            j_parts.append(c)
        elif seq == 15:
            e_parts.append(c)
        elif getattr(u, "doc_type", "") == DOC_TYPE_EXECUTION and not e_parts:
            e_parts.append(c)
        elif getattr(u, "doc_type", "") in (DOC_TYPE_JUDGMENT, DOC_TYPE_MEDIATION, DOC_TYPE_RULING) and not j_parts:
            j_parts.append(c)
    if j_parts:
        out[DOC_TYPE_JUDGMENT] = "\n\n".join(j_parts)
    if e_parts:
        out[DOC_TYPE_EXECUTION] = "\n\n".join(e_parts)
    return out


def build_segmented_text(
    pdf_text: str = "",
    sources: Optional[List[DocumentSource]] = None,
    source_texts: Optional[Dict[str, str]] = None,
) -> SegmentedText:
    """统一入口：多文件 source_texts 优先，否则单 PDF 切分。"""
    if source_texts:
        return segment_from_sources(source_texts)
    return segment_single_pdf_text(pdf_text)


def validate_sources_for_archive(sources: List[DocumentSource]) -> Optional[str]:
    """校验多文件输入；返回错误信息或 None"""
    if not sources:
        return "未选择任何 PDF 文件"
    types = {s.doc_type for s in sources}
    only_default = types <= {DOC_TYPE_DEFAULT}
    if not only_default and DOC_TYPE_JUDGMENT not in types and DOC_TYPE_EXECUTION not in types:
        return "至少需要一份「判决书」或「执行裁定书」（或使用「默认（综合文档）」）"
    for s in sources:
        if not s.path:
            return "存在空文件路径"
    return None
