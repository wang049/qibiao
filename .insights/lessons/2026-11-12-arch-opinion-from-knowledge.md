# 2026-11-12 架构对照意见对电驱卡片

- 状态：active
- 条目：电驱需求拆解出表
- 闸门：`tests/test_arch_contrast.py`（`test_power_conflict_uses_the_power_card_and_keeps_the_current_wording`、`test_named_standard_cites_the_registered_source`、`test_unmatched_row_still_gets_an_opinion`）

## 代价

需求清单的意见栏一直空着。同文件功率前后不一致只写在备注里，没有对应的处理意见。

## 反事实

不把意见接到电驱卡片上，下一份架构对照的「意见」仍空。功率冲突若没有单独的卡片，会写成「尚无对应口径」，或者把 2.5 kW 和 2.72 kW 合成一个数。

## 二级依据

- 确认口径：意见写卡片里的说法，理由带卡片编号和当份质检原句。数值与单位仍只来自当份原文。状态保持 To be confirmed。
- 卡片 `arch-same-file-power`：同文件功率前后不一致时，意见为「标为同文件功率不一致，请按当份原文核对适用条件」。
- 对不上标准、图号、接口和同文件冲突时，函数仍能返回「知识库尚无对应口径」。需求清单不把这句写进每一行，见 `2026-11-13-arch-blank-repeated-opinion.md`。

## 闸门

`test_power_conflict_uses_the_power_card_and_keeps_the_current_wording`：意见含「同文件功率不一致」，不含「满足」；理由含卡片编号和当份的 2.5kW、2.72kW。
`test_named_standard_cites_the_registered_source`：原文点名 GB/T 18488-2024 时，意见为对照该标准，理由带来源编号。
`test_unmatched_row_still_gets_an_opinion`：函数对不上时仍返回「尚无对应口径」。出表不把这句写入每一行。
