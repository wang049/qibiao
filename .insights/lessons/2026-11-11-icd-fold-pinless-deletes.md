# 2026-11-11 没有引脚号的成批删除收成一段

- 状态：active
- 条目：ICD 出表
- 闸门：`tests/test_icd.py`（`test_pinless_signal_deletes_share_one_list`、`test_repeated_note_collapses_and_blank_pin_delete_is_hidden`）

## 代价

上一版有信号、当版整行没有的脚，每条信号占一行删除。低压连接器上 Chassis、PROP、Engine、LIN 会排成十几行红条，内容都是「无引脚号 / 引脚 / 信号名 / （空）」。

## 反事实

不把同一张表里这类删除收成一段，下一份差异仍是一只信号一行。有引脚号的删除若被一起收进去，`PIN9` 这类对得上的脚会从单独一行里消失。只有一条时若也收成「1只」，`Chassis_CAN1_H` 不再单独出现。

## 二级依据

- 同一张表、字段是引脚、没有引脚号、上一版信号名不同、当版为空，是同一类删除。
- 两只及以上收成「N只」，信号名写在上一版，当版写（空）。满 16 只后续写「续」。有引脚号的删除仍单独一行。只有一条时不收。
- 小结按信号名计数，不按空的引脚号算成 1。

## 闸门

`test_pinless_signal_deletes_share_one_list`：三条无脚号删除只有一段，上一版含三个信号名，对象是「3只」。`PIN9` 仍单独出现。小结写「删除 4」。
`test_repeated_note_collapses_and_blank_pin_delete_is_hidden`：只有一条 `Chassis_CAN1_H` 时仍单独列出。
