# 2026-09-09 #68 升压输出功率要写出 P=UI 点值

- 状态：active
- 条目：#68 升压输出功率
- 闸门：`electrical/tests/test_extract_quality.py`（`test_boost_power_writes_kw_point_not_range`、`test_expert_marked_fields`、`test_charging_table_not_drive_or_bus`）；`electrical/extract.py` `_fmt_p_ui_at` / `_parse_boost_power_vi`

## 代价

#68 已按 P=UI 代入当份 450V、400A@10s、Boost 195A，抽出值却只写「450V×400A」，核对表上看不出 180kW / 87.75kW。旧口径为避免电压区间展开成 64–180 kW，连点值也不算了。

## 反事实

不把 Vmax×Imax 算成单一 kW 点值写进抽出值，下次仍只看到 V×I，或再写成「峰值 64–180 kW（400A×160–450V）」区间；也不得把 Bypass 200A 算进持续功率，不得用清单示例 125kW@320-450V 顶替当份。

## 二级依据

- 用户核对表 #68：备注已写 P=UI，抽出值应给出具体功率。清单 gloss：升压模式输出功率能力（峰值/持续）。
- DHTS Boost 表：目标输出 450V；峰值 400A@10s → 180kW；持续 Boost:195A → 87.75kW。交叉 `2026-09-08-boost-power-as-vmax-imax-time`（禁止电压区间 kW 范围仍有效）。

## 闸门

- `_fmt_p_ui_at`：`{kW}kW（{V}V×{A}A@{t}）`；DHTS 回归含 180kW、87.75kW 和 450V×400A@10s，不含 64、160、200A。
- 充电表写出与 P=UI 一致的 100kW / 180kW，并保留 400V×250A@50min、720V×250A@30min。
- 持续电流只用 Boost 列。
