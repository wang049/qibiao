# 2026-09-20 清单外名称整页一种语种

- 状态：superseded
- 由：2026-09-20-off-list-name-from-spec.md 取代（中文名必须是当份原词，禁止词表翻译）
- 条目：清单外
- 闸门：`electrical/tests/test_extract_quality.py::OffListRequirementTests.test_off_list_names_one_language_per_sheet`；`electrical/extract.py::_unify_off_list_names`

## 代价

DHTS160 2026-09-20 15:21 清单外：回料/涂镀是中文，development CAN bus、MCU、Each I/O、Shield termination 是英文；屏蔽终端中英各占一行。名称两种语种并排，不像一份材料的固定条目名。

## 反事实

不按「当份有中文条目则整页名称用中文、纯英文规格书保持英文」统一、不把 MCU / development CAN / I/O / 屏蔽终端中英行并到中文名，下次仍会同一页中英名称混排，或中英各写一行。

## 二级依据

名称来自当份材料的固定条目名，不是句子语种各写各的。有中英对照固定中文；英文规格书固定英文。抽出值仍只来自当份原句，不翻译答案。

## 闸门

中英对照稿：名称均含汉字；MCU→微控制器，development CAN bus→开发CAN总线；屏蔽终端中英合并一行。纯英文稿：名称保持 MCU、development CAN bus。
