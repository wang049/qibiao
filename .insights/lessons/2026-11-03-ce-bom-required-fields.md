# 2026-11-03 标准 CE BOM 先核对必填，不补数

- 状态：active
- 条目：CE BOM 出表
- 闸门：`tests/test_ce_bom.py`（`test_standard_sheet_keeps_structure_formulas_and_existing_numbers`、`test_cover_plate_missing_thickness_is_recorded_not_filled`）

## 代价

序号、级别、零件中文名称、用量已经确认为必填，盖板的材料厚度为空也要能看见。标准表若仍只写「填写规则未到」，这些空格不会出现在核验记录里。

## 反事实

不核对必填，下一次标准表里没有序号、用量的零件行仍显示为通过。盖板没有材料厚度时也不记一笔。若据此把厚度或净重写进格子，就会在密度和图纸都还没有的时候造数。

## 二级依据

- 确认口径：序号、级别、零件中文名称、用量必填；零件号有则填；图片暂不处理；材料厚度仅盖板类必填。
- 净重按体积×密度，这次没有给出密度。产品尺寸、原材料要区分电子件和结构件，标准表没有这一列。
- EDF、Altium BOM、PLM 仍待确认或未接入，不作为本次写入来源。

## 闸门

`test_standard_sheet_keeps_structure_formulas_and_existing_numbers`：密封圈缺序号被记入核验，尺寸和公式原样保留，手册里的 999 不写入。
`test_cover_plate_missing_thickness_is_recorded_not_filled`：上盖板缺材料厚度被记下，厚度格仍为空。
