# 2026-09-10 P1 峰值功率持续时间与峰值电流跟 2.3.2 表

- 状态：active
- 条目：#29 P1峰值功率持续时间（核对表序号 25）；#44 P1逆变器交流电流峰值（核对表序号 40）
- 闸门：`electrical/tests/test_extract_quality.py` `test_p1_peak_duration_and_current_keep_2_3_2`、`test_p1_peak_generate_wrap_keeps_duration`；`electrical/extract.py` `_duration_from_peak_power_hit` / P1 `peak current` 须 `PCM P1` 且认 `Arms`

## 代价

4LDHT260 印页 22–23，`2.3.2` 性能表：P1 时长写在 `P1 peak generate power@60℃@≥10s@350Arms … 140kW`，旧规则要「10s 出现在 P1 peak generate 之前同段」才收，整洁行收不到。P1 峰值电流印成 `350Arms@10s`，旧规则只认 `Ams`（中间不能有 r），跳过 350 去吃后面 P3 的 `600Ams@10s`，或整行没进规则。模型用无标题页片段补 `10s` / `350Arms@10s`，条款列空。

## 反事实

仍要求 10s 写在英文功率名前面、或不认 `Arms`、或 `PCM P[lI1]` 把 P3 当 P1，下次核对表 25/40 仍只有值没有条款，或 P1 电流写成 600。若为填满去套 DHTS 6.5.x，会串号。当份功率行没有时长、电流行没有 P1 峰值则留空，不得用清单示例 10s / 250Arms 填。

## 二级依据

- 当份 4LDHT260 扫描件印页 23：P1 峰值发电功率 140kW 与 `@≥10s` 同一行；印页 22：`PCM P1 peak current 350Arms@10s`。节标题 `2.3.2 P&E 动力经济性` 在表头。
- 交叉 `2026-09-10-p3-peak-power-duration-clause`（同表 P3 时长跟功率行）；`2026-09-10-table-rows-keep-section-clause`（同表已印 2.3.2，不发明目录号）。

## 闸门

- 从 **P1 peak generate power / 电机峰值发电功率** 行（含 OCR 折行）上的 `@10s` / `@≥10s` 收持续时间，不依赖「10s 必须写在英文名前面」。
- `PCM P1` / `PCMPl` / `PCMPI` 峰值电流认 `Arms` / `Ams`；同一段里的 P3 `600Ams@10s` 不得进 P1。
- 存格后条款与同表功率行一样走行首已印 `2.3.2`。
- 电流行 `Arms@10s` 不得当作 #29。
