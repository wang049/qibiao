# 2026-09-07 #109 要填 IPXXB，不要把「无 HVIL」写成有互锁

- 状态：active
- 条目：#109 高压连接器保护；#116 主动保险功能
- 闸门：`electrical/tests/test_extract_quality.py`（`test_ipxxb_fills_connector_not_negative_hvil`、`test_pss_fills_active_fuse`、`test_hvdc_peak_power_is_not_connector_protection`）；`electrical/extract.py` 正向 `add()` IPXXB/PSS，HVIL 遇「无机械互锁」不填

## 代价

#109 漏掉高压连接器 IPXXB/防直触（螺栓连接可视为满足），却可能把「PCM 无机械互锁 HVIL」扫成「支持 HVIL」。HVDC 270kW 峰值仍不得进本格。#116 漏掉两相铜排 PSS 主动点爆。

## 反事实

不写 IPXXB 正向规则、不排除否定 HVIL，下次仍会：触指防护空着，或把「无互锁」标成有互锁；PSS 需求节有主动点爆也不进 #116。

## 二级依据

- 清单 gloss：#109 是高压连接器防直接接触（IPXXB / 触指）；排除防水 IP、过压、HVDC 功率。交叉 `2026-09-07-109-hvdc-peak-is-not-connector-protection`。
- SuperEvo：`电驱系统高压连接器：…IPXXB…螺栓连接，可判定满足防直触`；`PCM 无机械互锁HVDC HVIL电路`；`PSS（Power Safety Switch）…主动点爆`。
- #116 清单名「主动保险功能」，对应 PSS / 烟火点爆，不是电池熔断叙述 alone。

## 闸门

- `add("高压连接器保护")`：高压连接器 + IPXXB + 防直触。
- HVIL：上下文含「无机械互锁 / without machine of HVIL」不 `add()`。
- `add("主动保险功能")`：PSS + 主动点爆；`_value_fits_field("主动保险")`。
- 回归：该段 #109 含 IPXXB 且不含「支持 HVIL」；#116 含 PSS/主动点爆；HVDC 125kW 仍不得进 #109。
