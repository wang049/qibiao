# 2026-09-07 热损失不是冷却压降条款 6.8.3

- 状态：active
- 条目：#120 热损失；#71 / #119 冷却回路压降
- 闸门：`electrical/tests/test_extract_quality.py`（`test_coolant_drop_uses_6_8_3_not_interface_flow_resistance`）；`electrical/extract.py` `_pick_clause`、`_UNNUMBERED_PEI_HEADING`、`_HEADING_CLAUSE`

## 代价

DHTS160 #120 抽出值 `≤6.17kW（恒速）` 来自未印号标题 `Heat loss 热损失`，条款列却写成 `6.8.3`。现场按该号打开，看到的是冷却回路压降，不是热损失。当份正文没有印出 `6.8.3`。

## 反事实

不把未印号的热损失节从压降标题映照里拿掉，下次仍会把 `Coolant pressure drop → 6.8.3` 挂到 #120；压降格自己仍应保留该映照。

## 二级依据

- 清单 #120：热损失 / 需冷却带走的损耗。DHTS Word 标题印大纲号 `6.8.4 Heat loss 热损失`（读文件曾丢掉，见 `2026-09-08-word-outline-number-and-toc-page`）。未印号的 Markdown 片段条款应空，不得写成 6.8.3。
- 清单 #71：冷却回路压降。上一节 `### Coolant pressure drop 冷却回路压降`，35kPa@10L/min@65℃。`_HEADING_CLAUSE` 只把该标题映成 6.8.3。
- 交叉 `2026-09-07-ripple-lv-unnumbered-headings`、`2026-09-07-shown-in-hv-safety-is-not-back-emf-clause`：未印号分节不得抄上一节号。

## 闸门

- `_UNNUMBERED_PEI_HEADING` 含 `Heat loss` / `热损失`。
- `_pick_clause`：字段是热损失且摘录不是压降标题时，清掉映照来的 `6.8.3`。
- 回归：同段压降格条款仍为 6.8.3；热损失 6.17kW、条款空。
