# 2026-09-21 4LDHT 扫描件：持续电流、出功率/随转、额定转速、堵转水温

- 状态：active
- 条目：#39 P1逆变器持续交流电流；#31/#48 最高工作转速；#29/#46 额定转速；#107 冷却液温度范围；#106 冷却接口
- 闸门：`electrical/extract.py` `_value_fits_field`（额定转速拒 kW@转速、冷却液拒 `65℃`/堵转安全）；`_fmt_max_speed_power_overrun`；`PCM P1 持续电流` 认 `Arms@30min`；`_HEADING_LINE_CLAUSE` 认 `6.2.2Cooling`；`electrical/tests/test_extract_quality.py::SuperEvoQualityGateTests.test_4ldht_scan_20260921_must_fix_cells`、`test_glued_622_cooling_heading_not_guiding_pins`；`test_scan_ocr_4ldht_performance_stores` 增 16000/17000、拒 7500 额定转速

## 代价

`4LDHT260_DPR_扫描件_2026年09月21日11：16：45.xlsx`：#40 摘录已有 `210Arms@30min`，#39 仍空；#31 只写 `17000rpm`（随转在前），漏 `16000（出电功率）`；#29 把 `70kW@7500rpm` 抬成已检索到的额定转速，#46 对同一写法空着；#107 用堵转考核点 `65℃` 顶冷却液温度范围；#106 条款抄定位销 `6.2.1.5`（正文是 `6.2.2Cooling connections`）。

## 反事实

- 不放宽 `Continuous Current` 正则：OCR 写成 `PCM P1 Continuous Current Arms 210Arms@30min` 或中文「持续电流」时仍漏 #39。
- 只按数字出现顺序收最高转速：随转写在出功率前面时，#31 继续只剩 17000。
- 继续用规则把 `kW@7500rpm` 填进 #29：与 #46 待专家口径打架，下次仍把功率行转速当额定转速定义。
- `_value_fits_field` 只拒 `65 °C` 不拒 `65℃`、只认「堵转策略」不认「堵转安全」：#107 继续过满。
- 行首条款号必须空格：`6.2.2Cooling` 认不出，冷却接口继续挂 6.2.1.5。

## 二级依据

- 4LDHT 2.3.2 电流表：`PCM P1 Continuous Current / 持续电流 210Arms@30min` 与峰值 `350Arms@10s` 分行。
- 同表转速行：`16000（出电功率）` 与 `17000（随转）` 是两种工况，不是一个数。
- `docs/knowledge/pending_rulings.json` `p3-rated-speed-from-power-point`：额定功率点上的转速不算正式额定转速，未定稿前空着。
- 冷却液温度范围认全范围 / 正常范围行，不认堵转或压降考核点的单一 65℃。
- 冷却连接标题是 6.2.2；6.2.1.5 是定位销。交叉 `2026-09-07-no-printed-652-no-external-5310`。

## 闸门

- `_value_fits_field("P1 额定转速", "7500rpm", "70kW@7500rpm")` 为 False。
- `_value_fits_field("冷却液温度范围", "65℃", "Stall Safety 堵转安全 @65℃冷却水温")` 为 False。
- 11:16 扫描件片段：#39 含 210Arms@30min；#31/#48 出功率与随转成对；#29、#107 不填；`6.2.2Cooling` 条款为 6.2.2。
