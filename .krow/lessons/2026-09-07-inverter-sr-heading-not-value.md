# 2026-09-07 逆变器 SR：检查表勾选/表头不是抽出值

- 状态：active
- 条目：#14/#19 高压安全-耐电压；#35 P1最高工作转速；#52 P3最高工作转速
- 闸门：`electrical/tests/test_extract_quality.py`（`InverterSrFixTests.test_partner_proposal_and_rpm_heading_are_not_values`）；`electrical/extract.py` `_value_fits_field` / `_is_junk_value`

## 代价

闸掉电容纹波/HVIL 后再跑 `Inverter SR from Outside`，模型把检查表 `Dielectric strength @60sec Vac Partner proposal √` 标成耐电压已检索到，把表头 `Maximum allowable RPM` 标成 P1/P3 最高转速。都没有试验电压或转速数字。

## 反事实

不拒 Partner proposal 勾选、不要求转速格带 4–5 位数字，下次逆变器 SR 仍会把「合作方提案」和「允许最高转速」表头抬成已检索到。

## 二级依据

- 清单 gloss：#14/#19 要耐电压试验电压或 GB/T 18488/击穿判据，不是 60 秒介电勾选；#35/#52 要最高工作转速定义（rpm 数字或转速表），交叉 `2026-09-07-poles-rpm-is-not-max-speed`。
- 当份检查表：`Dielectric strength @60sec | Vac | Partner proposal √`；`Maximum allowable RPM` 无数字。

## 闸门

- `_value_fits_field("耐电压")`：`Partner proposal` 且无 Vac/18488/击穿 → 拒；`has_test` 不再把单独 `@60sec` 当试验条件。
- `_value_fits_field("最高工作转速")`：必须有 `\d{4,5}`。
- `_is_junk_value`：`Maximum allowable RPM`；耐电压格的无电压 Partner proposal。
- 回归：该检查表/表头片段不得入库 #14/#19/#35/#52。
