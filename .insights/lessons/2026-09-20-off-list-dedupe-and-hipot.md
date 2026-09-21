# 2026-09-20 清单外去中英重复、耐压不进、半截主语丢掉

- 状态：active
- 条目：清单外
- 闸门：`electrical/tests/test_extract_quality.py::OffListRequirementTests.test_off_list_dedupes_bilingual_and_drops_hipot_junk`；`electrical/extract.py::_off_list_same_item` / `_OFF_LIST_ON_TEMPLATE` / `_OFF_LIST_SPLIT_CN`

## 代价

DHTS160 2026-09-20 13:21 清单外 40 行：ISO 6469 耐压抄回主表 #14；单点故障 / USCAR-12 / IPC 中英各占一格；`由供` 切在「供应商」的「应」上；`应能够` 切成「够根据CARB」；本文件应包括、campaign、连续进料占满名额，涂镀/追溯后段进不来。

## 反事实

不按条款+标准号合并中英、不把耐压/电基频 0.95×Ipeak 判回主表、不把「应能够」和「应商」从「应」里拆开，下次仍会用半截主语和重复句占满 40 行，第 4 章产品要求继续被顶掉。

## 二级依据

#14 是高压安全-耐电压。清单外只收对不上 1–120 的当份产品/材料/MCU 要求。同一条款同一 ISO/SAE/IPC 号是一条，中英留一条。抽出值须是 shall/应/禁止 后面的完整答案，不能从「供应商」里切开。

## 闸门

耐压能力测试、0.95*I peck → `_maps_to_template_field` 为真。本文件应包括 / campaign / 连续进料 / 由供应商根据…测试 → split 为 None。`应能够根据CARB` 抽出值以「根据CARB」开头。同条款 USCAR-12、J-STD-001、危险事件 各至多 1 行。涂镀平整光滑、追溯码打印仍在 extra。
