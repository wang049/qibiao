# 2026-11-10 已有 CE BOM 只做校核

- 状态：active
- 条目：CE BOM 出表
- 闸门：`tests/test_ce_bom.py`（`test_previous_bom_marks_difference_and_does_not_invent_rows`）

## 代价

生成结果不对照已有 CE BOM。用量和规格变了看不出来，上一版有而这次输入没有的零件会被补进表。

## 反事实

若用上一版填当次没有的行，下一份 AD BOM 会混进旧零件。用量从 1 变成 2 时仍显示一致。

## 二级依据

- 会议口径：电子件准确率靠与已有 CE BOM 校核。电子件来自 AD BOM 的 TYPE、数量、规格和中文名称，级别默认 4。结构件有图为 2 级、无图为 3 级，3 级尺寸手填。
- 校核只比较当次已经写出的名称、用量、规格。上一版多出来的名称记入核验，不补行。

## 闸门

`test_previous_bom_marks_difference_and_does_not_invent_rows`：用量不同写成「不一致：用量」；相同写成「一致」；当次没有的名称是「上一版没有」，读取结果里也不出现未给出的零件。
