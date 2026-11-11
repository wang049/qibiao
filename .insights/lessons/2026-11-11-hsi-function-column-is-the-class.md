# 2026-11-11 手册分类写入 Function 列

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_supply_pin_stays_on_the_sheet_and_is_hidden`、`test_dhte400_keeps_atom_port_name_cover_and_history`）

## 代价

没有原理图时，J 列 Function 写的是模板里对上的 Analog、PWM、CAN。会议要的电源、地、IO、ADC、GPIO 只附在标记说明后部，筛选 J 列看不到。

## 反事实

继续写模板功能词，下一份端口表 J 列仍是 Analog 80、PWM 60 这种筛选。`AN0` 的 Function 仍是 Analog，不是 ADC。`VDD` 的 Function 仍空着，不是电源。

## 二级依据

- 会议口径：引脚分类是电源、地、IO、ADC、GPIO 等，按手册归类。J 列就是这张表上的分类列。
- 归类只看当份手册的符号、功能和复用。对不上的留空。有原理图的归档不改这一列的既有填法。

## 闸门

`test_supply_pin_stays_on_the_sheet_and_is_hidden`：`VDD` 的 Function 是电源，`AN0` 是 ADC。
`test_dhte400_keeps_atom_port_name_cover_and_history`：`AN0` 的 Function 是 ADC。
