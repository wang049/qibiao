# 2026-09-07 #109 高压直流功率不是连接器触指防护

- 状态：active
- 条目：#109 高压连接器保护
- 闸门：`electrical/tests/test_extract_quality.py`（`test_hvdc_peak_power_is_not_connector_protection`、`test_expert_marked_fields`）；`electrical/extract.py` `_value_fits_field` 拒 `125kW`/`62.5kW`，`6.2.3.2` 功率句不再 `add()`

## 代价

第二版把 `6.2.3.2 High Voltage DC connection` 的 `10s@125kW@320V-450V`、`62.5kW@320V` 填进 #109，标已检索到。专家第一版已判这组功率不是 P1（#28/#30 错误），又判 #109 错误。

## 反事实

不把 HVDC 峰值/持续功率从 #109 拿掉，下次仍会把母线连接能力当成触指防护，并把专家已作废的 125kW/62.5kW 写进连接器保护。

## 二级依据

- 清单 gloss：#109 是高压连接器防直接接触（IPXXB / 触指防护）；排除防水 IP 与过压。
- 专家格子：#109 人工填写「错误」，备注「条款 6.2.3.2 正确」——条款指向对，抽出值不能是那组功率。
- 原文：`6.2.3.2` 是高压直流连接能力；`HVDC peak power` / `HVDC continuous power` 不是触指防护。

## 闸门

- `_value_fits_field("高压连接器保护")`：抽出值含 kW/峰值功率则拒；IPXX / 触指 / 防直触可过；仅「高压直流连接」标题则局部对应。HVIL 勾选不够。逆变器 SR 见 `2026-09-07-inverter-sr-cap-ripple-not-bus`。
- `6.2.3.2` 的功率数字不写入抽出值；条款与「高压直流连接」仍要挂上，标局部对应。见 `2026-09-08-109-clause-6232-must-still-extract`。
- 正向：高压连接器 IPXXB/防直触应填（并压过 6.2.3.2 连接标题）；「无机械互锁 HVIL」不得写成支持 HVIL。见 `2026-09-07-ipxxb-not-negative-hvil`。
- 回归：该段原文时 #109 不得出现 125kW，不得标已检索到。

