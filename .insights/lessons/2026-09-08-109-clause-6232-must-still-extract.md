# 2026-09-08 #109 条款 6.2.3.2 仍要抽出，只是不能填功率

- 状态：active
- 条目：#109 高压连接器保护
- 闸门：`electrical/tests/test_extract_quality.py`（`test_hvdc_peak_power_is_not_connector_protection`、`test_expert_marked_fields`、`test_ipxxb_wins_over_hvdc_connection_clause`）；`electrical/extract.py` `6.2.3.2` 填「高压直流连接」局部对应，抽出值拒 kW

## 代价

挡住 125kW/62.5kW 之后，`6.2.3.2` 整段 `pass`，DHTS #109 变成未检索到。专家格子写的是「条款 6.2.3.2 正确」，不是「这一格应空」。

## 反事实

不把 `6.2.3.2 High Voltage DC connection` 挂回 #109，下次仍会：条款正确的格子空着；或为了填满再把峰值/持续功率写进抽出值。

## 二级依据

- 专家：#109 人工填写「错误」，备注「条款 6.2.3.2 正确」——条款指向对，抽出值不能是 `10s@125kW@320V-450V` / `62.5kW@320V`。
- 当份 `6.2.3.2` 标题是高压直流连接，正文只写物理连接功率，没有 IPXXB/触指。
- 清单 gloss：#109 是触指防护。当份未写触指代号 → 局部对应「高压直流连接」，不得抬成已检索到。
- 交叉：`2026-09-07-109-hvdc-peak-is-not-connector-protection`、`2026-09-07-ipxxb-not-negative-hvil`。有 IPXXB 触指句时触指赢，且不得把 6.2.3.2 接到触指摘录上。

## 闸门

- `add("高压连接器保护")`：命中 `6.2.3.2 High Voltage DC connection` 时抽出值「高压直流连接」，`STATUS_PARTIAL`，条款 `6.2.3.2`。
- `_value_fits_field`：抽出值含 kW/峰值功率 → 拒；抽出值是「高压直流连接」且摘录可含功率句 → 过。
- 回归：该段 #109 有 6.2.3.2、有「高压直流连接」、无 125kW、不是已检索到。同段若有高压连接器 IPXXB，触指赢且条款不是 6.2.3.2。
