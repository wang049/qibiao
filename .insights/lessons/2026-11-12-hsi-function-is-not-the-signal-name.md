# 2026-11-12 符号功能不写入信号名

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py` `test_symbol_function_stays_out_of_the_signal_name`

## 代价

TC499 底稿的 Pin Definition 是空的。原理图 PDF 只认出符号上的 `CAN10_TXD`、`GPIO`，归档却把这些功能写进信号名。ADC 的 Signal name 再引用这一列，打开就是功能名或空白。模板里原来的 `IA_S/M_TM` 若被空公式盖掉，归档不能直接用。

## 反事实

继续在没有导线网络名时用符号功能填 Pin Definition，下一份 `P00.0` 的信号名仍是 `CAN10_TXD`，复用列也是同一个字。信号名还空着时若把 ADC 的 Signal name 改成引用空格子，`IA_S/M_TM` 会从 ADC 页消失。

## 二级依据

- 会议：有原理图时不改的内容原样留下，只更新认得出的引脚配置。信号名来自导线上的网络名。符号上的可配置功能列在复用里，不当成已经选定的信号名。
- TC499-HSI.xlsx：`2_Port Assignment ` 第 4 行球号 `W13`、符号 `AN0`，Pin Definition 为空。`3_ADC Table` 的 Signal name 在改之前也是空的。

## 闸门

`test_symbol_function_stays_out_of_the_signal_name`：`P00.0` 的信号名仍空，复用是 `CAN10_TXD`。`P00.2` 的信号名仍空，复用是 `GPIO`。`AN0` 的 `IA_S/M_TM` 还在，ADC 信号名不出现 `CAN10_TXD`。
