# 2026-09-20 清单外名称和抽出值语种一致

- 状态：active
- 条目：清单外
- 闸门：`electrical/tests/test_extract_quality.py::OffListRequirementTests.test_off_list_name_and_value_same_language`；`electrical/extract.py::_off_list_lang` / `_split_off_list_item`

## 代价

DHTS160 2026-09-20 13:44 清单外第 16 行：英文标题 `Internal fault in HV` 配中文抽出值「导致元件内的连续故障」。`不应` 被拆成名称末尾「不」+「应」，名称作废后改用英文节标题。

## 反事实

不把「不应」当成情态、不禁止英文标题给中文句当名称、不拦名称与抽出值语种不一致，下次仍会一行里中英混用。

## 二级依据

清单外是一条指标一个答案，名称和抽出值都来自同一句当份原文。该句是中文则名称、抽出值都中文；该句是英文则都英文。标准号、MCU、CAN 可夹在中文句里，不单独改语种。

## 闸门

英文节标题 + 「内部故障不应导致连续故障」→ 名称「任何高压元件的内部故障」、抽出值以「不应」开头。收集结果中名称含汉字当且仅当抽出值含汉字。
