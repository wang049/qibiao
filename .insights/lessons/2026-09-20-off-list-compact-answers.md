# 2026-09-20 清单外抽出值只留可核对答案

- 状态：active
- 条目：清单外
- 闸门：`electrical/tests/test_extract_quality.py::OffListRequirementTests.test_off_list_keeps_only_useful_product_items`；`electrical/extract.py::_off_list_compact_value` / `_OFF_LIST_NOT_USEFUL`

## 代价

14:32 表：NVH评级抽出值拖着英文半句；TOP-60cm噪声以「是在凸台…分析」开头；pitch 50 mm、OCPD +12V 进了前期清单外。

## 反事实

不把 NVH/噪声收到「8 级 / 不大于50dB(A)」、不把绞距和 OCPD 当废条目丢掉，下次抽出值仍是方法从句，布线细则再占格。

## 二级依据

清单外一条指标一个答案。NVH 前期看评级级数，噪声看 dB(A)。绞距、熔断器保护接地不是 XCM 前期最小化输入缺口。抽出值只来自当份原句中的那一段答案。

## 闸门

NVH评级抽出值=`8级`，不得含 The objective。TOP-60cm噪声抽出值=`不大于50dB(A)`，不得含凸台。pitch、OCPD 不进 extra。CARB 名称=`CARB诊断`。
