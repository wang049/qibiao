# 2026-09-07 PCM HVAC 按当份安培数；EMC 认整机电气属性句

- 状态：active
- 条目：#90 相电流采样精度；#76 EMC等级；#102 防腐要求
- 闸门：`electrical/tests/test_extract_quality.py`（`test_pcm_hvac_uses_800_and_1200_not_xcm_600`、`test_emc_from_transmission_body_not_catalog`、`test_anticorrosion_keeps_l1_f3_not_xcm_heading`）；`electrical/extract.py` `_hvac_phase_accuracy_value`、EMC 正文加分、L1-F3 不被 XCM F3 标题盖掉

## 代价

对照 DHTS160 时，SuperEvo 原文已有 P1 −800A~+800A、P3 −1200A~+1200A 和「电气属性均须满足 J7110922D / J7110779E」，核对表却空着；防腐格写成「XCM 满足 F3」。规则把 DHTS 的 600A/XCM 句式和「The unit shall meet」当成唯一写法。

## 反事实

不按当份安培解析、不给「电气属性均须满足 / EMC测试要求」加分、L1-F3 仍被零件防腐标题盖成 XCM F3，下次 SuperEvo 仍漏 #90/#76，#102 过满成别的产品名。

## 二级依据

- 清单 #90：相电流采样精度，要量程 + ±%。SuperEvo `HVAC Current measurements`：P1 800A、P3 1200A。DHTS 才是 P1 600A、P3 300A。
- 清单 #76：EMC 等级。SuperEvo 正文「变速器整机及相关电器零部件的电气属性均须满足…J7110922D-2024，…J7110779E-2023」，不是文首标准目录表。DHTS 才有 `The unit shall meet Q/JLY J7110922D` 与 2.3.3.3.1。
- SuperEvo 防腐：`PCM … L1-F3`，不是 DHTS 的「XCM 满足 F3」。
- 交叉：DHTS `升压器的目标输出电压 450V` 仍是 #67；`_value_fits_field` 不得只认 SuperEvo 的 480/1056。

## 闸门

- HVAC 从原文解析 P1/P3 峰值安培，禁止写死 600/300。
- J7110922D 命中：目录表行减分；「电气属性均须满足 / EMC测试要求」加分。仅目录表不入库。
- 已写入 L1-F3 时，不再用零件防腐标题覆盖成 XCM F3。
- DHTS 450V 升压器目标输出仍认 #67（`test_dhts_booster_450_is_boost_output_voltage`）。
