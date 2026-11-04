# 2026-11-04 原理图 PDF 认符号上的脚和球号

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_schematic_ball_stays_on_the_same_row`、`test_schematic_pdf_reads_pin_and_ball_on_the_symbol`）

## 代价

EDIF 网表只有接插件脚和网络名。原理图 PDF 上 MCU 符号写着 `P14_0/ASCLIN0_ATX` 和球号 `E19`，不出进端口表。把整页文字按顺序硬拼，会把旁边另一只脚的球号配错。

## 反事实

只收 `.edf` 时，下一次上传 `DHT160-OF` 原理图 PDF 仍被拒绝。若只抽文字不看位置，`P14_0` 会对上邻近的 `D18` 而不是 `E19`。

## 二级依据

- 确认口径：按原理图 PDF 识图生成 HSI。认符号上的引脚、球号和写在符号上的功能。
- 球号文字比引脚高约 2.6 pt，左右不超过 50 pt。一个球号只配一只脚。`P31.5` 对 `AF13`，`P31.6` 对 `AE13`。取绝对最近会配到下一行，`P14.0` 会落到 `D18`。位号 `PIU…` 缺字时也会把相邻两只脚配成同一个球。
- 项目网络名如 `IA_S/M_TM` 在另一页，没有和这只脚连在同一处，不写入 Pin Definition。方向、完整复用表不从这张图猜。

## 闸门

`test_schematic_pdf_reads_pin_and_ball_on_the_symbol`：`P14.0` 的球号是 `E19`，复用是 `ASCLIN0_ATX`，Function 为空。`P24.0` 的球号是 `L25`，标记说明写未标功能。标题带从图上认出的 `TC499`，封装表头不再是 `BGA436`。
