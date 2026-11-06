# 2026-11-04 原理图 PDF 认符号上的脚和球号

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_schematic_ball_stays_on_the_same_row`、`test_schematic_analog_pins_are_kept`、`test_schematic_pdf_reads_pin_and_ball_on_the_symbol`、`test_schematic_symbol_functions_fill_later_sheets`）

## 代价

EDIF 网表只有接插件脚和网络名。原理图 PDF 上 MCU 符号写着 `P14_0/ASCLIN0_ATX` 和球号 `E19`，不出进端口表。把整页文字按顺序硬拼，会把旁边另一只脚的球号配错。

## 反事实

只收 `.edf` 时，下一次上传 `DHT160-OF` 原理图 PDF 仍被拒绝。若只抽文字不看位置，`P14_0` 会对上邻近的 `D18` 而不是 `E19`。只认 `P` 开头时，`AN36/P40_6` 和单独的 `AN0` 不进端口表。清掉模板明细后不按符号上的功能回填，`3_ADC Table`、SPI 和 CAN 仍只有表头。

## 二级依据

- 确认口径：按原理图 PDF 识图生成 HSI。认符号上的引脚、球号和写在符号上的功能。`AN36/P40_6` 的引脚符号是 `AN36`，复用是 `P40.6`。只写 `AN0` 的也是一只脚。符号上的 QSPI、CAN、EVADC/TMADC 写入后面的 SPI、CAN、ADC 表。符号上没有转换器名时，`Gr` 和 `channel` 按同一型号手册里该球号的复用填写。方向、缓冲、PMIC 和死区时间符号上没有，不补。
- 球号文字比引脚高约 2.6 pt，左右不超过 50 pt。一个球号只配一只脚。`P31.5` 对 `AF13`，`P31.6` 对 `AE13`。取绝对最近会配到下一行，`P14.0` 会落到 `D18`。位号 `PIU…` 缺字时也会把相邻两只脚配成同一个球。
- 项目网络名如 `IA_S/M_TM` 在另一页，没有和这只脚连在同一处，不写入 Pin Definition。方向、完整复用表不从这张图猜。

## 闸门

`test_schematic_analog_pins_are_kept`：`AN36/P40_6` 的符号是 `AN36`，复用是 `P40.6`，球号是 `K20`。`AN62/P41_7/NC` 的复用是 `P41.7`。`AN0` 和 `AN56/NC` 也进表，功能留空。
`test_schematic_pdf_reads_pin_and_ball_on_the_symbol`：`P14.0` 的球号是 `E19`，复用是 `ASCLIN0_ATX`，Function 为空。`P24.0` 的球号是 `L25`，标记说明写未标功能。标题带从图上认出的 `TC499`，封装表头不再是 `BGA436`。
`test_schematic_symbol_functions_fill_later_sheets`：`EVADC_G9CH11` 进 ADC 表并标组 `G9`。`QSPI2_TXD` 进 SPI 表。`CAN10_TXD` 进 CAN 表。`GPIO` 不进这三张表。SPI 的 I/O 留空。
