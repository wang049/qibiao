# 2026-09-09 适用标准栏不重复「不提供抽出值」

- 状态：active
- 条目：知识库条款卡片「适用标准」
- 闸门：`tests/test_knowledge.py`（`test_enterprise_std_is_method_not_fill`）；`scripts/publish_knowledge.py` `_apply_enterprise_std`

## 代价

企标对照写进 `std` 时，每条后面都挂「评价看当份 DPR，不提供抽出值」。知识库页已有「禁止用库填数」，卡片上标准号被这句话挡住。

## 反事实

不把这句从适用标准芯片拿掉，下次条款卡仍会把总口径复制到每条标准号后面，对表的人看不清 7.5→030001-24。

## 二级依据

- 知识库页顶栏已有「抽出值只来自当份规格书」和「禁止用库填数」。
- 「适用标准」只回答对照哪份方法标准。`fill: false` 仍在企标卡片和发布产物里。

## 闸门

- `_apply_enterprise_std` 写入的 `std` 为 `Q/JLP 030602-07-2026A 6.3→…`，不含「不提供抽出值」「评价看当份」。
- `browse_catalog` 耐电压 #14 的 `std` 同样不含这两句。
