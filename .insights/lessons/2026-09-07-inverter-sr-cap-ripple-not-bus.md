# 2026-09-07 逆变器 SR：电容纹波/HVIL 勾选不是清单值

- 状态：active
- 条目：#8 直流母线纹波电压要求；#12 高压安全-纹波电压；#13/#18 高压安全-绝缘电阻；#39 P1位置传感器；#109 高压连接器保护
- 闸门：`electrical/tests/test_extract_quality.py`（`InverterSrFixTests.test_emc_hv_ripple_and_hvil_tick_are_not_pcm_fields`、`test_inverter_table36_torque_altitude_not_cap_as_machine`）；`electrical/extract.py` 不再 `add()` `Voltage Ripple on HV 15Vpp` 和任意 `HVIL`/`Rotor position`

## 代价

`Inverter SR from Outside` 核对表 18 格「已检索到」里：#8 把电容/EMC 表 `Voltage Ripple on HV 15Vpp/30Vpp Region I` 当成整机母线纹波；#13/#18 把「Insulation resistance … shall meet the design specifications」标已检索到（没有 MΩ）；#39 把信号清单里的 Rotor position 写成「转子位置 / Resolver」；#109 把 `HVIL design compliance √` 写成「支持 HVIL」。清单 #109 是触指防护（IPXXB），不是互锁勾选。

## 反事实

不把 `Voltage Ripple on HV` 从母线纹波拿掉、不要求绝缘电阻带 MΩ、不收紧位置传感器/连接器，下次逆变器 SR 仍会：用电容 EMC 行填 #8、用「满足设计规格」填绝缘、用 CAN 信号名填 P1 旋变、用 HVIL 勾选填触指防护。

## 二级依据

- 清单 gloss：#8 是整机直流母线纹波（接通工况），不是 Region I 的 HV 纹波限值；#13/#18 要绝缘电阻值（MΩ），不是「符合设计规格」；#39 是位置传感器型式，不是信号列表里的词；#109 是 IPXXB/防直触，排除 HVIL 勾选与防水 IP。
- 当份 Table 3.9 / EMC 表：`Voltage Ripple on HV | 15Vpp/30Vpp | Region I` 与 DC capacitor 500Vdc 同区；`HVIL design compliance √` 是设计符合性勾选。
- 交叉：`2026-09-07-ipxxb-not-negative-hvil`（#109 要 IPXXB）；`2026-09-07-ripple-lv-unnumbered-headings`（#8/#12 按接通/断开分节）；表头/勾选见 `2026-09-07-inverter-sr-heading-not-value`。

## 闸门

- 逆变器规则不再把 `15Vpp/30Vpp`、任意 `HVIL`、`Rotor position|Position se` 写入对应格。
- `_value_fits_field`：母线纹波拒 `Voltage Ripple on HV`（无 Generated voltage ripple）；绝缘电阻必须有 MΩ/100M/20M，拒 `meet the design spec`；#109 只认 IPXX/触指，不认 HVIL；P1 位置传感器拒 HVIL/Main relay 信号清单上的 Resolver 别名。
- `_is_process_language`：`shall meet the design specifications`。
- 回归：该电容/EMC/勾选片段不得入库 #8/#12/#13/#39/#109。
