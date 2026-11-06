# 2026-11-05 结构图按供应商的列填写，模板零件行不留

- 状态：active
- 条目：CE BOM 出表
- 闸门：`tests/test_ce_bom.py`（`test_structure_drawing_reads_title_and_detail_rows`、`test_structure_table_above_header_keeps_weight_blank_without_unit`、`test_structure_drawing_fills_supplier_sheet_and_drops_template_rows`、`test_hardware_and_structure_stay_on_separate_supplier_sheets`、`test_required_fields_follow_electronic_and_structure`）

## 代价

结构二维图和硬件 BOM 写在同一张供应商表里，零件号和用量会对不上。明细栏只往表头下方找，表头在数据下面的壳体图会整表丢掉。质量栏的 `3.8` 没有单位，写成净重就是造数。

## 反事实

明细只搜表头下方，壳体图的摩擦焊板、固化密封胶在表头上方，下一次会整表丢掉。把质量栏的 `3.8` 写成 `3.8g`，单位是补出来的。把标题栏特性数量 `0`、`10` 写成用量，盖板用量就错了。结构行写到列不一样的另一张表，供应商仍留着模板零件，这次读到的盖板不会出现在供应商表。硬件和结构写进同一张供应商表，两类零件会混在一起。沿用模板冻结在第 105 行，打开后停在空白处，第 16 行的壳体看不见。壳体和摩擦焊板的级别都空着，或因为有上级总成号就把壳体写成 2 级。材料标记是 `/` 时写成原材料，空材料被当成有值。

## 二级依据

- 确认口径：读到的数据按供应商表的列写入，模板里原有的零件行不保留。只上传结构图时写入供应商。同时有硬件时，硬件留在供应商，结构另起一张同样列序的表。结构只从标题栏、明细栏取能对上的字段。本图零件是级别 1，明细子件是级别 2，在对应的级别列写 ●。上级总成不在本表时，不把本图零件降成 2。电子件网表和 AD BOM 没有父子零件，每一行都是 1 级。产品尺寸不从散落标注里挑。
- `MS_02` 标题栏：图样名称「保险盒接线盖板」，图样代号 `5501801798`，材料标记 `Al5052-O态`，质量 `31g`，上级总成 `5501801726`。技术要求写明「板料厚度1.5±0.15mm」。特性数量 `0`、`10` 不是零件用量。这张图没有明细栏。
- `MS_06` 明细栏表头在数据上方。五行：PN-N铜排、PN-P铜排材料 `T2HO2` 各 1；衬套「碳钢-镀锌镍」2；塑料本体 `PPS-GF40` 1。标题材料标记是 `/`。质量 `216g`。
- `5501801758` 明细栏表头在数据下方。壳体行零件号与标题相同，材料 `ADC12`。质量栏是 `3.8`，旁边没有单位。

## 闸门

`test_structure_drawing_reads_title_and_detail_rows`：盖板读出名称、零件号、`31g`、`Al5052-O态`、`1.5±0.15mm` 和上级总成。用量留空。明细行读出铜排和材料。
`test_structure_table_above_header_keeps_weight_blank_without_unit`：表头在数据下方仍能读出摩擦焊板。质量 `3.8` 不写入净重，备注记未标单位。`/` 不写进零件名。
`test_structure_drawing_fills_supplier_sheet_and_drops_template_rows`：盖板写入供应商的零件中文名称、零件号、材料厚度、净重和原材料。模板里的密封圈和净重公式被清除。级别和产品尺寸留空，产品尺寸记入核验。已有净重和原材料，不记缺项。
`test_hardware_and_structure_stay_on_separate_supplier_sheets`：同时有 AD BOM 和结构图时，电容在供应商，盖板在「结构」。两张表都用供应商的列。
`test_standard_sheet_keeps_structure_formulas_and_existing_numbers`：模板冻在 `H105` 时，生成后冻结改到 `A16`，打开位置不再停在第 105 行。
`test_structure_level_follows_the_detail_parent`：壳体是级别 1，摩擦焊板和固化密封胶是级别 2。上级总成不在表里，壳体不降级。
