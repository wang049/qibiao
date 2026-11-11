# 2026-11-11 原理图归档也让死区 μs 可以改

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi_dead_time.py`（`test_schematic_archive_makes_dead_time_editable`、`test_dead_time_value_drives_the_sentence_and_the_figure`）

## 代价

按原理图归档只改端口和后面的网络名。`7_Dead Time` 仍是模板里写死的 `1.6μs`。改要求文字或改图上的数，另一处不会跟着变。

## 反事实

原理图归档不调用死区页处理，下一份 `C4` 仍是纯文字 `1.6μs`，`J7` 没有可改的数。要求已经是引用 `J7` 的公式时若再写成纯文字，改 `J7` 不再带动这句话。没有死区句子的表若被改写，空的 `7_Dead Time` 会被加上 `1.6`。

## 二级依据

- 手册出表已经把死区时间放在 `J7`、`J8`，要求行和时序图引用这两格。原理图归档保留这张表，同一套改法也要加上。
- 数从这一页已有的句子或格子读取，不另取一个默认值。没有死区句子和数字时不动这张表。
- 改 `J7` 后，`C4` 和两处图注显示同一个 μs。窄脉冲抑制用 `J8`。

## 闸门

`test_schematic_archive_makes_dead_time_editable`：原理图归档后 `J7` 为 `1.6`，`K7` 为 `μs`，`C4`、`C5` 引用 `J7`、`J8`，图上有 `1.6μs`。
`test_dead_time_value_drives_the_sentence_and_the_figure`：把 `J7` 改成 `2.5` 后，图注变成 `2.5μs`。
