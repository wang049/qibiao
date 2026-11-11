# 2026-11-10 手册出表藏起 ADC 信号名，关键词标须进入 HSI

- 状态：active
- 条目：HSI 出表、ICD 出表
- 闸门：`tests/test_hsi.py`（`test_dedicated_symbols_get_a_manual_class`、`test_manual_hsi_hides_adc_signal_name`）、`tests/test_icd.py`（`test_pins_parts_and_hv_come_from_the_sheet`）

## 代价

手册生成的 ADC 表若仍留着 Signal name 列，会露出上一份项目的信号名。GTM 脚被标成 Timer，看不出要按 PWM 交给人工选复用。ICD 里的水温、CAN、LIN 没有标成必须进入 HSI。信号名列的删除见 `2026-11-11-hsi-drop-signal-name-and-extra-pin.md`。

## 反事实

不隐藏 Signal name 列，下一次手册出表的 F 列和 X 列仍显示 `IA_S/M_TM` 这类原理图才会有的名字。把多路复用自动收成一个功能，会在占比很少的冲突上替人工做选择。关键词不对上时，水温采样仍要人逐行去对 HSI。

## 二级依据

- 确认口径：有原理图时沿用模板，只更新认得出的引脚配置。仅手册时先认型号、数总脚数，再按电源、ADC、PWM、GPIO 分类，并列出可配置信号供选择。
- ADC 表 F 列和 X 列表头是 `Signal name`。L 列是时间常数的单位，不是信号名。手册出表删掉 Signal name 列。有原理图时按端口表网络名回填仍在的信号名列。
- 固定关键词是水温、CAN、LIN。复用多于一个时只列出，不自动选定。

## 闸门

`test_dedicated_symbols_get_a_manual_class`：`GTM_TOUT17` 的手册分类是 PWM。
`test_manual_hsi_hides_adc_signal_name`：Signal name 列被删掉，L 列单位仍是 `A`。
`test_pins_parts_and_hv_come_from_the_sheet`：信号 `CAN1_H`、名称「水温采样」标成须进入 HSI，关键词为水温和 CAN。
