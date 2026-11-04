# 2026-11-04 ADC 表不留模板阻容

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_adc_drops_template_circuit_constants`）

## 代价

`3_ADC Table` 的 Circuit constant 仍显示模板滤波参数，像是这颗芯片的采样电路。

## 反事实

不清 C1、R2、C2 和 τ，下一次打开仍是 `3.3` nF、`0.1` kΩ、`0.22` nF，以及「电路滤波延迟 4us；霍尔芯片延迟 3us」。

## 二级依据

- 这些数在 DHTE400 `3_ADC Table` 第 5、7、8 行，表头是 `C1(nF)`、`R2 (kΩ)`、`C2(nF)`、`τ(us)`。TC499 手册没有这些阻容和延迟。
- 清的是表头下面的数、公式和这些格子上的细边框。表头留下。R1、R3 仍隐藏。

## 闸门

`test_adc_drops_template_circuit_constants`：`C1(nF)`、`τ(us)` 表头还在；`3.3`、滤波延迟句子、`=Z7*AA7` 和 C1 格的边框被清掉；AN0 的球号仍是 `W13`。
