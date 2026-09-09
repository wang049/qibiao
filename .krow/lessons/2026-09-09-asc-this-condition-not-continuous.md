# 2026-09-09 「在此条件下」是电机 ASC 稳态，不是下一节持续相电流

- 状态：active
- 条目：#40 P1 ASC电流能力；#42 P1逆变器交流主动短路电流；#43 P1逆变器持续交流电流
- 闸门：`electrical/tests/test_extract_quality.py`（`test_p1_asc_does_not_take_continuous_200`）；`electrical/extract.py` `_p1_asc_section_span` / `_p1_asc_inverter_amps` / `_value_fits_field`

## 代价

DHTS `6.5.7.1` 写 P1 电磁稳态 250Arms，「P1逆变器应能在此条件下工作3.5秒」；同段还有 830A@1ms 短时峰值。紧接着 `6.5.7.2` 才是持续相电流 200Arms。规则在整段里找「逆变器/PEI + 数字」，把 200 当成逆变器 ASC，#40/#42 抽出值写成 200Arms，摘录却是电机 250 + 此条件。

## 反事实

不把 ASC 窗口截到 `6.5.7.2` / `AC current continuous`、不让「在此条件下 / under this condition」跟电机稳态、不拒持续值与 `@1ms` 峰值进逆变器 ASC 格，下次仍会把 200Arms 持续电流写入 #40/#42。不得用清单示例 250A/3.5s、830A/1ms 顶替当份未写出的数。

## 二级依据

- 当份 `6.5.7.1`：P1 EM / P1电磁最大允许稳态 250A rms；PEI P1 / P1逆变器在此条件下 3.5s；短时峰值 830A@1ms。
- 当份 `6.5.7.2`：PEI P1 continuous AC phase current 200Arms / 逆变器P1 交流相电流 200Arms持续值 → #43。
- 清单 #40：稳态+瞬态成对；#42 单一 Arms；#43 持续相电流。交叉 `2026-09-09-expert-miss-asc-temp-hv-clause`（电机与逆变器分列，不是把下一节持续值当成逆变器 ASC）。

## 闸门

- `_p1_asc_section_span`：从 6.5.7.1 / 主动短路截到 6.5.7.2。
- 「在此条件下」且无单独逆变器安培句 → 逆变器格 = 电机稳态。
- 「在250Arms条件下」且电机 253 → 仍分列（253 进备注）。
- 持续值 / `@1ms` / transient peak 不进 #42；当份写出的 830@1ms 只进 #40 瞬态半句。
