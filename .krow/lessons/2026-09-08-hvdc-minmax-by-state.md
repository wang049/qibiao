# 2026-09-08 #5/#6/#7 抽出值按状态写最低最高

- 状态：active
- 条目：#5 直流工作电压范围；#6 满功率(电流)工作电压；#7 降额工作电压范围
- 闸门：`electrical/tests/test_extract_quality.py`（`test_hvdc_reads_boost_column`、`test_hvdc_rows_not_glued_numbers`、`test_hvdc_range_beats_pcm_busbar`）；`electrical/extract.py` `_fmt_hvdc_state_lines`

## 代价

HVDC 电压表抽出值写成「冷启动160V；性能限制最低非升压200V/升压160V；满功率…」一串，核对时看不清每种状态的最低、最高。

## 反事实

不改成「1.状态最低：xxx  最高：xxx」分行，下次仍会把冷启动/满功率/限制性能和升压列糊成一句，现场对表对不上。不得用清单示例 160~500V 顶替当份表值。

## 二级依据

- 清单 gloss：#5 含冷启动/全性能/极限；#6 满功率/满电流不降额区间；#7 可工作但降额区间。
- DHTS 高压范围表：冷启动 160/160、满功率 340/160～450/450、限制性能 200/160～500/500。交叉 `2026-09-07-hvdc-range-is-not-protection-clause`。

## 闸门

- `_fmt_hvdc_state_lines`：`1.冷启动最低：…  最高：…` 换行 `2.满功率…`。缺值写「未给出」，不编造最高。
- `_is_junk_value` 不得把 `1.冷启动最低：` 当成条目编号垃圾丢掉。
- 两列时最低/最高内保留「非升压 / 升压」；#6 另列满电流。
- 回归：DHTS 第 5 条以 `1.冷启动最低：` 开头，含 160；第 6 条有满功率与满电流；第 7 条 `1.限制性能最低：`。
- `test_hvdc_range_beats_pcm_busbar` 经 `_store_cell` 后 #5 仍含冷启动，不得为空。
