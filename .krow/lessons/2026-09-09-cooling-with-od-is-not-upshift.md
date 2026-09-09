# 2026-09-09 冷却流阻 (with OD) 不是 OD 上移

- 状态：active
- 条目：#2 设计范围是否包含OD上移功能；#71 冷却回路压降；#1 OD本体物理集成
- 闸门：`electrical/tests/test_extract_quality.py`（`test_od_upshift_rejects_cooling_with_od`、`test_coolant_drop_uses_6_8_3_not_interface_flow_resistance`）；`electrical/extract.py` `_value_fits_field`、`_od_module_parenthetical_not_upshift`、`_is_junk_value`

## 代价

DHTS 接口冷却句 `Cooling flow resistance … ≤ 35Kpa@65 ℃@10L/min;（with OD）` 被写成 #2 抽出值 `with OD`，状态已检索到、条款 6.2.2。当份没有 OD 上移功能；该括注是流阻规格含 OD 模块，应走 #71，物理集成走 #1 重量目标。

## 反事实

不把「条目名含 OD 且原文有 OD」改成「上移必须有上移/推荐电路等功能语义，并拒绝冷却括号 with OD」，下次模型仍会把 `with OD` 填进 #2 并标已检索到。

## 二级依据

- 清单 #2 gloss：把 OD 的驱动/控制功能上移到 XCM（需推荐电路或确认平台电路）。排除冷却流阻/压降括号 with OD（→#71）和重量目标 With OD Module（→#1）。
- 清单 #1：本体物理集成；重量句 `20.2kg(With OD Module)` 才是 #1。
- 清单 #71：冷却回路压降。同一句 35 kPa@65℃@10 L/min（含 OD）是压降，不是上移。交叉 `2026-09-07-heat-loss-is-not-coolant-drop-clause`。

## 闸门

- `_value_fits_field`：#2 不再因 `\bOD\b` 过闸；冷却/压降括号 `with OD` 拒填；真上移句（上移/推荐电路/relocation）仍可填。
- `_is_junk_value`：#2 抽出值仅为 `with OD` 视为垃圾。
- 回归：该冷却句经 `_store_cell` 后 #2 为空；#71 仍为 6.8.3。不得用清单示例「是」顶替当份未给出的上移结论。
