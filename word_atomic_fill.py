#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V1.3 原子替换：仅改写【】字符跨度，禁止整格 Range.Text 回退"""

import re
import sys

WD_REPLACE_ONE = 1
WD_FIND_STOP = 0
WD_LINE_SPACE_EXACTLY = 4

CELL_END = "\x07"
REFERENCE_FORMAT_TRAILING = re.compile(r"参考格式[：:\s].*$", re.DOTALL)

# 仅对填入值子 Range 阶梯缩字（pt）
FIT_SIZES = (14.0, 10.5, 9.0, 8.5)
FIT_LINE_SPACINGS = (20.0, 17.0, 15.0, 13.0)
FIT_CHAR_THRESHOLD = 20


def _plain(text: str) -> str:
    return (text or "").replace(CELL_END, "").replace("\r", "").replace("\n", "")


def clear_range_bold(rng):
    """取消 Range 内加粗（Run 级，避免继承模板 Bold）"""
    if rng is None:
        return
    try:
        rng.Font.Bold = 0
    except Exception:
        pass
    try:
        runs = rng.Runs
        for i in range(1, runs.Count + 1):
            runs(i).Font.Bold = 0
    except Exception:
        pass


def content_range(rng):
    """单元格/段落 Range 去掉末尾单元格标记"""
    if rng is None:
        return None
    try:
        doc = rng.Document
        text = rng.Text or ""
        end = rng.End
        if text.endswith(CELL_END) and end > rng.Start:
            end -= 1
        return doc.Range(rng.Start, end)
    except Exception:
        try:
            return rng.Duplicate
        except Exception:
            return rng


def _token_for_key(key: str) -> str:
    return key if key.startswith("=") else f"【{key}】"


def _should_skip_compact(key: str) -> bool:
    """结案小结/审办结果由 fill_cell_format 统一设四号楷体，不再阶梯缩字"""
    try:
        from fill_cell_format import is_outcome_placeholder

        return is_outcome_placeholder(key)
    except ImportError:
        return False


def find_substring_range(doc, container_rng, substring: str):
    """在容器内用字符偏移定位子 Range"""
    if not substring or doc is None or container_rng is None:
        return None
    try:
        base = content_range(container_rng)
        full = _plain(base.Text or "")
        idx = full.find(substring)
        if idx < 0:
            return None
        start = base.Start + idx
        end = start + len(substring)
        return doc.Range(start, end)
    except Exception:
        return None


def _find_via_word_find(doc, container_rng, substring: str):
    try:
        base = content_range(container_rng)
        search_rng = base.Duplicate
        find = search_rng.Find
        find.ClearFormatting()
        find.Text = substring
        find.Replacement.Text = ""
        found = find.Execute(
            Replace=0,
            Forward=True,
            Wrap=WD_FIND_STOP,
            Format=False,
        )
        if found and substring not in _plain(search_rng.Text or ""):
            return search_rng.Duplicate
        if found:
            return doc.Range(search_rng.Start, search_rng.End)
    except Exception:
        pass
    return None


def _valid_offset_hint(container_rng, token: str, offset_hint=None):
    """偏移仅当当前文本仍完全匹配 token 时有效"""
    if not offset_hint or not offset_hint.get("len"):
        return None
    try:
        base = content_range(container_rng)
        full = _plain(base.Text or "")
        start = int(offset_hint["start"])
        length = int(offset_hint["len"])
        if start >= 0 and start + length <= len(full):
            if full[start : start + length] == token:
                return offset_hint
    except Exception:
        pass
    return None


def locate_token_range(doc, container_rng, token: str, offset_hint=None):
    """定位占位符子 Range；offset_hint 为 manifest 预计算 {start, len}"""
    offset_hint = _valid_offset_hint(container_rng, token, offset_hint)
    if offset_hint:
        try:
            base = content_range(container_rng)
            full = _plain(base.Text or "")
            start = int(offset_hint["start"])
            length = int(offset_hint["len"])
            return doc.Range(base.Start + start, base.Start + start + length)
        except Exception:
            pass
    rng = find_substring_range(doc, container_rng, token)
    if rng is not None:
        return rng
    return _find_via_word_find(doc, container_rng, token)


def _fit_value_subrange(value_rng, char_count: int = 0):
    """仅对填入值缩小字号/行距"""
    if value_rng is None:
        return
    n = char_count or len(_plain(value_rng.Text or ""))
    if n < FIT_CHAR_THRESHOLD:
        return
    size_idx = 0
    if n >= 90:
        size_idx = 3
    elif n >= 55:
        size_idx = 2
    elif n >= 28:
        size_idx = 1
    try:
        pt = FIT_SIZES[size_idx]
        line = FIT_LINE_SPACINGS[min(size_idx, len(FIT_LINE_SPACINGS) - 1)]
        value_rng.Font.Size = pt
        value_rng.Font.Bold = 0
        for i in range(1, value_rng.Paragraphs.Count + 1):
            try:
                fmt = value_rng.Paragraphs(i).Format
                fmt.LineSpacingRule = WD_LINE_SPACE_EXACTLY
                fmt.LineSpacing = line
                fmt.SpaceBefore = 0
                fmt.SpaceAfter = 0
            except Exception:
                pass
    except Exception:
        pass


def replace_token_atomic(
    doc,
    container_rng,
    token: str,
    value: str,
    blacken_fn=None,
    offset_hint=None,
    fit_long_text: bool = True,
) -> bool:
    """
    将容器内的 token（如【key】）替换为 value，仅修改该字符跨度。
    失败返回 False，不整格回退。
    """
    if doc is None or container_rng is None or not token:
        return False

    ph_rng = locate_token_range(doc, container_rng, token, offset_hint=offset_hint)
    if ph_rng is None:
        return False

    val = "" if value is None else str(value)
    try:
        start = ph_rng.Start
        ph_rng.Text = val
        if not val:
            return True
        value_rng = doc.Range(start, start + len(val))
        if fit_long_text:
            _fit_value_subrange(value_rng, len(val.replace(" ", "")))
        clear_range_bold(value_rng)
        if blacken_fn:
            blacken_fn(value_rng)
        return True
    except Exception as e:
        print(f"  [WARN] 原子替换失败 {token[:20]}: {e}", file=sys.stderr)
        return False


def replace_placeholders_atomic(
    doc,
    container_rng,
    patch: dict,
    blacken_fn=None,
    placeholder_offsets: dict = None,
    fit_long_text: bool = True,
) -> int:
    """
    在容器内批量原子替换。placeholder_offsets: {key: {start, len}} 可选。
    返回成功替换次数。
    """
    if not patch or container_rng is None or doc is None:
        return 0

    placeholder_offsets = placeholder_offsets or {}
    total = 0

    def _start_hint(key):
        token = _token_for_key(key)
        hint = _valid_offset_hint(
            container_rng, token, placeholder_offsets.get(key)
        )
        return int(hint["start"]) if hint else 10_000

    # 同格多占位符：先填非空（从前向后），再清空说明类（从后向前，且不用过期偏移）
    fills = []
    clears = []
    for key, value in patch.items():
        if value is None:
            continue
        if str(value).strip():
            fills.append((key, value))
        else:
            clears.append((key, value))

    fills.sort(key=lambda kv: (_start_hint(kv[0]), -len(str(kv[0]))))
    clears.sort(key=lambda kv: (-_start_hint(kv[0]), -len(str(kv[0]))))

    for key, value in fills:
        token = _token_for_key(key)
        base = content_range(container_rng)
        if token not in _plain(base.Text or ""):
            continue
        hint = _valid_offset_hint(
            container_rng, token, placeholder_offsets.get(key)
        )
        use_fit = fit_long_text and not _should_skip_compact(key)
        if replace_token_atomic(
            doc,
            container_rng,
            token,
            value,
            blacken_fn=blacken_fn,
            offset_hint=hint,
            fit_long_text=use_fit,
        ):
            total += 1

    for key, value in clears:
        token = _token_for_key(key)
        base = content_range(container_rng)
        if token not in _plain(base.Text or ""):
            continue
        # 清空类必须重新搜索，避免先清空尾部时破坏前一占位符末尾（如 元】→元内】）
        if replace_token_atomic(
            doc,
            container_rng,
            token,
            value,
            blacken_fn=blacken_fn,
            offset_hint=None,
            fit_long_text=False,
        ):
            total += 1

    return total


def delete_substring_atomic(doc, container_rng, substring: str) -> bool:
    """删除容器内指定子串（用于说明文字、参考格式）"""
    if not substring:
        return False
    ph = locate_token_range(doc, container_rng, substring)
    if ph is None:
        return False
    try:
        ph.Text = ""
        return True
    except Exception:
        return False


def strip_reference_format_atomic(doc, container_rng) -> bool:
    """仅删除「参考格式…」后缀子串"""
    base = content_range(container_rng)
    text = _plain(base.Text or "")
    m = REFERENCE_FORMAT_TRAILING.search(text)
    if not m:
        return False
    try:
        start = base.Start + m.start()
        doc.Range(start, base.End).Text = ""
        return True
    except Exception:
        return False


def replace_plain_atomic(doc, container_rng, token: str, value: str, blacken_fn=None) -> int:
    return 1 if replace_token_atomic(doc, container_rng, token, value, blacken_fn=blacken_fn) else 0
