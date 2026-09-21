# 2026-09-20 清单外多收指标但守质量

- 状态：active
- 条目：清单外
- 闸门：`electrical/tests/test_extract_quality.py::OffListRequirementTests.test_off_list_keeps_only_useful_product_items`；`electrical/extract.py::_off_list_candidates` / `_off_list_indicator_name` / `_is_off_list_useful`

## 代价

14:12 表只剩 11 行：涂镀/追溯/ICD/KL15 因表格竖线被整行丢掉；NVH、分析程序用整句当名称。设计要尽量多的可核对指标，不是越少越好。

## 反事实

不从表单元格收 shall/应、不把「将在整车测试 / 分析程序」改成 NVH评级和 TOP-60cm 噪声、不用带单位数字补收前期指标，下次要么漏第 4 章外观追溯，要么名称仍是场合句。

## 二级依据

前期清单外补主表缺口：材料标识、芯片与开发口、ICD、诊断立法、冷却承压、带级数或 dB 的 NVH。表格里的原句仍是当份原文。符合 ISO/USCAR/IPC 的转引和危险事件套话仍不是指标。

## 闸门

表格中的涂镀平整光滑、追溯码打印、ICD-09、KL15 进 extra。NVH 名称必须是「NVH评级」。分析程序不得当名称。USCAR、135%、危险事件不进。
