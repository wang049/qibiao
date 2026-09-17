# 2026-09-11 #68 升压输出功率要写峰值功率与持续稳定功率

- 状态：active
- 条目：#68 升压输出功率（核对表序号 64）
- 闸门：`electrical/tests/test_extract_quality.py`（`test_boost_power_writes_kw_point_not_range`、`test_expert_marked_fields`、`test_charging_table_not_drive_or_bus`）；`electrical/extract.py` `_fmt_vi_at` / `_fmt_p_ui_at` / `_parse_boost_power_vi`

## 代价

DHTS160 核对表序号 64 已按 P=UI 写出 180kW / 87.75kW，但标签只写「峰值」「持续」，括注只写 `450V×400A@10s`，看不出是最大电压×最大电流、还是最大电压×持续电流。

## 反事实

不把标签改成峰值功率 / 持续稳定功率、括注不写最大电压与最大/持续电流，下次仍要口头解释哪一行是峰值、哪一行用了持续电流。也不得把电压区间展开成 64–180 kW，不得把 Bypass 200A 算进持续功率，不得用清单示例 125kW@320-450V 顶替当份。

## 二级依据

- 用户核对表 `DHTS160_DPR_2026年09月11日15：42：35.xlsx` 序号 64：建议分别给出峰值功率（最大电压×最大电流，并标注时间）和持续稳定功率（最大电压×持续电流）。
- DHTS Boost 表：目标输出 450V；峰值 400A@10s → 180kW；持续 Boost:195A → 87.75kW。交叉 `2026-09-09-boost-power-writes-kw-point`、`2026-09-08-boost-power-as-vmax-imax-time`。

## 闸门

- `_fmt_p_ui_at`：峰值 `180kW（最大电压450V×最大电流400A@10s）`；持续 `87.75kW（最大电压450V×持续电流195A）`。
- 抽出值两行标签为「峰值功率」「持续稳定功率」。
- 充电表仍写点值 kW，括注最大电压×最大电流@时长；不含 64–180 区间、不含 Bypass 200A。
