# 2026-09-20 清单外有对照时摘录用中文句

- 状态：active
- 条目：清单外
- 闸门：`electrical/tests/test_extract_quality.py::OffListRequirementTests.test_off_list_names_come_from_spec_chinese`；`electrical/extract.py::_off_list_zh_twin` / `_prefer_off_list_excerpt`

## 代价

DHTS160 2026-09-20 15:57 清单外：名称已是「微控制器单元」「开发CAN总线」「每个I/O」「涂镀层外观」，抽出值也是中文，原文摘录仍是先扫到的英文 shall。对照中文句被 `seen_extra` 挡掉，摘录对不上名称语种。

## 反事实

对照句只换名称和抽出值、摘录仍贴英文、合并时再把中英两句拼进摘录，下次「原文摘录」仍会大段英文，复核的人看不到规格书里那句中文。

## 二级依据

名称、抽出值、原文摘录都只来自当份原文。有英中对照时三列都用后随中文句；没有中文对照的英文规格书保持英文。禁止另译，也不把中英两句拼成一条摘录。

## 闸门

对照稿「微控制器单元 / 开发CAN总线 / 每个I/O / 屏蔽终端」的 excerpt 必须含对应中文句，不得含 `The MCU shall` / `The development CAN` / `Each I/O shall` / `Shield termination`。纯英文稿 excerpt 保持 `The MCU shall`。
