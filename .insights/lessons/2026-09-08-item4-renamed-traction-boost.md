# 2026-09-08 #4 正式名改为行车升压

- 状态：active
- 条目：#4 设计范围是否包含行车升压功能（原「充电升压」）；#3 驱动升压
- 闸门：`electrical/tests/test_extract_quality.py`（`test_item_4_scope_renamed_to_traction_boost`、`test_charging_table_not_drive_or_bus`、`test_scan_env_and_boost_scope`）；`electrical/extract.py` `_ITEM4_SCOPE` / `_canonical_field_name`；`tests/test_clause_lexicon.py`（`test_item_4_renamed_to_traction_boost`）

## 代价

甲方把清单第 4 条由「充电升压」改成「行车升压」。若只改 Excel 表头、出表仍按旧字段名 `add()`，第 4 行对不上，充电 Boost/Buck 会进「额外抽出」。若把「行车升压」继续当作 #3 强别名，认条会和 #4 抢同一句。

## 反事实

不改模板名、不把 `add()` / `_value_fits_field` / 旧名绑定改到新正式名、不从 #3 拿掉「行车升压」，下次仍会：核对表第 4 行空白或进错列；boost control 误填 #4；「行车升压」被认成 #3。

## 二级依据

- 甲方要求：第 4 条正式名为「设计范围是否包含行车升压功能」。
- 清单 gloss：#3 仍是驱动升压（HV Booster / boost control）；#4 与 #115 仍是充电 Boost/Buck 范围判断 vs 充电定义。交叉 `2026-09-04-115-connector-is-not-charge-definition`、`2026-09-07-no-printed-652-no-external-5310`。
- 模板：`电气/templates/电机控制需求清单.xlsx` 序号 4。

## 闸门

- 模板 seq 4 名称必须是「设计范围是否包含行车升压功能」。
- 旧名「设计范围是否包含充电升压功能」经 `_canonical_field_name` 仍绑定 seq 4。
- Charging Buck/Boost 填 #4 新名，不填 #3；boost control 不填 #4。
- #3 强别名不再含「行车升压」；#4 正式名含「行车升压」。
