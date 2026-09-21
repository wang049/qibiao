# 2026-09-20 清单外中文名必须是当份原词

- 状态：active
- 条目：清单外
- 闸门：`electrical/tests/test_extract_quality.py::OffListRequirementTests.test_off_list_names_come_from_spec_chinese`；`electrical/extract.py::_off_list_zh_twin` / `_unify_off_list_names`

## 代价

曾把 MCU 译成「微控制器」、I/O 译成「输入输出」。规格书写的是「微控制器单元」「每个I/O」「开发CAN总线」「屏蔽终端」。乱译不是当份名称。

## 反事实

不从英中对照的中文句取主语、不用当份原词合并中英行，下次仍会自造译名，或英文名称与规格书中文对不上。

## 二级依据

抽出名称和抽出值都只来自当份原文。有中英对照时用中文句里已出现的主语；没有中文对照的英文规格书保持英文。禁止词表翻译。

## 闸门

对照稿名称=`微控制器单元` / `开发CAN总线` / `每个I/O` / `屏蔽终端`（各一行）。不得出现自造的「微控制器」「输入输出」。纯英文稿名称保持 MCU。
