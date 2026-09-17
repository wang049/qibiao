# 2026-09-07 充电 Boost 表要填 #70/#67/#68，不要填母线纹波

- 状态：active
- 条目：#70 升压纹波电压；#67 升压输出电压；#68 升压输出功率；#23 备份电源功能
- 闸门：`electrical/tests/test_extract_quality.py`（`SuperEvoChargeMisbindTests.test_charging_table_not_drive_or_bus`、`test_connecting_kl30_is_not_backup_supply`）；`electrical/extract.py` Charging Buck/Boost 窗口内 `add()` 纹波/电压/功率；备份电源拒 Connecting/Disconnecting KL30

## 代价

旧口径故意不把充电 Boost 表写入 #70/#67/#68，SuperEvo 原文有桩侧≤1%、电池侧 20V/10V、满电流 480–1056V、250A/100kW@400V 却漏检。#23 把「连接/断开 KL30 不得激活输出」当成 KL30 丢失备用供电（当份其实另有 Back-up supply if KL30 is lost）。

## 反事实

不在 Charging Buck/Boost 块内正向填升压纹波/输出电压/输出功率，下次仍漏 #67/#68/#70；不拒 Connecting KL30，下次仍把 I/O 激活禁令写成备份电源。

## 二级依据

- 清单：#70 升压纹波、#67 升压输出电压、#68 升压输出功率，对应充电 Boost 表，不是直流母线纹波（#8/#12）。
- SuperEvo 充电表：纹波电压-桩侧 ≤1%；电池侧未接入 ≤20V、接入后 ≤10V；满电流高压侧 480V≤U≤1056V；充电功率 250A/100kW@400V 50min、250A/180kW@720V 30min。
- #23：`Back-up supply voltage if KL30 is lost` 才是备份电源；`Connecting the KL30 must not activate outputs` 不是。

## 闸门

- Charging Buck/Boost 窗口 `add()` #70/#67/#68；不得写入直流母线纹波、驱动升压、P3 相电流。
- `_value_fits_field("升压输出功率")` 须有升压/Charging Buck 语境，禁止单凭「充电功率」四字。
- `_value_fits_field("备份电源")` 拒 Connecting/Disconnecting KL30、gate driver 隔离电源；保留 KL30丢失备用电源电压。
- 回归：充电表片段填 #70/#67/#68 且不填母线纹波；Connecting KL30 不得进 #23。
