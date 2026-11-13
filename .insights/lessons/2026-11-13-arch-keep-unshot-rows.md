# 2026-11-13 截不到图的需求仍留下

- 状态：active
- 条目：电驱需求拆解
- 闸门：`tests/test_arch_contrast.py`（`test_unshot_row_stays_and_category_is_marked_as_a_suggestion`、`test_blank_page_is_named_and_not_filled_from_another_page`、`test_quantity_missing_from_the_page_stays_blank`）

## 代价

定位不到或斜章挡住时，整条需求被从需求清单拿掉。没有文字的页也不写进「未能读取」，看起来像没这一页。

## 反事实

不把截不到图的条目留在清单里，下次被斜章挡住的行会再次整条消失。挡住的图仍不放回格子。空白页或读失败的页若不记页码，就会被静默丢掉，也不能用其他页的字补上。数值若不在当页，不能另写一个数。

## 二级依据

- `.insights/lessons/2026-10-23-arch-skip-stamped-shots.md`：斜章盖住的截图不放进表，原文摘录不因截图被丢掉而删除。
- 同一条闸门：没有单独截图位置的条目，备注写「未能截图」和页码，需求清单里没有嵌入图片。
