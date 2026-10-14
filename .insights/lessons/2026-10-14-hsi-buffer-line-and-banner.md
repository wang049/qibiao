# 2026-10-14 斜杠续行是缓冲，页眉不是复用

- 状态：active
- 条目：HSI 端口表
- 闸门：`tests/test_hsi.py`（`test_slash_buffer_line_is_not_the_function`）

## 代价

TC38x BGA292 有 69 个引脚的功能列写成 `/ FAST /` 或 `/ ES5`，General-purpose input 被放进复用。另有 99 个引脚的复用末尾是页眉 `TC38x AD/AE-Step`，摘录在 500 字处被截断。

## 反事实

不把单独成行的 `/ FAST /`、`X / FAST /`、`/ ES5` 留在缓冲里，下次功能列仍会写成这些斜杠行，手册上的 General-purpose input 进入复用。不把 `TC38x AD/AE-Step` 当成页眉丢掉，复用和摘录里仍会出现这行；摘录若再按 500 字截断，长引脚的原文会在词中间被切开。

## 二级依据

- 当份手册页 201。`B12 P13.0 I LVDS_TX` 下一行是 `/ FAST /`，功能原文是 General-purpose input。
- 当份手册页 208。`D12 P14.9 I LVDS_R` 下一行是 `X / FAST /`。
- 当份手册页 224。`P20 P22.0 I LVDS_TX` 下一行是 `/ FAST /`。
- 当份手册页 250。`VEVRSB` 下一行是 `/ ES5`，功能原文仍是 General-purpose input。
- 当份手册引脚页页眉为 `TC38x AD/AE-Step`，例如页 160。这一行不是复用功能。
