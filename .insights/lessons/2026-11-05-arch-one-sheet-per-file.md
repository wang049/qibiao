# 2026-11-05 多份需求文件合成一本，每份一张表

- 状态：active
- 条目：电驱需求拆解出表
- 闸门：`tests/test_arch_contrast.py`（`test_write_contrast_puts_each_file_on_its_own_sheet`、`test_write_contrast_builds_sheets_and_lists_unreadable`）

## 代价

一次上传多份需求 PDF 时，条款都写进同一张「需求清单」，只能靠「文件」列区分。打开后要自己筛选才能看某一份。

## 反事实

继续把多份文件的条目叠在「需求清单」里，下一次 `260605_LDC_SR.pdf` 和 `BHDC.pdf` 仍在同一张表，REQ-ID 连着编。只上传一份时若也不再写「需求清单」，原来只看这一张表的核对会找不到表。

## 二级依据

- 确认口径：多份需求文件合成一本工作簿。确认说明仍是第一张。其后每个文件一张表，表名用文件名，版式与需求清单相同，REQ-ID 从各自的 001 起。只上传一份时仍是「确认说明」和「需求清单」。读不出文字的文件不另开表，写在确认说明里。

## 闸门

`test_write_contrast_puts_each_file_on_its_own_sheet`：两份文件的表名是 `260605_LDC_SR` 和 `BHDC_总成`，没有「需求清单」。两张表的第一条都是 `REQ-20261015-001`，行数相同。确认说明写明每个文件单独一张表。
`test_write_contrast_builds_sheets_and_lists_unreadable`：一份文件时仍是「确认说明」和「需求清单」。
