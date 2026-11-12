# 2026-11-12 文件名里的扫描件 DPR 仍按电控 DPR 抽

- 状态：active
- 条目：SOR 出表
- 闸门：`electrical/tests/test_doc_kind.py`（`test_scanned_4ldht_filename_is_still_dpr`）

## 代价

`4LDHT260_DPR(扫描件).pdf` 选中后标成「非电控规格」，并写「未识别为电控规格书。不按 120 项电控清单硬抽。」扫描只是没有文字层，文件本身是 DPR。

## 反事实

下划线后面的 `DPR` 仍不认，下一份 `4LDHT260_DPR(扫描件)` 在正文还没 OCR 时继续被标成非电控，出表不会按电控清单抽。

## 二级依据

- 确认口径：文件名写了 DPR 或 4LDHT，就是电控 DPR。扫描件另标需要本机 OCR，不改成非电控。
- 本次选中文件：`4LDHT260_DPR(扫描件).pdf`，110 页，8.2 MB。

## 闸门

`test_scanned_4ldht_filename_is_still_dpr`：空正文时类型是电控 DPR，要抽取，说明里没有「不按」。
