# 2026-11-04 手册里的专用脚也要归类

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_dedicated_symbols_get_a_manual_class`）

## 代价

NC、晶振、以太网、JTAG 和复位脚没有手册分类，看起来像漏识别。复用写成 `ADC_TMADC2CH6`、`GTM_TOUT17` 的脚也不进 ADC、Timer。

## 反事实

只认单词边界上的 ADC、GTM，下一次 `P00.8` 的复用 `ADC_TMADC2CH6` 仍没有「手册分类：ADC」。`NC1_A26`、`XTAL1`、`PHY1_TXP`、`TRST`、`PORST` 仍只有「模板没有该引脚符号」。

## 二级依据

- TC499 端口表里这几脚的符号就是 `NC1_A26`、`XTAL1`、`PHY1_TXP`、`TRST`、`PORST`。PORST 的功能原文含 Reset。
- 复用记号用下划线连着，如 `ADC_TMADC2CH6`、`GTM_TOUT17`。分类仍只写标记说明，不写进 Function。

## 闸门

`test_dedicated_symbols_get_a_manual_class`：上述符号分别是空脚、时钟、以太网、调试、复位；`ADC_TMADC2CH6` 为 ADC，`GTM_TOUT17` 为 Timer。
