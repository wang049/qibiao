# 2026-11-12 原理图归档保留模板里的空页

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_revise_hsi_from_schematic_keeps_unmatched_rows`）

## 代价

上一份归档把第 4 行起没有字的页整页删掉。`HSI--20261112.xlsx` 只剩封面、变更记录、端口、ADC、SPI、CAN，硬件版本、PMIC、死区、油温、热泵都不在了。

## 反事实

这些页再被删掉，下一份原理图归档仍对不上 TC499 模板的目录。封面写着热泵、油温，表里却没有对应页。

## 二级依据

- 确认口径：原理图没写到的页留着，不因为空就删。盖住文字的图挪到右侧，见 `2026-11-12-hsi-move-picture-beside-text.md`。
- 本次 `HSI--20261112.xlsx` 只有 6 页。模板 `TC499-HSI.xlsx` 有 29 页，其中包括 `5_PMIC-TLF4D985`、`7_Dead Time`、`17_变速器油温`、`18_热泵温度传感器`。

## 闸门

`test_revise_hsi_from_schematic_keeps_unmatched_rows`：归档后 `18_热泵温度传感器` 还在，页上的图还在。
