# 2026-11-04 ADC 组分配等确认后再写

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_adc_drops_template_group_allocation`、`test_supply_pin_stays_on_the_sheet_and_is_hidden`）

## 代价

`3_ADC Table` 下方的组×通道表，以及 `Gr0`、`Ch0`、`IA_S/M_TM`，看起来像这次已经分配好的结果。

## 反事实

留下模板组号和信号名，下一次打开仍是 `Gr0 / Ch0 / IA_S/M_TM`，以及「GM current sense」。拿这张表去写「三相电流应配置在不同 group」，会把上一份项目的分配写进标记说明。

## 二级依据

- DHTE400 `3_ADC Table` 第 5 行是 `Gr0`、`Ch0`、`IA_S/M_TM`。第 129 行起是 Group × CH0–CH15，格子里是同一批信号名，没有公式。
- 图例：绿色 TM current sense，蓝色 GM current sense，灰色「不可用通道，已被其它PIN占用」。
- TC499 手册没有这些组号和项目信号。分类仍写在标记说明：「手册分类：ADC。分配待人工确认」。手册通道名，如 `ADC_TMADC2CH0`，仍写入 channel 列。

## 闸门

`test_adc_drops_template_group_allocation`：`Gr`、`channel`、`Signal name` 表头还在；`Gr0`、`Ch0`、`IA_S/M_TM`、Group 对照和 current sense 被清掉；AN0 的球号仍是 `W13`，channel 含 `ADC_TMADC2CH0`。
`test_supply_pin_stays_on_the_sheet_and_is_hidden`：AN0 的标记说明有「分配待人工确认」，没有「三相电流」。
