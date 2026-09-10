# 2026-09-10 工位知识库来源登记不写甲方乙方

- 状态：active
- 条目：工位知识库「来源登记」文案（非清单格子）
- 闸门：`tests/test_knowledge.py` `test_browse_hides_contract_parties_on_sources`；`electrical_krow/knowledge.py` `_scrub_party` / `_source_confirm_status`；`electrical_krow/frontend/kb.js`

## 代价

来源登记把 `catalog.yaml` 的 `provided_by: 甲方 / 乙方整理，待甲方确认` 原样印在工位页。对表的人是客户工程师，合同角色没有信息量，还像内部台账。

## 反事实

工位页继续输出「甲方」「乙方」，下次来源登记仍像验收备忘，而不是密级、不出场所、已确认/待确认。

## 二级依据

- 工位使用者是现场工程师，不是合同甲乙方角色。密级与不出场所仍要看见。
- `catalog.yaml` 的 `provided_by` 仍可记谁提供，只是不进 `browse_catalog` 给页面。

## 闸门

- 公开来源对象用 `status`（已确认/待确认），不含 `provided_by`。
- `browse_catalog` 的 `scope` 与 `sources` JSON 不含「甲方」「乙方」。
