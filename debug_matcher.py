#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Per-operation structural diagnostics; never retain source text or filenames."""

import json
import math
from typing import List
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

_METHODS = frozenset({"layout", "anchor", "layout+anchor", "inherit", "llm", "vision", "none", "searched"})
_DOC_TYPES = frozenset({
    "judgment", "execution", "contract", "complaint", "other", "unknown", "default",
    "poa", "ruling", "mediation", "indictment", "appeal", "summons", "court_record",
    "invoice", "evidence", "plea", "agent_opinion", "review_record", "group_discussion",
    "preservation", "investigation", "client_talk", "arbitration", "consultation",
})

def _integer(value):
    return value if type(value) is int and value >= 0 else None

def _confidence(value):
    return float(value) if type(value) in (int, float) and 0 <= value <= 1 and math.isfinite(value) else None

def _code(value, allowed):
    return value if type(value) is str and value in allowed else "unknown"

@dataclass
class MatchDebugInfo:
    """文书匹配调试信息"""
    step: str
    timestamp: str
    doc_id: int = None
    doc_type: str = None
    catalog_seq: int = None
    start_page: int = None
    end_page: int = None
    confidence: float = None
    match_method: str = None
    anchor_found: bool = False

class DebugMatcher:
    """调试匹配器"""

    def __init__(self, output_file: str = None, *, enabled: bool = False):
        self.enabled = enabled is True
        self.debug_log: List[MatchDebugInfo] = []
        self.output_file = output_file or f"outputs/debug_match_{uuid4().hex}.json"

    def log_page_classification(self, page_idx: int, text: str, result: dict):
        """记录页面分类过程"""
        if not self.enabled:
            return
        self.debug_log.append(MatchDebugInfo(
            step="page_classification",
            timestamp=datetime.now().isoformat(),
            doc_id=_integer(page_idx),
            doc_type=_code(result.get("doc_type"), _DOC_TYPES),
            match_method=_code(result.get("method"), _METHODS),
            confidence=_confidence(result.get("confidence")),
            catalog_seq=_integer(result.get("catalog_seq")),
            anchor_found=bool(result.get("anchor")),
        ))

    def log_document_segment(self, doc_id: int, doc_type: str, start_page: int,
                             end_page: int, confidence: float, catalog_seq: int):
        """记录文书段切分结果"""
        if not self.enabled:
            return
        self.debug_log.append(MatchDebugInfo(
            step="document_segment",
            timestamp=datetime.now().isoformat(),
            doc_id=_integer(doc_id),
            doc_type=_code(doc_type, _DOC_TYPES),
            catalog_seq=_integer(catalog_seq),
            start_page=_integer(start_page), end_page=_integer(end_page),
            confidence=_confidence(confidence)
        ))

    def log_missing_analysis(self, catalog_seq: int, item_name: str,
                           searched_types: List[str], reasons: List[str]):
        """记录缺失项分析"""
        if not self.enabled:
            return
        self.debug_log.append(MatchDebugInfo(
            step="missing_analysis",
            timestamp=datetime.now().isoformat(),
            catalog_seq=_integer(catalog_seq),
            match_method="searched",
        ))

    def save_debug_log(self):
        """Disabled instances never create directories or files."""
        if not self.enabled or not self.debug_log:
            return False
        try:
            path = Path(self.output_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps([asdict(item) for item in self.debug_log],
                                      ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, ValueError, TypeError):
            print("匹配诊断保存失败 [DIAGNOSTIC_WRITE_FAILED]")
            return False
        finally:
            self.debug_log.clear()
        print("匹配诊断已保存")
        return True

    def print_summary(self):
        """打印调试摘要"""
        if self.enabled:
            print(f"匹配诊断记录数: {len(self.debug_log)}")

def get_debug_matcher(config: dict | None = None) -> DebugMatcher:
    """Fresh caller-owned instance: no process-global cross-task accumulation."""
    return DebugMatcher(enabled=enable_debug_mode(config))

def enable_debug_mode(config: dict | None = None):
    """启用调试模式"""
    if config is None:
        from settings import load_config
        config = load_config()
    return (config.get("debug") or {}).get("match_details") is True

def log_classification(page_idx: int, text: str, result: dict):
    """便捷函数：记录分类过程"""
    matcher = get_debug_matcher()
    matcher.log_page_classification(page_idx, text, result)
    return matcher

def log_segmentation(doc_id: int, doc_type: str, start_page: int, end_page: int,
                     confidence: float, catalog_seq: int):
    """便捷函数：记录切分结果"""
    matcher = get_debug_matcher()
    matcher.log_document_segment(doc_id, doc_type, start_page, end_page, confidence, catalog_seq)
    return matcher
