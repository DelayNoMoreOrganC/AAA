#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 文书定位器 — DocumentUnit 文书级切分与目录映射

以整份文书为单元：首页锚点定边界，无锚点页并入当前文书，全文 OCR 补充漏识别起点。
"""

import os
import re
import warnings
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

import archive_catalog as ac
import document_segmenter as ds

# 调试工具
try:
    from debug_matcher import get_debug_matcher
    DEBUG_AVAILABLE = True
except ImportError:
    DEBUG_AVAILABLE = False


def _wf1_ingest(
    pdf_path: str,
    config: dict,
    log=print,
) -> tuple:
    """WF1 统一摄入（禁止回退全卷 page_ocr.get_page_texts）"""
    from ocr_pipeline import ingest_pdf

    log("       WF1 摄入材料")
    result = ingest_pdf(pdf_path, config, log=log)
    return result.page_texts, result.full_text, result.layout_blocks or []

# 同页多锚点时，优先级高的类型胜出（越具体越高）
DOC_TYPE_PRIORITY = {
    ds.DOC_TYPE_EXECUTION: 100,
    ds.DOC_TYPE_JUDGMENT: 90,
    ds.DOC_TYPE_MEDIATION: 85,
    ds.DOC_TYPE_RULING: 80,
    ds.DOC_TYPE_APPEAL: 70,
    ds.DOC_TYPE_COMPLAINT: 60,
    ds.DOC_TYPE_CONTRACT: 55,
    ds.DOC_TYPE_POA: 50,
    ds.DOC_TYPE_SUMMONS: 45,
    ds.DOC_TYPE_COURT_RECORD: 44,
    ds.DOC_TYPE_AGENT_OPINION: 40,
    ds.DOC_TYPE_PLEA: 35,
    ds.DOC_TYPE_INVOICE: 30,
    ds.DOC_TYPE_EVIDENCE: 20,
    # 新增manual类型优先级（按重要性排序）
    getattr(ds, 'DOC_TYPE_PRESERVATION', 'preservation'): 28,  # 诉讼保全
    getattr(ds, 'DOC_TYPE_REVIEW_RECORD', 'review_record'): 26,  # 阅卷笔录
    getattr(ds, 'DOC_TYPE_GROUP_DISCUSSION', 'group_discussion'): 24,  # 集体讨论
    getattr(ds, 'DOC_TYPE_INVESTIGATION', 'investigation'): 22,  # 调查材料
    getattr(ds, 'DOC_TYPE_CLIENT_TALK', 'client_talk'): 18,  # 谈话记录
    ds.DOC_TYPE_OTHER: 10,
    ds.DOC_TYPE_UNKNOWN: 5,
}


# 阶段细分（保全 vs 执行）：
# 「执行裁定书」可能是审判前的「财产/诉讼保全裁定」（案号「执保/财保/诉保」字号），
# 也可能是判决生效后的「强制执行裁定」（案号「执」字号）。前者归保全(seq8)，后者归执行(seq15)。
_PRESERVATION_CASE_RE = re.compile(
    r"执\s*保|财\s*保|诉\s*保|诉\s*前\s*财\s*产\s*保\s*全|财\s*产\s*保\s*全|证\s*据\s*保\s*全|保\s*全\s*申\s*请"
)
# 明确的强制执行标志：出现则保留执行（避免把含「保全」字样的真执行文书误归保全）。
_ENFORCE_MARK_RE = re.compile(
    r"终结本次执行|恢复执行|强制执行|限制消费|执行完毕|执行决定书|失\s*信|执\s*恢|拍卖|变卖|财产分配"
)


@dataclass
class DocumentUnit:
    """文书单元（整份连续页段）"""
    doc_id: int
    doc_type: str
    start_page: int
    end_page: int
    title: str = ""
    catalog_seq: Optional[int] = None
    source_path: str = ""
    score: float = 0.0
    confidence: float = 1.0
    manual_catalog_seq: Optional[int] = None


DocSpan = DocumentUnit


def _validate_document_type(text: str, doc_type: str) -> bool:
    """文书类型二次校验（防止锚点误匹配）

    规则：
    - execution：须含「执行裁定书」或「终结本次执行」或「恢复执行」
    - judgment：含「判决书」且前 200 字不含「执行」
    - ruling：含「裁定书」且不满足 execution 条件
    - mediation：须含「调解书」
    - indictment：含起诉/公诉/抗诉书锚点，且非明显上诉（防与 appeal 混淆）
    - appeal：含「上诉状/上诉书」或前段含「二审/不服一审」上诉强信号

    【优化】执行类文书识别增强：
    - 扩大execution锚点搜索范围（前800字）
    - 允许"执行"、"执行通知书"等执行相关关键词
    - 降低过于严格的验证要求，提高召回率
    """
    if doc_type == ds.DOC_TYPE_EXECUTION:
        # 【关键修复】扩大execution搜索范围并增强识别能力
        prefix_800 = text[:800] if len(text) > 800 else text
        prefix_200 = text[:200] if len(text) > 200 else text

        # 核心锚点优先
        core_keywords = ["执行裁定书", "终结本次执行", "恢复执行"]
        if any(keyword in text for keyword in core_keywords):
            return True

        # 【新增】支持执行相关关键词
        execution_indicators = [
            "执行通知书", "执行通知", "执行立案", "执行案件",
            "强制执行", "执行申请", "执行法院", "执行庭",
            "执字", "执恢", "执异"  # 执行案号常用字头
        ]

        # 如果前800字包含明确的执行相关标识，也认为是execution
        if any(indicator in prefix_800 for indicator in execution_indicators):
            # 进一步验证：确实不是普通的裁定书
            # 如果没有"民事裁定书"等前缀，更可能是执行类
            if not any(prefix in prefix_200 for prefix in ["民事裁定书", "行政裁定书", "刑事裁定书"]):
                return True

        # 至少包含"执行"二字，且在合理位置
        if "执行" in prefix_800:
            return True

        return False
    elif doc_type == ds.DOC_TYPE_JUDGMENT:
        # 【优化】判决书判断：要求明确的判决书标识
        # 但避免过度排斥execution相关内容
        prefix_300 = text[:300] if len(text) > 300 else text
        has_judgment = "判决书" in text
        # 只有在明确出现"执行裁定书"等强执行标识时才排除
        is_execution = any(kw in text for kw in ["执行裁定书", "执行通知书"])
        return has_judgment and not is_execution
    elif doc_type == ds.DOC_TYPE_RULING:
        # 裁定书需包含"裁定书"但不满足执行条件
        return "裁定书" in text and not _validate_document_type(text, ds.DOC_TYPE_EXECUTION)
    elif doc_type == ds.DOC_TYPE_MEDIATION:
        return "调解书" in text
    elif doc_type == ds.DOC_TYPE_INDICTMENT:
        prefix_200 = text[:200] if len(text) > 200 else text
        has_indict = any(k in text for k in ("起诉书", "公诉", "抗诉书"))
        # 当事人上诉状/上诉书不应被判为起诉书（消歧）
        is_appeal = any(k in prefix_200 for k in ("上诉状", "上诉书"))
        return has_indict and not is_appeal
    elif doc_type == ds.DOC_TYPE_APPEAL:
        prefix_200 = text[:200] if len(text) > 200 else text
        return (
            any(k in text for k in ("上诉状", "上诉书"))
            or any(k in prefix_200 for k in ("二审", "不服一审"))
        )
    elif doc_type == ds.DOC_TYPE_POA:
        # 「委托书」一词在合同等正文中常见，要求与「授权」共现以收紧
        return "授权委托书" in text or ("委托书" in text and "授权" in text)
    elif doc_type == ds.DOC_TYPE_INVOICE:
        # 发票/收据须真为票据页，排除判决/裁定/合同正文偶提「发票」
        head = text[:40]
        if any(k in head for k in ("判决书", "裁定书", "委托代理合同", "法律服务合同")):
            return False
        return any(k in text for k in ("发票", "收费凭证", "收据"))
    elif doc_type == ds.DOC_TYPE_SUMMONS:
        # 「传票」在笔录/判决正文中可能被引用，排除明显的其他文书页
        head = text[:40]
        if any(k in head for k in ("判决书", "裁定书", "笔录")):
            return False
        # 排除银行「特种转帐贷方传票」等非法院业务凭证（含「传票」但实为转账单）
        head200 = text[:200]
        if any(k in head200 for k in ("特种转帐", "贷方传票", "转帐贷方", "特种转账", "转账贷方")):
            if "人民法院" not in head200 and "法院" not in text[:100]:
                return False
        return any(k in text for k in ("出庭通知", "传票", "传唤"))
    elif doc_type == ds.DOC_TYPE_COMPLAINT:
        # 起诉状/答辩状在判决书正文常被引用（「送达起诉状副本」「《起诉状》」），
        # 排除这两类正文引用模式；其余（含真正的起诉状首页及其续页）照常通过。
        stripped = re.sub(r"《[^》]*》", "", text)
        if re.search(r"送达.{0,8}(起诉状|答辩状)", stripped):
            return False
        if re.search(r"(起诉状|答辩状)副本", stripped):
            return False
        return True
    elif doc_type == ds.DOC_TYPE_CONTRACT:
        # 判决书/执行文书正文常引用《民事委托代理合同》等；仅排除书名号包围的正文引用。
        # 续页（无锚点）不经过此处；真正的合同首页锚点在标题区，照常通过。
        stripped = re.sub(r"《[^》]*》", "", text)
        if re.search(r"(委托代理合同|代理合同|法律服务合同|委托合同)", stripped):
            return True
        return False
    return True  # 其他类型默认通过


def _classify_page_prefix(text: str, max_chars: int = 450) -> Tuple[str, str]:
    """仅根据页面上部文字判定文书类型（避免页内嵌套锚点误触发）

    【优化】对execution类型使用更大的搜索范围，因为执行类文书的特征字样
    可能出现在页面中后部，而不仅仅是顶部。
    """
    # 对于执行类文书，扩大搜索范围
    execution_keywords = ["执行裁定书", "执行通知书", "执行立案", "执行案件"]
    if any(kw in text[:800] for kw in execution_keywords):
        # 对execution类型使用更大的搜索范围
        prefix = (text or "")[:min(max_chars * 2, 800)]  # 扩大到最多800字
    else:
        prefix = (text or "")[:max_chars]

    if not prefix.strip():
        return ds.DOC_TYPE_OTHER, ""
    return _classify_page_text(prefix)


def _classify_page_text(text: str) -> Tuple[str, str]:
    """单页最佳文书类型（同页多锚点取优先级最高）"""
    if not text or len(text.strip()) < 2:
        return ds.DOC_TYPE_OTHER, ""

    heading = _match_evidence_heading(text)
    if heading:
        # A genuine evidence title can list judgments/contracts in its body.
        # Those cited document names must not override the page's own title.
        return ds.DOC_TYPE_EVIDENCE, heading

    best_type = ds.DOC_TYPE_OTHER
    best_pri = -1
    best_anchor = ""
    for doc_type, anchors in ds.ANCHORS.items():
        for anchor in anchors:
            if re.search(re.escape(anchor), text):
                # 二次校验：不通过则跳过此类型
                if not _validate_document_type(text, doc_type):
                    continue
                pri = DOC_TYPE_PRIORITY.get(doc_type, 0)
                if pri > best_pri:
                    best_pri = pri
                    best_type = doc_type
                    best_anchor = anchor

    # 阶段细分：执行裁定/裁定书若案号为「执保/财保」等保全字号，且无强制执行标志，
    # 实为（诉讼/财产）保全裁定 → 归保全(seq8)，而非执行(seq15)。
    if best_type in (ds.DOC_TYPE_EXECUTION, ds.DOC_TYPE_RULING):
        if _PRESERVATION_CASE_RE.search(text) and not _ENFORCE_MARK_RE.search(text):
            return ds.DOC_TYPE_PRESERVATION, "执保"

    # 业务合同/凭证作为页面标题（页首）时归证据(seq7)。仅在无更强锚点时触发，
    # 且要求标题出现在页首（排除判决书正文引用《借款合同》的误判）。
    if best_type == ds.DOC_TYPE_OTHER:
        bc = _match_business_contract_title(text)
        if bc:
            return ds.DOC_TYPE_EVIDENCE, bc
    return best_type, best_anchor


def _match_evidence_heading(text: str) -> str:
    """Strict standalone first-line evidence heading, never a body citation."""
    lines = [line.strip("#＃*-—·•　 \t") for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    title = lines[0]
    compact = re.sub(r"\s+", "", title)
    if re.search(r"认为|认定|提交|举示|质证|诉称|证实|证明|提供|依据|根据|如下|本院|本庭", compact):
        return ""
    if re.fullmatch(r"[\u3400-\u9fff]{0,12}证据(?:材料|清单|目录|附页|附件|汇编|一览表)(?:清单|目录|附页|附件|续页|汇编|一览表)?(?:[（(]?[一二三四五六七八九十0-9]+[）)]?)?", compact):
        return title
    return ""


def _match_business_contract_title(text: str) -> str:
    """页首是否为业务合同/凭证标题（借款/担保/授信/分期/借据/对账单…）。
    返回匹配到的标题词，否则空串。判决书正文中部引用的《借款合同》不会命中。"""
    if not text:
        return ""
    # 去除常见 OCR 前缀符号与空白，标题须位于页首（pos==0）。
    # 判决书/执行文书正文中部引用《借款合同》等不在页首，故不会命中。
    head = text.lstrip("#＃*-—·•　 \t\r\n")
    for title in ds.BUSINESS_CONTRACT_TITLES:
        if head.startswith(title):
            return title
    return ""


def _find_page_anchor_starts(page_texts: List[str]) -> List[Tuple[int, str, str]]:
    """页级 OCR：有锚点的页作为新文书起点"""
    starts = []
    for page_idx, text in enumerate(page_texts):
        doc_type, anchor = _classify_page_text(text)
        if doc_type != ds.DOC_TYPE_OTHER:
            starts.append((page_idx, doc_type, anchor))
    return starts


def _dedupe_starts(starts: List[Tuple[int, str, str]]) -> List[Tuple[int, str, str]]:
    """同页多锚点只保留优先级最高的一种类型"""
    by_page: dict = {}
    for page, doc_type, anchor in starts:
        pri = DOC_TYPE_PRIORITY.get(doc_type, 0)
        if page not in by_page or pri > by_page[page][0]:
            by_page[page] = (pri, doc_type, anchor)
    return [(p, by_page[p][1], by_page[p][2]) for p in sorted(by_page)]


def _enrich_starts_from_fulltext(
    starts: List[Tuple[int, str, str]],
    page_texts: List[str],
    pdf_text: str,
    log=print,
) -> List[Tuple[int, str, str]]:
    """MinerU 全文补充页级漏识别的文书起点"""
    if not pdf_text:
        return starts

    existing_pages = {s[0] for s in starts}
    existing_types = {s[1] for s in starts}
    segmented = ds.segment_single_pdf_text(pdf_text)
    extra = []

    for doc_type in segmented.segments:
        if doc_type in existing_types:
            continue
        anchors = ds.ANCHORS.get(doc_type, ())
        if not anchors:
            continue

        found_page = None
        matched_anchor = ""
        for page_idx, text in enumerate(page_texts):
            if any(a in (text or "") for a in anchors):
                found_page = page_idx
                matched_anchor = next(a for a in anchors if a in text)
                break

        if found_page is None:
            for anchor in anchors:
                if anchor not in pdf_text:
                    continue
                pos = pdf_text.find(anchor)
                ratio = pos / max(len(pdf_text), 1)
                found_page = min(int(ratio * len(page_texts)), len(page_texts) - 1)
                matched_anchor = anchor
                break

        if found_page is None or found_page in existing_pages:
            continue

        extra.append((found_page, doc_type, matched_anchor))
        existing_pages.add(found_page)
        log(
            f"       全文补起点: {ds.DOC_TYPE_LABELS.get(doc_type, '未知类型')} "
            f"(页{found_page})"
        )

    return starts + extra


def _enrich_starts_from_layout(
    starts: List[Tuple[int, str, str]],
    layout_blocks: List[dict],
    log=print,
) -> List[Tuple[int, str, str]]:
    """MinerU content_list 标题块补充文书起点"""
    if not layout_blocks:
        return starts

    existing_pages = {s[0] for s in starts}
    existing_types = {s[1] for s in starts}
    extra = []

    for block in layout_blocks:
        text = (block.get("text") or "").strip()
        if not text:
            continue
        page_idx = int(block.get("page_idx", 0))
        if page_idx in existing_pages:
            continue

        is_heading = block.get("text_level") is not None
        btype = (block.get("type") or "").lower()
        if not is_heading and btype not in ("text", "title"):
            continue

        doc_type, anchor = _classify_page_text(text)
        if doc_type == ds.DOC_TYPE_OTHER:
            continue
        if doc_type in existing_types:
            continue

        extra.append((page_idx, doc_type, anchor or text[:20]))
        existing_pages.add(page_idx)
        log(
            f"       layout 补起点: {ds.DOC_TYPE_LABELS.get(doc_type, '未知类型')} "
            f"(页{page_idx})"
        )

    return starts + extra


def _build_units_from_starts(
    starts: List[Tuple[int, str, str]],
    total_pages: int,
) -> List[DocumentUnit]:
    """由起点列表构建覆盖全部页的 DocumentUnit 列表"""
    if total_pages <= 0:
        return []

    deduped = _dedupe_starts(starts)
    units: List[DocumentUnit] = []
    doc_id = 0

    if not deduped:
        units.append(
            DocumentUnit(
                doc_id=0,
                doc_type=ds.DOC_TYPE_UNKNOWN,
                start_page=0,
                end_page=total_pages - 1,
                title="",
            )
        )
        return units

    first_start = deduped[0][0]
    if first_start > 0:
        units.append(
            DocumentUnit(
                doc_id=doc_id,
                doc_type=ds.DOC_TYPE_UNKNOWN,
                start_page=0,
                end_page=first_start - 1,
                title="",
            )
        )
        doc_id += 1

    for i, (start_page, doc_type, anchor) in enumerate(deduped):
        if i + 1 < len(deduped):
            end_page = deduped[i + 1][0] - 1
        else:
            end_page = total_pages - 1
        units.append(
            DocumentUnit(
                doc_id=doc_id,
                doc_type=doc_type,
                start_page=start_page,
                end_page=end_page,
                title=anchor,
            )
        )
        doc_id += 1

    return units


def _pdf_page_count(pdf_path: str) -> int:
    try:
        import fitz
        doc = fitz.open(pdf_path)
        n = doc.page_count
        doc.close()
        return n
    except Exception:
        try:
            from archive_ocr import get_pdf_page_count
            return get_pdf_page_count(pdf_path) or 0
        except ImportError:
            return 0


def build_units_from_sources(
    sources: List[Union[ds.DocumentSource, dict]],
    case_type: str,
    config: dict,
    *,
    pdf_texts: Optional[dict] = None,
    page_texts_by_path: Optional[dict] = None,
    layout_blocks_by_path: Optional[dict] = None,
    log=print,
) -> List[DocumentUnit]:
    """从多份分类 PDF 构建 DocumentUnit 列表（路径 B + 路径 A 综合卷）

    - doc_type=default：卷内 segment_by_catalog 切分
    - 其他类型：整文件 1 个 Unit
    """
    catalog = ac.get_catalog(case_type)
    pdf_texts = pdf_texts or {}
    page_texts_by_path = page_texts_by_path or {}
    layout_blocks_by_path = layout_blocks_by_path or {}
    all_units: List[DocumentUnit] = []
    doc_id = 0

    for source_index, raw in enumerate(sources, start=1):
        if isinstance(raw, ds.DocumentSource):
            src = raw
        else:
            src = ds.DocumentSource(
                path=raw.get("path", ""),
                doc_type=raw.get("doc_type") or ds.DOC_TYPE_DEFAULT,
            )

        if not src.path or not os.path.exists(src.path):
            log(f"       [WARN] 材料{source_index}不存在，已跳过")
            continue

        if src.doc_type == ds.DOC_TYPE_DEFAULT:
            log(f"       综合卷切分: 材料{source_index}")
            page_texts = page_texts_by_path.get(src.path)
            fulltext = pdf_texts.get(src.path)
            layout_blocks = layout_blocks_by_path.get(src.path) or []
            if not page_texts:
                page_texts, ingested_full, ingested_layout = _wf1_ingest(
                    src.path, config, log=log
                )
                if not fulltext:
                    fulltext = ingested_full
                if not layout_blocks:
                    layout_blocks = ingested_layout
            units = segment_by_catalog(
                page_texts,
                case_type,
                log=log,
                layout_blocks=layout_blocks,
                pdf_path=src.path,
                config=config,
            )
            for u in units:
                u.doc_id = doc_id
                u.source_path = src.path
                all_units.append(u)
                doc_id += 1
        else:
            n = _pdf_page_count(src.path)
            if n <= 0:
                log(f"       [WARN] 材料{source_index}无法读取页数")
                continue
            label = ds.DOC_TYPE_LABELS.get(src.doc_type, "未知类型")
            log(f"       分类材料{source_index} → {label} ({n}页)")
            all_units.append(
                DocumentUnit(
                    doc_id=doc_id,
                    doc_type=src.doc_type,
                    start_page=0,
                    end_page=n - 1,
                    title=os.path.basename(src.path),
                    source_path=src.path,
                )
            )
            doc_id += 1

    # 综合卷已在 segment_by_catalog 中分配 catalog_seq；分类文件仍需映射
    needs_map = [u for u in all_units if u.catalog_seq is None]
    if needs_map:
        assign_catalog_seq(needs_map, catalog, log=log)
    return all_units


def _merge_adjacent_same_type(units: List[DocumentUnit], page_texts: List[str], log=print) -> List[DocumentUnit]:
    """合并相邻的同类型文书单元（避免同一份跨页文书被误切）

    规则：
    - 相邻 unit 若 doc_type 相同，且下一页无「新文书」强信号，则并入当前 unit
    - 强信号：标题/anchor 明显不同（如「恢复执行」vs「执行裁定书」）
    """
    if not units or len(units) <= 1:
        return units

    merged = []
    i = 0
    while i < len(units):
        current = units[i]
        if i + 1 < len(units):
            next_unit = units[i + 1]
            # 检查是否应该合并：类型相同 + 标题相似（无强信号）
            if (
                current.end_page + 1 == next_unit.start_page
                and current.doc_type == next_unit.doc_type
                and current.doc_type not in (ds.DOC_TYPE_UNKNOWN, ds.DOC_TYPE_OTHER)
        ):
                # 检查标题是否相似（是否有新文书强信号）
                title_similar = _is_title_similar(current.title, next_unit.title, page_texts, current, next_unit)
                if title_similar:
                    # 合并为一个 unit
                    merged_unit = DocumentUnit(
                        doc_id=current.doc_id,
                        doc_type=current.doc_type,
                        start_page=current.start_page,
                        end_page=next_unit.end_page,
                        title=current.title,
                        score=current.score,
                    )
                    merged.append(merged_unit)
                    i += 2  # 跳过已合并的下一个 unit
                    continue

        # 不合并，保留原 unit
        merged.append(current)
        i += 1

    return merged


def _merge_adjacent_same_catalog_seq(units: List[DocumentUnit], log=print) -> List[DocumentUnit]:
    """映射后合并相邻、同 catalog_seq 且同类型的页段（避免同一份文书被误切）"""
    if len(units) <= 1:
        return units

    merged: List[DocumentUnit] = []
    for unit in units:
        if not merged:
            merged.append(unit)
            continue
        prev = merged[-1]
        same_slot = (
            prev.catalog_seq is not None
            and prev.catalog_seq == unit.catalog_seq
            and prev.doc_type == unit.doc_type
            and prev.end_page + 1 == unit.start_page
            and prev.source_path == unit.source_path
            and prev.doc_type not in (ds.DOC_TYPE_UNKNOWN, ds.DOC_TYPE_OTHER)
        )
        if same_slot:
            merged[-1] = DocumentUnit(
                doc_id=prev.doc_id,
                doc_type=prev.doc_type,
                start_page=prev.start_page,
                end_page=unit.end_page,
                title=prev.title or unit.title,
                catalog_seq=prev.catalog_seq,
                source_path=prev.source_path,
                score=prev.score,
            )
        else:
            merged.append(unit)

    if len(merged) < len(units):
        log(f"       [INFO] 合并同目录相邻页段: {len(units)} → {len(merged)} 份")
    return merged


def _sort_units_by_catalog_seq(units: List[DocumentUnit], log=print) -> List[DocumentUnit]:
    """按catalog_seq排序，确保符合标准目录逻辑顺序

    【优化】增加更详细的排序逻辑，避免页码范围异常
    """
    if len(units) <= 1:
        return units

    # 记录原始排序信息
    original_order = [(u.catalog_seq, u.start_page, u.end_page, u.doc_type) for u in units]

    # 【第15轮修复】去重逻辑：合并相同catalog_seq的多个DocumentUnit
    deduplicated_units = _deduplicate_units_by_catalog_seq(units, log=log)

    # 按catalog_seq排序（primary key），同seq内按原始页码排序（secondary key）
    sorted_units = sorted(deduplicated_units, key=lambda u: (
        u.catalog_seq if u.catalog_seq is not None else 999,  # catalog_seq优先
        u.start_page  # 原始页码作为tie-breaker
    ))

    # 检查排序变化并记录详细信息
    if sorted_units != units:
        # 检查页码范围是否异常
        for i, unit in enumerate(sorted_units):
            if unit.end_page < unit.start_page:
                log(f"       [警告] seq{unit.catalog_seq} 页码范围异常: {unit.start_page}-{unit.end_page}")
            if i > 0 and sorted_units[i-1].end_page >= unit.start_page:
                log(f"       [警告] 页码重叠: seq{sorted_units[i-1].catalog_seq}({sorted_units[i-1].start_page}-{sorted_units[i-1].end_page}) vs seq{unit.catalog_seq}({unit.start_page}-{unit.end_page})")

        log(f"       [修复] 按catalog_seq重新排序，确保符合标准目录顺序")
        # 显示排序变化的详细信息
        for i, (orig, sorted_u) in enumerate(zip(original_order, sorted_units)):
            if orig != (sorted_u.catalog_seq, sorted_u.start_page, sorted_u.end_page, sorted_u.doc_type):
                log(f"         [{i}] seq{orig[0]} → seq{sorted_u.catalog_seq}, 页{orig[1]}-{orig[2]} → 页{sorted_u.start_page}-{sorted_u.end_page}")

    return sorted_units


def _deduplicate_units_by_catalog_seq(units: List[DocumentUnit], log=print) -> List[DocumentUnit]:
    """去重逻辑：合并相同catalog_seq且相同源的多个DocumentUnit

    对于同一个catalog_seq的多个匹配：
    1. 先按source分组，不同源不合并（避免丢失文书）
    2. 同源内合并：选择置信度最高的，合并页码范围
    3. 保留doc_type和title信息
    """
    if len(units) <= 1:
        return units

    # 按catalog_seq分组
    from collections import defaultdict
    seq_groups = defaultdict(list)
    for unit in units:
        if unit.catalog_seq is not None:
            seq_groups[unit.catalog_seq].append(unit)
        else:
            # 无catalog_seq的unit保持原样
            seq_groups[None].append(unit)

    deduplicated = []
    for seq, group in seq_groups.items():
        if seq is None:
            # 无catalog_seq的unit直接添加
            deduplicated.extend(group)
        elif len(group) == 1:
            # 只有一个匹配，直接添加
            deduplicated.append(group[0])
        else:
            # 多个匹配，先按source分组再合并
            source_groups = defaultdict(list)
            for unit in group:
                src = unit.source_path or ""
                source_groups[src].append(unit)

            # 对每个source组分别合并
            for src, src_group in source_groups.items():
                if len(src_group) == 1:
                    deduplicated.append(src_group[0])
                    continue

                # 仅合并「连续/重叠」的页段，保留不连续的孤岛分段。
                # 关键修复：同一 catalog_seq 的多个分段若被其他文书隔开
                # （如 contract 出现在 0-4 与 61-67，中间夹着 poa/complaint），
                # 直接按 min/max 合并会吞并中间页 → 物理重复插入。
                ordered = sorted(src_group, key=lambda u: (u.start_page, u.end_page))
                islands: List[List[DocumentUnit]] = [[ordered[0]]]
                for u in ordered[1:]:
                    last = islands[-1]
                    last_end = max(x.end_page for x in last)
                    if u.start_page <= last_end + 1:
                        last.append(u)
                    else:
                        islands.append([u])

                for island in islands:
                    if len(island) == 1:
                        deduplicated.append(island[0])
                        continue
                    best_unit = max(island, key=lambda u: u.confidence or 0)
                    min_page = min(u.start_page for u in island)
                    max_page = max(u.end_page for u in island)
                    merged_unit = DocumentUnit(
                        doc_id=best_unit.doc_id,
                        doc_type=best_unit.doc_type,
                        start_page=min_page,
                        end_page=max_page,
                        title=best_unit.title,
                        catalog_seq=seq,
                        source_path=best_unit.source_path,
                        score=best_unit.score,
                        confidence=best_unit.confidence,
                    )
                    deduplicated.append(merged_unit)
                    log(f"       [去重] seq{seq}: {len(island)}个连续匹配 → 1个（页{min_page}-{max_page}）")
                if len(islands) > 1:
                    log(f"       [去重] seq{seq}: 保留 {len(islands)} 个不连续分段，避免吞并中间文书")

    return deduplicated


def _is_title_similar(title1: str, title2: str, page_texts: List[str], unit1: DocumentUnit, unit2: DocumentUnit) -> bool:
    """判断两个标题是否相似（无新文书强信号）"""
    # 简单判断：如果标题都为空或高度相似，则认为相似
    if not title1 or not title2:
        return True

    # 检查是否有明显的不同关键词（强信号）
    strong_signals = [
        ("恢复执行", "执行裁定书"),
        ("终结执行", "执行裁定书"),
        ("驳回起诉", "裁定书"),
        ("管辖异议", "裁定书"),
    ]

    for signal1, signal2 in strong_signals:
        if signal1 in title1 and signal2 in title2:
            return False  # 有强信号，不合并
        if signal2 in title1 and signal1 in title2:
            return False

    # 默认：标题相似则可合并
    return title1 == title2 or len(set(title1) & set(title2)) >= min(len(title1), len(title2)) // 2


def segment_documents(
    page_texts: List[str],
    pdf_text: Optional[str] = None,
    layout_blocks: Optional[List[dict]] = None,
    log=print,
) -> List[DocumentUnit]:
    """[已弃用] 纯锚点文书切分：首页锚点定边界，无锚点页并入当前文书。

    .. deprecated::
        生产链路（WF2）已统一走 :func:`segment_by_catalog`（页级分类 + layout +
        目录槽位）。本函数仅作为无目录上下文时的锚点切分 fallback 保留，未在主
        流程调用。新代码请勿直接使用。
    """
    if not page_texts:
        return []
    warnings.warn(
        "segment_documents 已弃用，请使用 segment_by_catalog（WF2 主链路）",
        DeprecationWarning,
        stacklevel=2,
    )

    starts = _find_page_anchor_starts(page_texts)
    if layout_blocks:
        starts = _enrich_starts_from_layout(starts, layout_blocks, log=log)
    if pdf_text:
        starts = _enrich_starts_from_fulltext(starts, page_texts, pdf_text, log=log)

    units = _build_units_from_starts(starts, len(page_texts))
    covered = sum(u.end_page - u.start_page + 1 for u in units)
    if covered != len(page_texts):
        log(f"       [WARN] 文书切分覆盖 {covered}/{len(page_texts)} 页")

    # 合并相邻同类型 unit（T-604）
    original_count = len(units)
    units = _merge_adjacent_same_type(units, page_texts, log=log)
    if len(units) < original_count:
        log(f"       [INFO] 合并相邻同类型文书: {original_count} → {len(units)} 份")

    return units


def _catalog_seq_for_doc_type(case_type: str, doc_type: str) -> Optional[int]:
    """文书类型 → 归档目录序号（仅 pdf/manual 可识别项）

    【优化】增强execution类型的catalog_seq映射，确保能正确分配到目录项
    """
    if doc_type in (ds.DOC_TYPE_OTHER, ds.DOC_TYPE_UNKNOWN):
        return None

    # 优先使用catalog_item_for_doc_type函数
    item = ac.catalog_item_for_doc_type(case_type, doc_type)
    if item:
        return item.seq

    # 对于execution类型，如果上面的映射失败，使用强制映射
    if doc_type == ds.DOC_TYPE_EXECUTION:
        catalog = ac.get_catalog(case_type)
        # 查找包含execution的目录项
        for cat_item in catalog:
            if doc_type in cat_item.doc_types:
                return cat_item.seq

    # 回退到manual_key映射
    for manual_key, mdt in ac.MANUAL_KEY_DOC_TYPES.items():
        if mdt == doc_type:
            mk = ac.catalog_item_for_manual_key(case_type, manual_key)
            if mk:
                return mk.seq
    return None


def segment_by_catalog(
    page_texts: List[str],
    case_type: str,
    log=print,
    *,
    layout_blocks: Optional[List[dict]] = None,
    pdf_path: Optional[str] = None,
    config: Optional[dict] = None,
) -> List[DocumentUnit]:
    """按归档目录槽位切分（J-1 layout + J-2 低置信复核）

    - layout 标题 / 页面上部锚点 → 切换 catalog_seq
    - 无信号页 → 继承前一页（材料不断裂）
    - 连续同 seq 合并为一段
    """
    if not page_texts:
        return []

    from page_classifier import (
        LOW_CONFIDENCE_THRESHOLD,
        classify_page_with_layout,
        refine_low_confidence_pages,
    )

    if config is None:
        try:
            from settings import load_config
            config = load_config()
        except ImportError:
            config = {}

    debug_matcher = get_debug_matcher(config) if DEBUG_AVAILABLE else None
    catalog = ac.get_catalog(case_type)
    evidence_seq = _evidence_seq(catalog)
    if evidence_seq is None:
        evidence_seq = 7
    # 审判槽 seq（阶段锁定用）：裁判正文引用「证据」时不得夺页（§3 规则）
    trial_seq = _trial_seq(catalog)
    # 起诉状/合同槽 seq（阶段锁定兜底用）：裁判正文引用「起诉状/代理合同」时不得夺页
    complaint_seq = _catalog_seq_for_doc_type(case_type, ds.DOC_TYPE_COMPLAINT)
    contract_seq = _catalog_seq_for_doc_type(case_type, ds.DOC_TYPE_CONTRACT)

    heading_pages = set()
    if layout_blocks:
        from page_classifier import layout_headings_by_page
        heading_pages = set(layout_headings_by_page(layout_blocks).keys())

    page_seqs: List[int] = []
    page_confidences: List[float] = []
    # 每页是否为「新文书起点」（含同槽内的第二份及以后），用于同槽多文书二次切分
    page_doc_starts: List[bool] = []
    prev_seq = evidence_seq
    # context_seq：最近一次「分段型」文书的槽位（证据/合同/判决…），作为正文背景。
    # prev_short：上一页是否为短文书（授权书/发票/传票），用于其后回落到上下文。
    context_seq = evidence_seq
    prev_short = False

    # 分段型文书：layout 不完整时可凭页顶锚点切换，并更新背景 context_seq
    _SECTION_TYPES = (
        ds.DOC_TYPE_CONTRACT, ds.DOC_TYPE_COMPLAINT, ds.DOC_TYPE_EVIDENCE,
        ds.DOC_TYPE_JUDGMENT, ds.DOC_TYPE_RULING, ds.DOC_TYPE_EXECUTION,
        ds.DOC_TYPE_MEDIATION, ds.DOC_TYPE_PRESERVATION,
        ds.DOC_TYPE_INDICTMENT, ds.DOC_TYPE_APPEAL,
    )
    # 短文书：通常 1 页，其后无锚点页应回落到背景，不得吞并后续整段
    _SHORT_TYPES = (ds.DOC_TYPE_POA, ds.DOC_TYPE_INVOICE, ds.DOC_TYPE_SUMMONS)

    def _page_sig(t: str) -> str:
        return (t or "").strip()[:280]

    for page_idx, text in enumerate(page_texts):
        stripped = (text or "").strip()
        if len(stripped) < 8:
            seq = context_seq if prev_short else prev_seq
            prev_short = False
            page_seqs.append(seq)
            page_confidences.append(0.5)  # 短文本不是低质量，提高到0.5
            page_doc_starts.append(False)
            prev_seq = seq
            continue

        # 相邻页 OCR 文本完全相同 → 继承
        if page_idx > 0 and _page_sig(text) == _page_sig(page_texts[page_idx - 1]):
            seq = context_seq if prev_short else prev_seq
            prev_short = False
            page_seqs.append(seq)
            page_confidences.append(0.6)  # 相同页是正常的，提高到0.6
            page_doc_starts.append(False)
            prev_seq = seq
            continue

        result = classify_page_with_layout(
            page_idx, text, case_type, layout_blocks=layout_blocks
        )

        # 调试输出：记录页面分类结果
        if debug_matcher is not None:
            debug_matcher.log_page_classification(page_idx, text, {
                "method": result.method,
                "confidence": result.confidence,
                "catalog_seq": result.catalog_seq,
                "doc_type": result.doc_type,
                "anchor": bool(getattr(result, "anchor", False))
            })

        # 槽位切换：layout 标题 / 高置信页顶锚点 / 首页
        can_switch = (
            page_idx == 0
            or result.method in ("layout", "layout+anchor")
            or (result.method == "anchor" and result.confidence >= 0.76)
        )

        if page_idx > 0 and layout_blocks and page_idx not in heading_pages and result.method == "anchor":
            # 例外：页顶锚点指向「与当前段不同的分段型文书」时，即使该页未被 MinerU
            # 标为 title 也允许切换——否则证据清单(表格)、合同等无法脱离 complaint 巨块。
            distinct_section = (
                result.catalog_seq is not None
                and result.catalog_seq != prev_seq
                and result.doc_type in _SECTION_TYPES
            )
            if result.confidence < 0.82 and not distinct_section:
                can_switch = False

        switching = can_switch and result.method not in ("inherit", "weak_anchor")
        # 阶段锁定（§3）：当前处于裁判段(trial)时，禁止证据/起诉状/合同等弱锚点夺走裁判正文页。
        # 判决书正文常引用「证据」「送达起诉状副本」「《委托代理合同》」等，会命中对应锚点误切。
        # 仅当信号来自 layout 标题（MinerU title 块）时才允许脱离 trial。
        _trial_steal = (
            result.catalog_seq is not None
            and result.catalog_seq != trial_seq
            and result.method != "layout"
            and result.catalog_seq in (evidence_seq, complaint_seq, contract_seq)
            and not (result.catalog_seq == evidence_seq and _match_evidence_heading(text))
        )
        if (
            switching
            and trial_seq is not None
            and context_seq == trial_seq
            and _trial_steal
        ):
            switching = False
        if switching:
            seq = result.catalog_seq
            conf = result.confidence
            # 分段型 → 更新背景；短文书 → 仅占本页，标记 prev_short 供下页回落
            if result.doc_type in _SECTION_TYPES:
                context_seq = seq
            prev_short = result.doc_type in _SHORT_TYPES
        else:
            # 继承：若上一页是短文书，回落到背景 context（避免授权书等吞并后续整段）
            seq = context_seq if prev_short else prev_seq
            prev_short = False
            # 修复置信度算法：继承模式给更高置信度，去除硬编码上限
            if result.method == "inherit":
                conf = 0.7  # 继承不是坏事，提高到0.7
            else:
                conf = min(result.confidence, 0.9)  # 去除0.55上限，改为0.9

        # 标记新文书起点：高置信、明确文书类型的页（即便归入同一 catalog_seq）
        is_doc_start = (
            page_idx > 0
            and switching
            and result.doc_type not in (ds.DOC_TYPE_OTHER, ds.DOC_TYPE_UNKNOWN)
        )

        page_seqs.append(seq)
        page_confidences.append(conf)
        page_doc_starts.append(is_doc_start)
        prev_seq = seq

    llm_refine = (config.get("extraction") or {}).get("catalog_llm_refine", False)
    if pdf_path and config and llm_refine:
        page_seqs, page_confidences, _low_pages = refine_low_confidence_pages(
            page_seqs,
            page_confidences,
            page_texts,
            case_type,
            pdf_path,
            config,
            log=log,
        )
        prev_seq = evidence_seq
        for i, seq in enumerate(page_seqs):
            prev_seq = seq

    page_seqs = _dedupe_commission_contract_pages(
        page_seqs, page_texts, case_type, evidence_seq, log=log
    )

    from page_classifier import TITLE_ZONE_CHARS

    units: List[DocumentUnit] = []
    doc_id = 0
    i = 0
    n = len(page_seqs)
    while i < n:
        seq = page_seqs[i]
        start = i
        seg_conf = page_confidences[i]
        # 同槽内遇到新文书起点则断开，使两份同类文书（如两份判决/裁定）各成一段
        while (
            i + 1 < n
            and page_seqs[i + 1] == seq
            and not page_doc_starts[i + 1]
        ):
            i += 1
            # 修复：用平均置信度替代最小值，避免单页低置信度影响整体
            seg_conf = (seg_conf + page_confidences[i]) / 2
        end = i
        # 文书类型仅取标题区，避免正文中嵌套关键词污染（与 page_classifier 一致）
        dt, title = _classify_page_prefix(page_texts[start] or "", max_chars=TITLE_ZONE_CHARS)

        # 优化：对于页数较多且类型明确的文书，给予置信度加成
        page_count = end - start + 1
        if page_count > 10 and dt not in (ds.DOC_TYPE_OTHER, ds.DOC_TYPE_UNKNOWN):
            # 大段文书且类型明确，说明识别可靠，提高置信度
            seg_conf = max(seg_conf, 0.85)  # 至少0.85的置信度
        elif page_count >= 3 and dt not in (ds.DOC_TYPE_OTHER, ds.DOC_TYPE_UNKNOWN):
            # 中等长度文书(3-10页)且类型明确，也给予适度加成
            seg_conf = max(seg_conf, 0.80)  # 至少0.80的置信度
        elif page_count >= 1 and dt not in (ds.DOC_TYPE_OTHER, ds.DOC_TYPE_UNKNOWN):
            # 短文书(1-2页)但类型明确，给予轻微加成
            seg_conf = max(seg_conf, 0.78)  # 至少0.78的置信度

        # 业务规则：无法辨别具体类型的文书一律归入「证据材料」槽
        # （「证据材料清单」本身为 evidence 锚点，已在页级分类切到 evidence_seq，
        #   是证据材料段的起始页；其后无法辨别的页继承/归入同槽）。
        contract_seq_slot = _catalog_seq_for_doc_type(case_type, ds.DOC_TYPE_CONTRACT)
        if dt in (ds.DOC_TYPE_OTHER, ds.DOC_TYPE_UNKNOWN):
            if contract_seq_slot is not None and seq == contract_seq_slot:
                dt = ds.DOC_TYPE_CONTRACT
            else:
                dt = ds.DOC_TYPE_EVIDENCE
                seq = evidence_seq
        item = next((x for x in catalog if x.seq == seq), None)
        units.append(
            DocumentUnit(
                doc_id=doc_id,
                doc_type=dt,
                start_page=start,
                end_page=end,
                title=title or (item.name if item else ""),
                catalog_seq=seq,
                confidence=seg_conf,
            )
        )
        doc_id += 1
        i += 1

    covered = sum(u.end_page - u.start_page + 1 for u in units)

    # 调试输出：保存调试日志
    if debug_matcher is not None:
        debug_matcher.save_debug_log()
    log(f"       目录槽切分: {len(units)} 段，覆盖 {covered}/{n} 页")
    for u in units:
        item = next((x for x in catalog if x.seq == u.catalog_seq), None)
        label = item.name if item else f"seq{u.catalog_seq}"
        pages = u.end_page - u.start_page + 1
        conf_tag = " [低置信]" if u.confidence < LOW_CONFIDENCE_THRESHOLD else ""
        try:
            log(
                f"       seq{u.catalog_seq} {label}: 页{u.start_page}-{u.end_page} "
                f"({pages}页) conf={u.confidence:.2f}{conf_tag}"
            )
        except (UnicodeEncodeError, OSError):
            pass

    # 关键修复：按catalog_seq排序，确保符合标准目录顺序
    units = _sort_units_by_catalog_seq(units, log=log)

    return units


# 律所委托/法律服务合同页首标题（§3.1 去重判定用）
_COMMISSION_CONTRACT_NO_RE = re.compile(r"合同编号[：:]\s*(\d+)")


def _is_commission_contract_title_page(text: str) -> bool:
    """页首是否为律所委托/法律服务合同标题（非判决书正文《》引用）。"""
    head = (text or "").lstrip()[:120]
    if not head:
        return False
    for kw in (
        "民事委托代理合同",
        "委托律师代理合同",
        "委托代理合同",
        "法律服务合同",
        "法律顾问合同",
    ):
        pos = head.find(kw)
        if pos < 0 or pos > 25:
            continue
        before = head[:pos]
        if "《" in before or before.strip().startswith("关于"):
            continue
        return True
    return False


def _commission_contract_number(text: str) -> Optional[str]:
    m = _COMMISSION_CONTRACT_NO_RE.search(text or "")
    return m.group(1) if m else None


def _is_contract_citation_not_title(text: str) -> bool:
    """合同名出现在引用语境（《》/关于…），非独立合同页首。"""
    if _is_commission_contract_title_page(text):
        return False
    head = (text or "")[:250]
    return "委托代理合同" in head and ("《" in head or head.lstrip().startswith("关于"))


def _strong_section_doc_type(text: str) -> Optional[str]:
    from page_classifier import TITLE_ZONE_CHARS

    dt, _ = _classify_page_prefix(text or "", max_chars=TITLE_ZONE_CHARS)
    if dt in (
        ds.DOC_TYPE_POA,
        ds.DOC_TYPE_EVIDENCE,
        ds.DOC_TYPE_JUDGMENT,
        ds.DOC_TYPE_RULING,
        ds.DOC_TYPE_EXECUTION,
        ds.DOC_TYPE_PRESERVATION,
        ds.DOC_TYPE_COMPLAINT,
        ds.DOC_TYPE_MEDIATION,
    ):
        return dt
    return None


def _should_break_contract_run(text: str) -> bool:
    """合同连续段遇到新文书强锚点时截断（排除合同条款内「授权」等弱信号）。"""
    from page_classifier import TITLE_ZONE_CHARS

    head = (text or "").lstrip()[:150]
    if any(
        k in head
        for k in (
            "受理案件通知书",
            "应诉通知书",
            "举证通知书",
            "开庭通知书",
            "出庭通知书",
            "证据清单",
            "传票",
        )
    ):
        return True

    dt, _ = _classify_page_prefix(text or "", max_chars=TITLE_ZONE_CHARS)
    if dt in (
        ds.DOC_TYPE_EVIDENCE,
        ds.DOC_TYPE_JUDGMENT,
        ds.DOC_TYPE_RULING,
        ds.DOC_TYPE_EXECUTION,
        ds.DOC_TYPE_PRESERVATION,
        ds.DOC_TYPE_COMPLAINT,
        ds.DOC_TYPE_MEDIATION,
    ):
        return True
    if dt == ds.DOC_TYPE_POA:
        head = (text or "").lstrip()[:100]
        if any(k in head for k in ("受理", "应诉", "举证", "通知书", "法院")):
            return True
    if dt == ds.DOC_TYPE_SUMMONS:
        return True
    return False



def _dedupe_commission_contract_pages(
    page_seqs: List[int],
    page_texts: List[str],
    case_type: str,
    evidence_seq: int,
    log=print,
) -> List[int]:
    """§3.1 委托代理合同去重：连续多页完整合同=seq3；证据段单页副本/片段→证据(7)。"""
    contract_seq = _catalog_seq_for_doc_type(case_type, ds.DOC_TYPE_CONTRACT)
    if contract_seq is None:
        return page_seqs

    complaint_seq = _catalog_seq_for_doc_type(case_type, ds.DOC_TYPE_COMPLAINT)
    n = len(page_seqs)
    result = list(page_seqs)

    trial_types = (
        ds.DOC_TYPE_JUDGMENT,
        ds.DOC_TYPE_RULING,
        ds.DOC_TYPE_MEDIATION,
        ds.DOC_TYPE_PRESERVATION,
        ds.DOC_TYPE_EXECUTION,
    )
    trial_seqs: set = set()
    for dt in trial_types:
        sq = _catalog_seq_for_doc_type(case_type, dt)
        if sq is not None:
            trial_seqs.add(sq)

    complaint_start = next(
        (i for i in range(n) if complaint_seq is not None and page_seqs[i] == complaint_seq),
        n,
    )
    trial_start = next(
        (i for i in range(n) if page_seqs[i] in trial_seqs and i >= complaint_start),
        n,
    )

    # 裁判/执行正文中部引用合同名 → 还原为对应审判槽位
    for p in range(n):
        if result[p] != contract_seq:
            continue
        if _is_commission_contract_title_page(page_texts[p]):
            continue
        if _is_contract_citation_not_title(page_texts[p]):
            for dt in (ds.DOC_TYPE_JUDGMENT, ds.DOC_TYPE_RULING, ds.DOC_TYPE_EXECUTION):
                if _validate_document_type(page_texts[p], dt):
                    sq = _catalog_seq_for_doc_type(case_type, dt)
                    if sq is not None:
                        result[p] = sq
                        break
            continue
        sec = _strong_section_doc_type(page_texts[p])
        if sec and sec != ds.DOC_TYPE_CONTRACT:
            sq = _catalog_seq_for_doc_type(case_type, sec)
            if sq is not None:
                result[p] = sq

    # 处理仍为 contract 的连续段
    i = 0
    while i < n:
        if result[i] != contract_seq:
            i += 1
            continue
        start = i
        while i + 1 < n and result[i + 1] == contract_seq:
            i += 1
        run_end = i

        # 在强锚点（授权书/证据清单/裁判…）处截断合同段
        end = start
        for p in range(start, run_end + 1):
            if _should_break_contract_run(page_texts[p]) and p > start:
                break
            end = p

        for p in range(end + 1, run_end + 1):
            result[p] = evidence_seq

        run_len = end - start + 1
        has_title = _is_commission_contract_title_page(page_texts[start])

        keep = False
        # §3.1 卷首(证据外)委托代理合同=seq3；证据段内的合同一律归证据(seq7)——
        # 合同副本作为证据提交证明律师费支出，证据外另有合同(重复)时只保留证据外。
        if has_title and start < complaint_start:
            keep = True

        if not keep:
            for p in range(start, end + 1):
                result[p] = evidence_seq
            if has_title and start >= complaint_start:
                log(f"       [合同去重] 页{start} 单页副本→证据")
            elif run_len > 1:
                log(f"       [合同去重] 页{start}-{end} 片段/继承误并→证据")
        i += 1

    # 执行段后的合同条款附录（如 2019 p98）→ seq3（仅卷末、非诉状/裁判页）
    exec_seq = _catalog_seq_for_doc_type(case_type, ds.DOC_TYPE_EXECUTION)
    if exec_seq is not None:
        exec_pages = [p for p in range(n) if result[p] == exec_seq]
        if not exec_pages:
            exec_pages = [p for p in range(n) if page_seqs[p] == exec_seq]
        if exec_pages:
            last_exec = max(exec_pages)
            for p in range(last_exec + 1, n):
                if n - p > 3:
                    continue
                text = page_texts[p] or ""
                if _should_break_contract_run(text):
                    continue
                dt, _ = _classify_page_prefix(text)
                if dt in (
                    ds.DOC_TYPE_COMPLAINT,
                    ds.DOC_TYPE_JUDGMENT,
                    ds.DOC_TYPE_RULING,
                    ds.DOC_TYPE_EXECUTION,
                    ds.DOC_TYPE_PRESERVATION,
                ):
                    continue
                if re.search(r"原告|被告|违约|起诉|案由|信用卡", text):
                    continue
                if re.search(r"律师费|计费|收费标准", text):
                    result[p] = contract_seq

    # 卷末合同条款附录页（正文已标 contract 但无独立标题，如 2019 p98）→ seq3
    for p in range(n):
        if n - p > 3:
            continue
        dt, _ = _classify_page_prefix(page_texts[p] or "")
        if dt == ds.DOC_TYPE_CONTRACT and not _is_commission_contract_title_page(
            page_texts[p] or ""
        ):
            result[p] = contract_seq

    return result


def _evidence_seq(catalog: List[ac.CatalogItem]) -> Optional[int]:
    for item in catalog:
        if item.manual_key == "evidence":
            return item.seq
    return None


def _trial_seq(catalog: List[ac.CatalogItem]) -> Optional[int]:
    """审判文书槽（判决/裁定/调解）的 seq；用于阶段锁定（§3：裁判正文页不得被证据锚点夺走）。"""
    for item in catalog:
        if ds.DOC_TYPE_JUDGMENT in item.doc_types:
            return item.seq
    return None


def _match_catalog_items(unit: DocumentUnit, catalog: List[ac.CatalogItem]) -> List[ac.CatalogItem]:
    matches = []
    for item in catalog:
        # 优先级1: doc_types 直接匹配
        if unit.doc_type in item.doc_types:
            matches.append(item)
            continue

        # 优先级2: manual_key 精确匹配（invoice→seq2, evidence→seq7）
        if item.source == "manual" and item.manual_key:
            mdt = ac.MANUAL_KEY_DOC_TYPES.get(item.manual_key)
            if mdt and unit.doc_type == mdt:
                matches.append(item)
                continue

        # 优先级3: 文书标题模糊匹配（收紧防误拉 seq）：
        #   - 标题与目录名均需 ≥4 字符（过短目录名禁用模糊匹配，如「发票」）
        #   - 要求 ≥4 字符连续公共子串
        #   - 公共子串须落在标题前 30 字（避免正文尾部偶现词误匹配）
        title = (unit.title or "")[:30].lower()
        name = (item.name or "").lower()
        if len(title) >= 4 and len(name) >= 4:
            if _longest_common_substring_len(title, name) >= 4:
                matches.append(item)

    return matches


def _longest_common_substring_len(a: str, b: str) -> int:
    """最长公共连续子串长度（用于标题↔目录名的稳健模糊匹配）"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def _pick_best_catalog_item(matches: List[ac.CatalogItem], unit: DocumentUnit = None) -> ac.CatalogItem:
    """改进的目录项选择算法 - 多匹配时优先级：单一doc_type精确 > len(doc_types)最少 > source=pdf > manual"""
    def sort_key(item: ac.CatalogItem):
        source_pri = 2 if item.source == "pdf" else (1 if item.source == "mixed" else 0)
        return (source_pri, item.seq)

    # 如果只有一个匹配项，直接返回
    if len(matches) == 1:
        return matches[0]

    # 如果有多个匹配项且提供了unit信息，进行更精确的匹配
    if unit and unit.doc_type:
        # 优先级1: 单一 doc_type 精确匹配（最精确）
        single_doc_type_matches = [item for item in matches if len(item.doc_types) == 1 and unit.doc_type in item.doc_types]
        if single_doc_type_matches:
            return single_doc_type_matches[0]

        # 优先级2: doc_types 最少的匹配（最精确）
        exact_matches = [item for item in matches if unit.doc_type in item.doc_types]
        if exact_matches:
            return min(exact_matches, key=lambda x: len(x.doc_types))

        # 优先级3: source=pdf 优先于 mixed，mixed 优先于 manual
        pdf_matches = [item for item in matches if item.source == "pdf"]
        if pdf_matches:
            return min(pdf_matches, key=lambda x: len(x.doc_types))

        mixed_matches = [item for item in matches if item.source == "mixed"]
        if mixed_matches:
            return min(mixed_matches, key=lambda x: len(x.doc_types))

    # 默认：按source优先级和seq排序
    return max(matches, key=sort_key)


def assign_catalog_seq(
    units: List[DocumentUnit],
    catalog: List[ac.CatalogItem],
    log=print,
) -> List[DocumentUnit]:
    """为每份文书分配目录序号；未匹配整份归入证据材料槽"""
    evidence = _evidence_seq(catalog)
    matched_count = 0
    unmatched_count = 0

    # 先按 (源文件, 页码) 排序：同源文书连续且按页序，跨源不交错
    # 保证多 PDF（路径 B）顺序稳定，并让相邻同槽合并只在同源内生效
    units.sort(key=lambda u: (getattr(u, "source_path", "") or "", u.start_page))

    for unit in units:
        if unit.doc_type in (ds.DOC_TYPE_UNKNOWN, ds.DOC_TYPE_OTHER):
            unit.catalog_seq = evidence
            log(
                f"       未识别类型: {ds.DOC_TYPE_LABELS.get(unit.doc_type, '未知类型')} "
                f"(页{unit.start_page}-{unit.end_page}) → seq{evidence}"
            )
            unmatched_count += 1
            continue

        matches = _match_catalog_items(unit, catalog)
        if not matches:
            unit.catalog_seq = evidence
            log(
                f"       未匹配目录: {ds.DOC_TYPE_LABELS.get(unit.doc_type, '未知类型')} "
                f"(页{unit.start_page}-{unit.end_page}) → seq{evidence}"
            )
            unmatched_count += 1
            continue

        # 当有多个匹配时，显示详细信息
        if len(matches) > 1:
            log(
                f"       [调试] {ds.DOC_TYPE_LABELS.get(unit.doc_type, '未知类型')} "
                f"(页{unit.start_page}-{unit.end_page}) 匹配到 {len(matches)} 个目录项:"
            )
            for m in matches:
                log(f"              - seq{m.seq}: {m.name} (doc_types={len(m.doc_types)}项)")

        best = _pick_best_catalog_item(matches, unit)
        unit.catalog_seq = best.seq
        matched_count += 1
        log(
            f"       匹配成功: {ds.DOC_TYPE_LABELS.get(unit.doc_type, '未知类型')} "
            f"(页{unit.start_page}-{unit.end_page}) → seq{best.seq} ({best.name})"
        )

    log(f"       目录匹配完成: {matched_count} 份匹配, {unmatched_count} 份未匹配")
    units = _merge_adjacent_same_catalog_seq(units, log=log)
    # 修复catalog顺序问题：按catalog_seq排序，符合标准目录
    units = _sort_units_by_catalog_seq(units, log=log)
    return units


def locate_doc_spans(
    pdf_path: str,
    config: dict,
    *,
    case_type: Optional[str] = None,
    page_texts: Optional[List[str]] = None,
    pdf_text: Optional[str] = None,
    log=print,
) -> List[DocumentUnit]:
    """定位 PDF 中各文书单元（全页覆盖、无重叠）"""
    layout_blocks: Optional[List[dict]] = None
    if page_texts is None:
        page_texts, ingested_full, ingested_layout = _wf1_ingest(
            pdf_path, config, log=log
        )
        if pdf_text is None:
            pdf_text = ingested_full
        layout_blocks = ingested_layout

    if not page_texts:
        log("未获取到页面文字")
        return []

    if not case_type:
        case_type = "civil"

    layout_blocks = layout_blocks if layout_blocks is not None else []
    log(f"共 {len(page_texts)} 页，开始目录槽切分（layout={len(layout_blocks)} 块）")
    units = segment_by_catalog(
        page_texts,
        case_type,
        log=log,
        layout_blocks=layout_blocks,
        pdf_path=pdf_path,
        config=config,
    )
    for u in units:
        u.source_path = pdf_path

    log(f"切分完成: {len(units)} 段，合计 {len(page_texts)} 页")
    for u in units:
        n = u.end_page - u.start_page + 1
        seq_info = f" → seq{u.catalog_seq}" if u.catalog_seq is not None else ""
        log(
            f"       {ds.DOC_TYPE_LABELS.get(u.doc_type, '未知类型')}: "
            f"页{u.start_page}-{u.end_page} ({n}页){seq_info}"
        )
    return units


def find_doc_span_by_type(spans: List[DocumentUnit], doc_type: str) -> Optional[DocumentUnit]:
    for span in spans:
        if span.doc_type == doc_type:
            return span
    return None


def find_doc_spans_by_type(spans: List[DocumentUnit], doc_type: str) -> List[DocumentUnit]:
    return [s for s in spans if s.doc_type == doc_type]
