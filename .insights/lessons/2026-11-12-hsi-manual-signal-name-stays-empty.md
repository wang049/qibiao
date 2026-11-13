# 2026-11-12 无原理图时信号名留空，复用列出可选项

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py` `test_dhte400_keeps_atom_port_name_cover_and_history`

## 代价

没有原理图时，Pin Definition 写成「手册推荐：PWM；第一条复用」。这一列是信号名，看起来像已经选定。复用列里其实已经有全部可配置信号。

## 反事实

继续把分类和第一条复用写进 Pin Definition，下一份手册出表的信号名仍是一句推荐，工程师分不清这是待选还是已定。ADC 的 Signal name 列继续按表头删除；时间常数的单位列不改成信号名。

## 二级依据

- 会议：无原理图先认型号、数总脚数，再按电源、ADC、PWM、GPIO 分类，并列出可配置信号供选择。信号名留空。仅手册时删掉 ADC 里标题为 Signal name 的列。
- DHTE400 `3_ADC Table`：F4、X4 是 `Signal name`，L4 是时间常数的 `「Unit]`。有原理图时信号名改成引用端口表，改端口名后各页跟着变。L 列不写网络名。

## 闸门

`test_dhte400_keeps_atom_port_name_cover_and_history`：AN0、P02.1 的 Pin Definition 为空，也没有跳转。功能列是 ADC、PWM，复用列仍有 ATOM1。符号格（AN0）仍跳到 ADC 那一行。空的信号名不挂链接，否则再次打开时落点名称会被写进这一格。
