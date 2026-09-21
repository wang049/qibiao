# 2026-09-20 清单外只收设计用得上的产品条目

- 状态：active
- 条目：清单外
- 闸门：`electrical/tests/test_extract_quality.py::OffListRequirementTests.test_off_list_keeps_only_useful_product_items`；`electrical/extract.py::_is_off_list_useful`

## 代价

DHTS160 2026-09-20 13:44 清单外约 31 行。材料禁令、MCU、开发 CAN 有用；USCAR/IPC/危险事件/耐压周边/熔断器 135%/NVH 套话/3.25 bar/CARB/safety rules 占满页，设计 SOR 几乎用不上。

## 反事实

不把清单外收成材料禁令、涂镀/追溯、MCU/开发总线白名单，下次仍会用安全与布线 shall 堆 20–40 行，有用条目被淹没。

## 二级依据

1–120 已覆盖放电、耐压、冷却流量、功能安全、通讯。清单外只补当份里主表没有的产品/材料/芯片约束。抽出值仍只来自当份原句。

## 闸门

涂镀/追溯/回料/胶水/MCU/5Mbit/ICD-09 进 extra。USCAR、J-STD、危险事件、135%、NVH、3.25 bar、CARB、safety rules 不进。extra ≤ 10。
