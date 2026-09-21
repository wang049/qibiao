# 2026-09-20 清单外补前期硬件缺口

- 状态：active
- 条目：清单外
- 闸门：`electrical/tests/test_extract_quality.py::OffListRequirementTests.test_off_list_keeps_early_design_hardware_extras`；`electrical/extract.py::_OFF_LIST_USEFUL` / `_off_list_overrides_template`

## 代价

前期名单只到材料、MCU 位宽、开发 CAN、冷却承压、NVH。规格书写了 Flash/SRAM/主频、JTAG/SWD、乙二醇浓度、透气阀、爬电/间隙 mm、接地电阻 mΩ 时，要么被主表别名（#95 电机类型、#110 冷却接口）吞掉，要么当普通 shall 丢掉。

## 反事实

不把这六类按「当份有可核对数字或物理口」收进名单、不把带 mm 的爬电/带 % 的乙二醇从主表误认里放出来，下次仍会漏选型要用的存储、调试口、冷却介质和绝缘尺寸，或把无 mm 的 2.5 kV 爬电套话、绝缘电阻 MΩ 填进清单外。

## 二级依据

1–120 已覆盖绝缘电阻（MΩ）、耐压 kV、冷却流量/温度/接口、电机类型。清单外只补当份原文里的：MCU 存储/主频、调试或刷写物理口、冷却液浓度（不是 #111/#112）、壳体透气/泄压、爬电与电气间隙 mm、接地点或接地电阻 mΩ。抽出值只来自当份原句。

## 闸门

MCU闪存 `不小于2 MB`、SRAM `不小于512 KB`、主频 `为160 MHz`、调试口 JTAG/SWD、冷却液介质 `50%的乙二醇`、透气阀、爬电 `不小于8 mm`、电气间隙 `不小于4 mm`、接地电阻 `不大于10 mΩ`、接地点 `2个` 进 extra。绝缘电阻 48 MΩ、冷却回路 -40℃、爬电 2.5 kV、software flashed、pitch 不进。
