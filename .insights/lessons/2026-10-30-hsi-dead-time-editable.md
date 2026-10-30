# 2026-10-30 死区时间可以改，图跟着变

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi_dead_time.py`（`test_dead_time_value_drives_the_sentence_and_the_figure`）

## 代价

`7_Dead Time` 上的死区是一张写死 `1.6μs` 的图。要求文字和图上的数各写各的，改一处另一处不会变。

## 反事实

仍把 `1.6μs` 画进图片，下一次把死区改成别的数，图上的标注还是 1.6。上面两行要求如果仍是纯文字，和图也互不影响。标注锚点超出本列宽度时，左右两个时间会叠在左边。波形如果用过大的自定义路径坐标，右半边会断开。

## 二级依据

- `DHTE400` 的 `7_Dead Time`：`Dead time of PWM-H and PWM-L shall be set 1.6μs`，`Add Short Pulse Inhibition Time: 1.6μs`。
- 原图是上框 `PWM_H`、中线向两侧伸出、下沿两侧各留一段死区，死区处标 `1.6us`。
- 死区时间只取这一页已有的数。图按这个形状重画。左右两处标注都指向死区时间这一格。窄脉冲抑制单独一格，只改第二行要求。

## 闸门

`test_dead_time_value_drives_the_sentence_and_the_figure`：初始为 1.6，要求行是引用 `J7`、`J8` 的公式，图上有 `PWM_H`、`PWM_L`，两处标注链接 `$AA$7`。把 `J7` 改成 2.5 后再写回，2.5 还在，图的标注变成 `2.5μs`。两处标注都在同一组图形里，不再用超出单元格的锚点，波形不用 custGeom。
