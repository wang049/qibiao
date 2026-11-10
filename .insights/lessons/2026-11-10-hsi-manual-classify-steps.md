# 2026-11-10 无原理图时分步认型号、数脚、分类

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_dedicated_symbols_get_a_manual_class`、`test_supply_pin_stays_on_the_sheet_and_is_hidden`）

## 代价

手册路径一次写完端口，不先落总脚数和分类。标记说明对 ADC 等不写「手册分类」，封面也不带分类汇总。

## 反事实

若不先认 MCU、数脚再分类，下一份无原理图规划仍看不出电源/地/ADC/SPI/CAN/GPIO/IO 各多少只，功能列也容易被误改成手册分类词。

## 二级依据

- 会议与白板：无原理图从 datasheet 出发，先认 MCU 与总脚数，再按电源、GND、IO、ADC、SPI、CAN、GPIO 等分类，再按复用填信号；不靠模型猜类别。
- Function 列仍只用模板用法词（Analog、Digital、PWM、SPI、CAN…），分类写在标记说明和手册依据表，不进 Function。
- 独立 MCU 模板文件名含型号时由 `hsi_template_for_mcu` 选用；目前仓内默认仍是 DHTE400。

## 闸门

`test_dedicated_symbols_get_a_manual_class`：QSPI→SPI、CAN→CAN、裸端口→IO。`test_supply_pin_stays_on_the_sheet_and_is_hidden`：电源写「手册分类：电源」，AN0 写「手册分类：ADC」且 Function 仍为 Analog。
