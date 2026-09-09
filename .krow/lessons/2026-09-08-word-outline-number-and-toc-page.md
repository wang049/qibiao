# 2026-09-08 Word 大纲号要写回正文；页码只认 Word 印页

- 状态：active
- 条目：条款号列（#5/#6/#7、#21/#22、Boost、重量、热损失等）；页码列
- 闸门：`electrical/tests/test_read_doc.py`（`test_prefix_skips_typed_clause`、`test_page_key_strips_clause_not_decimal_kg`）；`electrical/tests/test_doc_kind.py`（`test_dhts_boost_and_weight_match_header_pages`、`test_align_word_pages_ignores_restored_outline_prefix`、`test_docx_without_word_does_not_use_toc_as_printed_page`）；`electrical/tests/test_extract_quality.py`（`test_word_outline_hvdc_clause_not_cleared_by_unnumbered_name`、`test_printed_lv_heading_is_6_5_2`、`test_printed_heat_loss_clause_is_6_8_4`）；`electrical/read_doc.py` `_DocxOutline`、`_pages_from_printed_docx`、`_norm_page_key`；`electrical/extract.py` `_clause_for_index`

## 代价

DHTS / SuperEvo 核对表大量已填格条款号空。Word 打开时标题印着 `2.3.1` / `6.5.3` / `6.5.4`，python-docx 的 `para.text` 不含自动编号。Mac 没有 Word COM 时页码可以空；工位交付在 Windows，页码必须是打开文档后页眉 PAGE，不能用目录 PAGEREF 插值或 LibreOffice 回流页顶替。

## 反事实

不把 Word 大纲自动编号写回标题、标题行已有 `6.5.3 HVDC Voltage Range` 仍被未印号闸门清掉，下次条款列继续空，或把上一节 Protection `6.4.2.4` 挂到高压范围表。写回大纲号后若不对齐时去掉该前缀，Windows 上 Word 段落对不上，命中率不够会丢掉印页。没有 Word 时若用目录插值当印页，Boost/高压范围会比页眉 PAGE 早 1 页。

## 二级依据

- 当份 Word：标题样式 Heading 1/2/3 + `numbering.xml` abstract 0（`%1.%2.%3`）。印页可见 `2.3.1 Weight`、`6.5.2 LV power consumption`、`6.5.3 HVDC Voltage Range`、`6.5.4 HV Booster`。已手打 `6.2.3.2 High Voltage DC connection` 的不要再叠号。
- 专家第一版页码（打开 Word 的 PAGE）：重量 23、#5–#7 为 53、Boost 54、绝缘 67。Windows 用 Word/WPS `wdActiveEndPageNumber`。目录 `6.5 PEI → 52` 不是段落印页。LibreOffice 转 PDF 的 HVDC/Boost 约 60/61 也不是。
- 交叉：`2026-09-07-hvdc-range-is-not-protection-clause`（未印号片段仍不得抄 6.4.2.4）；`2026-09-07-no-printed-652-no-external-5310`（无自动编号、正文也无字面 6.5.2 时仍不得用 DHTS 目录套 SuperEvo）。

## 闸门

- 读 `.docx`：Heading 段落按 `numbering.xml` 前置十进制大纲号；已手打条款号不重复。
- `_clause_for_index`：当前行已是「条款号 + PEI 标题」时保留该号；未印号的 `HVDC Voltage Range` 等仍切断上一节号。
- 页码：只问本机 Word/WPS；没有再读同目录 PDF。不用目录 PAGEREF 插值。无 Word、无 PDF 时页码列空，不得发明「第 1 页」。对齐 Word 段落时去掉写回的 `x.y.z`，不要去掉 `20.2kg`。
- 回归：DHTS 正文出现 `6.5.3 HVDC Voltage Range`；写回号的标题仍能对上 Word 给出的 23/53/54/67；无 Word 时不得用目录冒充印页；未印号高压范围表条款仍空；印了 `6.8.4 Heat loss` 时热损失条款为 6.8.4 不是 6.8.3。
