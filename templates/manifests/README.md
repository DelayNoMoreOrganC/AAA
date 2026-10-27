# 模板单元格映射表（格式版本 1.2，V6 仍使用）

每份 Word 模板对应一个 JSON，程序**仅**对 `role` 为 `fill` / `clear` / `seq_fill` 的格写入内容；`fixed` / `header` 格不修改。

## 维护流程

1. 修改 `templates/bundled/*.doc` 后，在项目根目录执行：
   ```
   python tools/generate_template_manifest.py
   python fix_manifest_roles.py
   ```
2. 用编辑器打开本目录下对应 JSON，核对 `preview` 与 `role`。
3. 运行模板填充测试，并在 V6 浏览器核对页检查对应表格。

## 字段说明

| role | 含义 |
|------|------|
| fill | 含【占位符】，按字段映射替换 |
| clear | 【留空】等，填入空字符串 |
| seq_fill | 同一占位符多行依次填入（送达清单法院文书） |
| header | 表头列名，不写入 |
| fixed | 固定文字，不写入 |
