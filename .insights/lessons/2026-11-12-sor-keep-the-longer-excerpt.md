# 2026-11-12 同一抽出值留下更完整的原句

- 状态：active
- 条目：#3 设计范围是否包含驱动升压功能
- 闸门：`electrical/tests/test_extract_quality.py`（`test_clipped_boost_excerpt_keeps_both_sentences`）

## 代价

第 3 条原文摘录是 `control, motor control, ... module. PCM is`，从句子中间起，又在下一句开头截断。抽出值已经写了 boost control 和 BOOST 架构，摘录却没有这两句的头尾。后到的高置信短摘录盖过了先抽出的整句。

## 反事实

置信度更高的短摘录继续赢，下一份扫描件第 3 条仍从 `control,` 起、停在 `PCM is`。`PCM is the control unit` 和 `variants tailored to the BOOST architecture` 仍不在摘录里。

## 二级依据

- 当份 4LDHT 扫描件第 44 页、条款 3.1：`PCM is the control unit of a hybrid dedicated transmission, which includes transmission control, motor control, thermal management control, boost control, and integrates power distribution module.` 下一句是 `Considering the platform integration of PCM, PCM must have variants tailored to the BOOST architecture.`
- 抽出值：`是；PCM 含 boost control，并按 BOOST 架构做平台变型`。

## 闸门

`test_clipped_boost_excerpt_keeps_both_sentences`：先写入截断摘录且置信度 0.9，规则再写入整句后，摘录从 `PCM is the control unit` 起，并含 `variants tailored to the BOOST architecture`。
