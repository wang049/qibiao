# 2026-11-10 器件中文名按 20261110 规则表各页的 Type 对

- 状态：active
- 条目：CE BOM 出表
- 闸门：`tests/test_ce_bom.py`（`test_name_rules_read_type_from_every_sheet`、`test_edf_counts_same_part_and_does_not_fill_the_standard_sheet`）

## 代价

只读规则表第一页、并且只认前两列时，电阻、电容、电感都对不上中文名。电感页的 Type 在第二列，读第一列会把规格型号当成 Type。

## 反事实

下一次仍只用 `06_IC` 时，`Res`、`Cap`、`IND`、`Bead` 的零件中文名称留空。把 `Design Item ID` 当成 Type 时，`IND` 对不上「电感」。同一 Type 有两种中文名时改用后一行，`Z` 会写成 Mark点，而不是表上先写的「稳压管/特殊器件」。`*` 和「（未定义）」写进零件名。

## 二级依据

- 确认口径：零件中文名称只来自规则表。规则表没有的 Type 留空，不自造。同一 Type 多行时用第一次写出的类型。
- 规则表 `CE BOM 器件中文名称对应规则示例_20261110.xlsx` 共 10 页。`01` 到 `02`、`04` 到 `10` 的表头是 Type、类型。`03_Inductor & Bead & CMC` 的 Type 在第二列，类型在第三列。
- `Res` 为贴片电阻，`Cap` 为贴片电容，`IND` 为电感，`Bead` 为磁珠。`Z` 先写「稳压管/特殊器件」，后写「Mark点」。`*` 的类型是「（未定义）」，不采用。

## 闸门

`test_name_rules_read_type_from_every_sheet`：`Res` 为贴片电阻，`IND` 为电感，`Bead` 为磁珠，`Z` 为稳压管/特殊器件。没有类型的 `Cap` 和 `*` 不进表。
`test_edf_counts_same_part_and_does_not_fill_the_standard_sheet`：当本机规则表把 `Res`、`Cap` 对上中文名时，供应商表写入该中文名；表不在时这两格仍为空。
