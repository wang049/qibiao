# 2026-11-12 原理图归档去掉空的项目页

- 状态：superseded
- 取代：`.insights/lessons/2026-11-12-hsi-keep-template-sheets.md`
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_blank_project_sheets_drop_and_dead_time_stays`）

## 代价

TC499 模板清掉上一项目的电路后，热泵、油温、PMIC、门驱这些页只剩表头。按原理图归档整本留下，打开的人看到一串空表。

## 反事实

第 4 行起没有内容的项目页若继续留着，下一份原理图归档仍会带上空白的热泵、油温、PMIC。死区页里已有的原句若被一起删掉，`1.6` 会消失。

## 二级依据

- 确认口径：端口、ADC、SPI、CAN 保留。原理图没有写到的项目页，第 4 行起没有字就删掉，封面目录里对应的名称一并去掉。
- 本次 `HSI--20261112.xlsx`：`18_热泵温度传感器`、`17_变速器油温`、`5_PMIC-TLF4D985` 只有表头。`3_ADC Table`、`4-SPI总线`、`6_CAN` 有内容。

## 闸门

`test_blank_project_sheets_drop_and_dead_time_stays`：空的热泵页被删，封面不再写热泵。死区页第 7 行的 `1.6` 还在，SPI 页还在。
