# 2026-09-20 清单外不漏印页、不收主表电参数

- 状态：active
- 条目：清单外
- 闸门：`electrical/tests/test_extract_quality.py::OffListRequirementTests.test_off_list_drops_template_electrical_and_fills_page`；`test_maps_active_discharge_to_template`；`electrical/extract.py::_maps_to_template_field` / `_page_from_full_markdown` / `_split_off_list_item`

## 代价

收紧后 DHTS160 核对表「清单外需求」仍进 P1/P3 200/250 Arms、被动放电 500VDC、冷却回路、最高效率 99%，印页全空；「禁止回料」只写出「使用和添加回料」，热模型表和 xx% 占位也占满 40 行。

## 反事实

不把 200/250/520 Arms、被动/主动放电、冷却回路、最高效率、测量误差判回主表，不从全文「第 N 页」回填印页，不把「禁止/不得」写进抽出值，下次清单外页仍会抄主表电参数、空页码，并把半截禁令和占位句当成指标。

## 二级依据

主表已覆盖 P1/P3 相电流、主被动放电、冷却流量/温度、效率、工作温度/湿度/振动。清单外只收当份原句里对不上 1–120 的产品/材料要求。抽出值须是 shall/应/禁止 后面可核对的答案；印页来自当份 `## 第 N 页`，不编页。

## 闸门

`200 Arms` / `Passive discharge` / `coolant circuit` / `最高效率` → `_maps_to_template_field` 为真，不进 extra。`禁止使用和添加回料` 抽出值以「禁止」开头且印页=91。`thermal table`、`不少于xx%` → split 为 None。
