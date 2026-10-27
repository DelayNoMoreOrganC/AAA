# 归档正文排序与文书识别准确度（已实现）

> 本文取代根目录早期规划稿 `PDF_ORDER_OPTIMIZATION_PLAN.md` / `PDF_ORDER_COMPARISON.md`。
> 相关能力已在 Phase J（准确度）与 Phase K（顺序配置化）落地。

## 1. 两种正文排序模式

`config.json` → `archive.order_mode`：

| 模式 | 行为 | 适用 |
|------|------|------|
| `catalog`（默认） | 正文按标准案卷目录序号 0..N 重排；同槽内按 `(doc_id, start_page)` | 正式归档、强调目录规范 |
| `original` | 正文保持源 PDF 原始页序；卷首/卷末系统模板与卷内目录照旧 | 强调文档自然流转、快速查阅 |

- getter：`settings.get_archive_order_mode(config)`
- CLI：`run_archive.py --order-mode {catalog,original}`
- GUI：完整归档卡片「正文排序」单选
- 入口：`pdf_archive_merger.build_full_archive(..., order_mode=...)`
- 两模式均满足**源 PDF 页守恒**（PRD D5），失败则 `success=False`。

## 2. 文书识别 / 排序准确度改进（Phase J）

1. **乱序检测修复**：`_verify_document_order` 重写为「同 (catalog_seq, source_path) 内按插入顺序校验 `start_page` 单调」，
   修正历史 bug（先 `sort(doc_id)` 再判 `doc_id` 递减导致恒不触发）。issues 纳入 `ArchiveResult.order_issues`。
2. **多源排序稳定**：`assign_catalog_seq` 按 `(source_path, start_page)` 排序，路径 B 多文件不交错，相邻同槽合并只在同源内生效。
3. **类型二次校验扩充**：`_validate_document_type` 增加 mediation / indictment / appeal 规则，含起诉书↔上诉状消歧。
4. **标题模糊匹配收紧**：`_match_catalog_items` 改为要求 ≥3 字符最长公共子串（`_longest_common_substring_len`），避免误拉 seq。
5. **消除双轨**：纯锚点 `segment_documents` 标记弃用（保留为无目录上下文 fallback），主链路统一 `segment_by_catalog`。

## 3. 手动兜底

GUI analyze 后弹出「文书顺序与归属调整」对话框：

- 可改每份文书的目录归属（`catalog_seq`，仅正文槽）
- 可上移/下移调整插入顺序（确认时重排 `doc_id`）
- 确认后 `archive_pipeline.recompute_found_and_missing` 刷新缺失清单

## 4. 回归

```bash
py scripts/verify_doc_order.py       # 乱序检测 + 兴泰贸易同槽页序
py scripts/verify_order_mode.py      # catalog vs original（免 OCR）
py scripts/verify_cli_supplement.py  # CLI 解析 + 多文件补充（免 OCR）
py -m pytest tests/ -q               # 纯逻辑单测
```
