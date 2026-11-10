# 2026-11-10 出表加匹配栏和版本号，ICD 差异用颜色标

- 状态：active
- 条目：ICD 出表、CE BOM 出表、HSI 出表
- 闸门：`tests/test_icd.py`（`test_previous_file_marks_add_remove_and_change`）、`tests/test_ce_bom.py`（`test_ad_bom_type_maps_to_chinese_name`）、`tests/test_hsi.py`（`test_schematic_lists_unconnected_connector_pin_and_clears_template_pages`、`test_dhte400_keeps_atom_port_name_cover_and_history`）

## 代价

差异表只有文字时，新增、删除和变更混在一起。列宽按固定值时，长信号名被截断。重出以后变更记录仍停在模板的 v1.3，看不出这一次是哪一版。

## 反事实

下一次 ICD 差异行不上色，或列宽不随字数变。引脚清单没有「匹配」和「版本」。CE BOM 供应商表没有「匹配」和「出表版本」。按手册重出的 HSI 变更记录仍只有 v1.3，没有本次时间戳。原理图归档若清掉模板 v1.3，会把上一份项目的版本号当成没发生过。

## 二级依据

- 确认口径：每份输出另加一栏，写这次输入和输出对上了多少。每次重出注明版本号。ICD 比对上一版和最新版，用颜色标出差别，列宽随内容撑开，其余保持原表格式。
- 新增为绿、删除为红、变更为黄。匹配栏写已对上的项和未对上的项。3 级结构件的尺寸记「待手填」，不算没对上。
- 手册出表和原理图归档都保留封面修改人和 v1.3，并在下一空行写下本次版本。

## 闸门

`test_previous_file_marks_add_remove_and_change`：差异表有新增、删除、变更，三色分别以 C6EFCE、FFC7CE、FFE699 结尾；版本差异表头有「匹配」和「版本」。
`test_dhte400_keeps_atom_port_name_cover_and_history`：变更记录第 5 行仍是 v1.3，第 6 行是本次时间戳，说明含「芯片手册」。
`test_schematic_lists_unconnected_connector_pin_and_clears_template_pages`：模板 v1.3 留在第 2 行，下一行是本次时间戳，说明含「未对上」。封面修改人保留。
