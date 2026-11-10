# 2026-11-10 出表版本不能写进合并单元格

- 状态：active
- 条目：CE BOM 出表
- 闸门：`tests/test_ce_bom.py`（`test_issue_version_skips_merged_title_cells`）

## 代价

版本号写进表头上方时，真实模板第 4 行到第 13 行是合并单元格。往合并格里赋值会直接报错，壳体图出表变成 Internal Server Error。

## 反事实

下一次仍把「出表版本」写进合并区域的第一列，`3DHT200-CE BOM` 再出结构图会在同一处崩溃。只判断格子是空的、不判断它是不是合并格，空的合并格仍会被写。

## 二级依据

- 模板 `3DHT200-CE BOM-V2-20260730.xlsx`：第 1 行到第 3 行、第 5 行到第 13 行的 A 列在合并区域内。第 4 行 A 可写，B 是合并格。
- `DHT160OF-5501801758` 壳体图可以写出 3 行：壳体为 2 级，摩擦焊板和固化密封胶为 3 级。

## 闸门

`test_issue_version_skips_merged_title_cells`：A1:B3 和 A4:B13 合并后，版本写在可写的格子里，不抛出异常。
