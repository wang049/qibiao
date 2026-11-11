# 2026-11-11 手册里唯一的组和通道要写出来

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_adc_group_stays_empty_when_converters_differ`）

## 代价

ADC 表只把转换器名堆在通道列。`EVADC_G10CH8` 能看出组和通道，但表上没有 `Ch8`。端口表标记说明只有「手册分类：ADC」，没有这一组和这一通道。两路 EVADC 若写成其中一组，会把没选定的转换器当成已经分组。

## 反事实

继续不写通道号，下一份 `AA18` 的通道列仍只有 `EVADC_G10CH8`，标记说明没有「分组：G10 Ch8」。`P00.2` 同时有 `EVADC_G10` 和 `EVADC_G0` 时若写成一组，组号不再留空。

## 二级依据

- 会议口径：分类之后，手册写明的复用用来看这只脚落在哪一组、哪一通道。多种接法不自动选定。
- 组号仍只取唯一的 EVADC 组或 TMADC。EDSADC 不另算一组。通道号只有一个时才写 `Ch`。

## 闸门

`test_adc_group_stays_empty_when_converters_differ`：`AA18` 的组是 `G10`，通道列以 `Ch8` 开头，并保留 `EVADC_G10CH8`。`N6` 有两组，组号为空。
