# 2026-09-08 #68 升压输出功率禁止电压区间 kW 范围

- 状态：active
- 条目：#68 升压输出功率
- 闸门：`electrical/tests/test_extract_quality.py`（`test_charging_table_not_drive_or_bus`、`test_expert_marked_fields`、`test_boost_power_writes_kw_point_not_range`）；`electrical/extract.py` `_fmt_vi_at` / `_fmt_p_ui_at` / `_parse_boost_power_vi`
- 接续：点值 kW 见 `2026-09-09-boost-power-writes-kw-point`

## 代价

#68 由 P=UI 推算时写成「峰值 64–180 kW（400A×160–450V）」区间，核对时看不清最大电压、最大电流和持续时间，还把 Bypass 持续电流混进升压。

## 反事实

不禁止把电压区间乘电流展开成一串 kW，下次仍会写成 64–180 kW，现场无法对表；也不得用清单示例 125kW@320-450V 顶替当份电流/电压。点值 kW 要写，见接续篇。

## 二级依据

- 清单 gloss：#68 升压模式输出功率能力（峰值/持续）；物理关系 `P=UI` 只代入当份已出现的量。
- DHTS Boost 表：输入峰值电流与持续电流、升压至输出电压上限同份出现时，按峰值/持续分行。交叉 `2026-09-07-charge-boost-table-fills-ripple`（充电表 #68 仍填）。

## 闸门

- `_fmt_vi_at`：`{V}V×{A}A@{t}`；缺时长不加 @。抽出值在此基础上写点值 kW。
- 推算格不得写电压区间展开的 kW 范围；持续电流只用 Boost 列，不用 Bypass。
- 回归：充电表保留 `400V×250A@50min` / `720V×250A@30min`；DHTS 含 `450V×400A@10s` 与 195A，不含 160–450 区间、不含 64–180 kW。
