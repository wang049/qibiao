# 2026-10-23 质检备注不写「须向客户确认」

- 状态：active
- 条目：电驱需求拆解
- 闸门：`tests/test_arch_qa.py`（`test_write_contrast_writes_qa_to_note_and_reqs`、`test_detects_cross_table_vo_range_and_shock_g_and_dual_max_output`）

## 代价

需求清单备注写成「须向客户确认」。这张表是交给甲方用的，读表的人就是甲方，这句话像在让别人再去问客户。

## 反事实

备注里留下「须向客户确认」，下次出表仍会在待定项和功率口径不一致的行上要求读者去问客户。

## 二级依据

- `架构对照-20261023-104033.xlsx` 需求清单 M 列，标红行备注为「【内容质检】原文含待定项（TBD/TBC），须向客户确认」和「同条最大输出功率口径不一：既写 2.5kW，又写 Max. output = 2.72kW，须向客户确认」。
- 确认说明写明本表供人工逐条确认，不写能否满足。状态列默认 To be confirmed。
