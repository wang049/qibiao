# 2026-09-20 清单外收紧后不能空表

- 状态：active
- 条目：清单外
- 闸门：`electrical/tests/test_extract_quality.py::OffListRequirementTests.test_collects_unlisted_shall_not_template_or_process`（至少 3 条：追溯码、涂镀层、回料）；`_maps_to_template_field` 只认全名/长别名

## 代价

商务垃圾滤掉后 DHTS 清单外变成 0 行。整页 `_is_front_matter`、泛「电压」认主表、抽出值必须带单位数字，把涂镀层/回料/追溯码也滤没了。

## 反事实

不把认条收成条目全名和长别名、不允许「平整光滑 / 禁止回料 / 打印在…」这类短答案，下次收紧后又是空页，设计 SOR 仍看不到清单外指标。

## 二级依据

清单外要的是当份产品/工艺指标，不是商务交付。涂镀层外观、禁止回料、追溯码打印位置对不上 1–120，但能写成一条指标一个答案。There shall、3D 模型、下表规定仍不收。

## 闸门

收集结果至少含追溯码、涂镀层外观、回料；3D/There shall/Table below 仍为 None。
