# 2026-11-03 原理图封面不显示模板修改说明

- 状态：superseded
- 取代：`.insights/lessons/2026-11-10-hsi-schematic-archive-keeps-template.md`
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_schematic_lists_unconnected_connector_pin_and_clears_template_pages`）

## 代价

按原理图生成的封面仍显示模板「需要修改内容」，例如「修改 K 和 L 列对应原理图的网络名」「按照模板更改」。这些说明被看成这次出表的要求。

## 反事实

E 列继续留着模板修改说明，下一份原理图封面仍像 DHTE400 的工作清单。目录如果一并清掉，工作簿里实际存在的表名也看不到。

## 二级依据

- 确认口径：按原理图生成时，「需要修改内容」不显示。封面目录保留，因为那些表还在工作簿里。
- `HSI--20261103.xlsx` 封面 E 列来自模板 `DHTE400-HSI-V1.3-20261023.xlsx`。EDF 里没有封面，也没有这些修改说明。
- 按 MCU 型号新建仍保留封面修改说明。`test_dhte400_keeps_atom_port_name_cover_and_history` 仍检查第 4 行第 5 列含「原理图」。

## 闸门

`test_schematic_lists_unconnected_connector_pin_and_clears_template_pages`：「需要修改内容」表头和「修改K和L列对应原理图的网络名」为空；目录「硬件版本识别」还在。
