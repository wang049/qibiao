# 2026-11-10 CE BOM 电子件点在 4 级，结构件有图为 2、无图为 3

- 状态：active
- 条目：CE BOM 出表
- 闸门：`tests/test_ce_bom.py`（`test_ad_bom_type_maps_to_chinese_name`、`test_edf_counts_same_part_and_does_not_fill_the_standard_sheet`、`test_structure_drawing_fills_supplier_sheet_and_drops_template_rows`、`test_structure_level_follows_the_detail_parent`、`test_hardware_and_structure_stay_on_separate_supplier_sheets`）

## 代价

电子件如果仍点在 1 级，和会议定的默认 4 级对不上。结构图的本图零件点在 1 级、明细子件点在 2 级，有图和无图就对调了。表头只在第一格写「级别」、下一行才是 1 到 5 时，如果只认写着「级别」的那一格，4 级这一列点不上去。

## 反事实

下一次 AD BOM 或 EDF 仍把 ● 点在 1 级，电子件就不会落在 4 级。壳体图的本图零件仍点在 1 级，摩擦焊板和密封胶仍点在 2 级，有图的不会是 2 级、无图子件不会是 3 级。只认表头「级别」那一格时，下一行的 2、3、4、5 列收不进来，4 级没有格子可点。把图上散落的长、宽、高填进 2 级件，或给 3 级件补尺寸，都会在图纸没有单列外形尺寸时造数。

## 二级依据

- 确认口径：电子件默认 4 级。结构件默认 2 级有图纸，3 级无图纸。2 级件的长宽高只在图纸写明时读取，不从散落标注里挑。3 级件尺寸手动填写。级别点在供应商表「级别」下面标着 1 到 5 的那一列。
- 会议：电子件从 AD 导出的 BOM 生成，层级默认 4 级。结构件先用一个总成的 2 级件图纸试，3 级件无图，尺寸手动填。
- 模板 `3DHT200-CE BOM` 第 14 行只有一格写「级别」，第 15 行 B 到 F 为 1、2、3、4、5。
- `DHT160OF-5501801758` 壳体图写明无指示尺寸参照数字化模型，标题栏没有单列的长、宽、高。质量栏没有单位时仍不写入净重。

## 闸门

`test_ad_bom_type_maps_to_chinese_name`：电容和微控制器的 ● 在 E 列，B 列为空。
`test_edf_counts_same_part_and_does_not_fill_the_standard_sheet`：两行电子件的 ● 都在 E 列。
`test_structure_drawing_fills_supplier_sheet_and_drops_template_rows`：盖板的 ● 在 C 列，B 列为空。
`test_structure_level_follows_the_detail_parent`：壳体为 2 级，摩擦焊板和固化密封胶为 3 级。
`test_hardware_and_structure_stay_on_separate_supplier_sheets`：供应商表电容点在 4 级，结构表盖板点在 2 级。
