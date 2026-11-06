# 2026-11-03 标准 CE BOM 先核对必填，不补数

- 状态：active
- 条目：CE BOM 出表
- 闸门：`tests/test_ce_bom.py`（`test_standard_sheet_keeps_structure_formulas_and_existing_numbers`、`test_cover_plate_missing_thickness_is_recorded_not_filled`、`test_required_fields_follow_electronic_and_structure`）

## 代价

序号、级别、零件中文名称、用量已经确认为必填，盖板的材料厚度为空也要能看见。标准表若仍只写「填写规则未到」，这些空格不会出现在核验记录里。

## 反事实

不核对必填，下一次标准表里没有序号、用量的零件行仍显示为通过。盖板没有材料厚度时也不记一笔。结构件缺产品尺寸、净重、原材料时也不记。若据此把厚度或净重写进格子，就会在密度和图纸都还没有的时候造数。电子件也被按结构件去要尺寸和原材料。若把模板里的密封圈、铜排和净重公式留在供应商表，读入的零件会接在示例后面，表上的数不是这次输入的。若表头上的项目号、PSS 数字、供应商名称和标题还留着，输出里仍是模板项目的数据。若再另出 EDF器件、字段映射、核验记录，用量还在旁边的表上，供应商里看不到这次读到的行。若供应商只写用量，1046 这一行看不出是测试点还是电容。

## 二级依据

- 确认口径：序号、级别、零件中文名称、用量必填；零件号有则填；图片暂不管；产品尺寸电子件可不填、结构件必填；材料厚度仅盖板类必填；净重结构件必填，按体积×密度；原材料结构件必填。体积或密度未给定时不计算。电子件不按尺寸、净重、原材料判缺。
- AD 导出 BOM 的 Type 按 `CE BOM 器件中文名称对应规则示例_20261103.xlsx` 填零件中文名称。规则表没有的 Type 留空，不自造「电阻」「电容」。用量和 Manufacture PN 一并写入。级别、尺寸、厚度、净重、原材料不从 BOM 补。
- `AD 导出的BOM示例_20261103.xlsx` 有 196 行、23 种 Type。规则表只有芯片类。能对上的是 Boolean、Spower、COM、MCU、CMP、D Flip-Flop 等 19 行。Res 79 行、Cap 40 行没有对应中文名。
- 净重按体积×密度，这次没有给出密度。产品尺寸、原材料要区分电子件和结构件，标准表没有这一列。
- EDF 按类型、设计条目、值和封装归并后，用量写入供应商。Manufacture PN 写入零件号。Design Item ID 写入规格型号；没有则写 Value。封装不是产品尺寸。规则表没有的 Type，零件中文名称留空。不另出 EDF器件、字段映射、核验记录。

## 闸门

`test_standard_sheet_keeps_structure_formulas_and_existing_numbers`：模板里的密封圈、尺寸和净重公式被清除。标题、项目号、PSS 数字和供应商名称被清除，「项目」标签还在。手册里的 999 不写入。表头 X、Y、Z 还在。
`test_cover_plate_missing_thickness_is_recorded_not_filled`：模板里的上盖板被清除，不另写一个厚度。
`test_edf_counts_same_part_and_does_not_fill_the_standard_sheet`：两只相同电阻在供应商表记用量 2，零件号是 Manufacture PN，规格型号是 Design Item ID。电容用量 1，规格型号是 Value。零件中文名称和产品尺寸留空。工作簿只有供应商表。
`test_ad_bom_type_maps_to_chinese_name`：Type Cap 写成电容，MCU 写成微控制器，Res 留空。序号从 1 起。模板里的上盖板不保留。尺寸不写入。工作簿只有供应商表。
`test_required_fields_follow_electronic_and_structure`：电容不记缺产品尺寸、缺净重、缺原材料。PN包塑件记下这三项，净重写明不按体积×密度计算。盖板已有 31g 和原材料，不记缺净重、缺原材料；已有板料厚度，不记缺材料厚度。
