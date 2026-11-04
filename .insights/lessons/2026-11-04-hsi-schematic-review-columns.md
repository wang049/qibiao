# 2026-11-04 原理图端口表的核对列和重复网络

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_schematic_lists_unconnected_connector_pin_and_clears_template_pages`、`test_schematic_repeated_net_opens_the_same_index`）

## 代价

原理图端口表把脚号、网络名再写进标记说明。核对状态和标记说明落在筛选外面，列宽约 13，长句挤在一起。同一个网络有多只脚时，只能自己逐行找。

## 反事实

标记说明继续写「接插件 J101M.1；原理图网络 KL30」时，这两项仍和 B 列、K 列重复。标记说明仍停在 W 列默认宽度里。`GND` 出现在多只脚上时，点网络名仍然到不了其他脚。

## 二级依据

- 确认口径：原理图出表与手册出表同一套可读方式。已经写入格子的内容不在标记说明里再抄一遍。重复项可以跳转。端口名仍不抄网络名。
- 手册出表把核对状态、标记说明、人工修改放进表头，标记说明列宽 36 并换行，筛选盖到这些列。
- `HSI--20261104.xlsx` 的筛选原来只到 R 列，W 列宽 13。`GND` 有 51 只脚，`KL30` 有 3 只脚。

## 闸门

`test_schematic_lists_unconnected_connector_pin_and_clears_template_pages`：未入网的标记说明是「未进入任何网络；待人工复核」，不再写接插件脚号。有网络、没有电阻时不写「原理图网络」。表头有核对状态、标记说明、人工修改，标记说明列宽至少 36，筛选盖过 W 列。
`test_schematic_repeated_net_opens_the_same_index`：`J1.1` 和 `J1.2` 的 `GND` 进同一条跳转索引。`SIG` 只有一只脚，不加链接。端口名仍空。
