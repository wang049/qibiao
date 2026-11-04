# 2026-11-03 出表不把模板项目数据写成这次的结果

- 状态：superseded
- 被替代：`.insights/lessons/2026-11-04-hsi-fill-name-and-class.md`
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_dhte400_keeps_atom_port_name_cover_and_history`、`test_first_issue_drops_template_history_and_unmatched_names`）

## 代价

DHTE400 模板里的端口名、中文说明、ATOM/DTM，以及 ADC、热泵页上的信号名和公式，出现在生成稿里，看起来像这次手册和原理图算出来的。

## 反事实

对得上的引脚继续把 `IA_S/M_TM`、`PWM_M_AH_GM` 写入端口名格，下一份表仍会把上一份项目的名字当成这次的结果。ADC 数据行若只清中文列，信号名和转换公式还在。

## 二级依据

- 确认口径：看起来已经填上的格子，只保留这次手册和这次原理图写得出来的内容。模板对得上的名字记在标记说明，不当成这次的结果。
- 手册写得出来的是符号、球号、缓冲、上下拉、供电、复用、页码、原文摘录。上传网表再写网络名和外部电阻。
- DHTE400 端口表 L 列 `IA_S/M_TM`、M 列中文说明、G/H 列 ATOM/DTM 是模板原值。`3_ADC Table` 第 5 行信号名同样是模板原值。
- 封面和变更记录是文档壳，保留。端口名为空时不做跳转。名字填上之后，既有的按名称对表仍然可用。

## 闸门

`test_dhte400_keeps_atom_port_name_cover_and_history`：AN0、P02.1 的方向、功能、端口名、网络名、ATOM、DTM 为空；标记说明含「模板有端口名 IA_S/M_TM，待人工确认」和「模板有端口名 PWM_M_AH_GM，待人工确认」；复用列仍有手册里的 ATOM1；ADC 第 5 行信号名为空，表头还在；热泵表第 147 行空；封面和变更记录仍在。
`test_first_issue_drops_template_history_and_unmatched_names`：端口名格不写 `KEEP_ME`，标记说明写「模板有端口名 KEEP_ME，待人工确认」。
