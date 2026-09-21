# 2026-09-20 清单外按 XCM 前期设计补主表缺口

- 状态：active
- 条目：清单外
- 闸门：`electrical/tests/test_extract_quality.py::OffListRequirementTests.test_off_list_keeps_only_useful_product_items`；`electrical/extract.py::_OFF_LIST_USEFUL`

## 代价

只收材料/MCU 时，规格书里前期要用的冷却承压、CARB 诊断、带 8 级的 NVH 被一刀切掉；收全 shall 又会进 USCAR/IPC/危险事件套话。

## 反事实

不按「主表没有、前期选型/结构/软件范围用得上、当份有可核对答案」收清单外，下次要么空页缺冷却承压和诊断立法，要么再堆布线转引。

## 二级依据

120 项已覆盖电压/电流/放电/耐压/冷却流量与压降/功能安全/通讯方式。前期缺口常见在：芯片资源、开发 CAN、ICD、材料禁令与追溯、冷却回路耐压（不是 #71/#112）、有级数或 dB 的 NVH、CARB/OBD 诊断范围。抽出值只来自当份原句。

## 闸门

3.25 bar 绝对压力、CARB、NVH 8 级进 extra。USCAR、J-STD、危险事件、熔断器 135%、safety rules 不进。
