# 2026-11-03 原理图出表只写接插件网络

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_revise_hsi_from_schematic_keeps_unmatched_rows`、`test_schematic_lists_unconnected_connector_pin_and_clears_template_pages`）

## 代价

按原理图出表时，端口名抄了网络名，没进网的接插件脚被丢掉，ADC 等页仍显示 DHTE400 的信号名和公式。

## 反事实

继续把网络名写入 Pin Definition，下一份原理图表仍分不出网络和端口名。只收网上有的脚，`J402M.37` 这类未入网的脚仍不会出现。不清后面各页，`IA_S/M_TM` 和转换公式还在。

## 二级依据

- 确认口径：原理图出表一行一个接插件脚，网络名只写网络列。端口名空着。后面各页只留表头。
- `DHT160OF_PU_B3V2.EDF` 是功率板网表，没有 TC499。`J401M`、`J402M` 封装各 52 脚，`J601M` 6 脚，`J501M` 2 脚。未入网的是 `J402M.37`、`J402M.38`、`J501M.1`。
- 芯片的 400 多个脚不在这份网表里，仍由手册出表。

## 闸门

`test_revise_hsi_from_schematic_keeps_unmatched_rows`：网络名在第 11 列，第 12 列端口名为空。
`test_schematic_lists_unconnected_connector_pin_and_clears_template_pages`：`J501.1` 无网络并注明未进入任何网络，`J501.2` 网络为 `SIG`；ADC 表头保留，第 5 行信号名和公式为空；网络列不隐藏。
