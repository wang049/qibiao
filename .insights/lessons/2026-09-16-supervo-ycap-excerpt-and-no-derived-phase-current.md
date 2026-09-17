# 2026-09-16 SuperEvo：Y 电容摘录要是原文片段；交流相电流不得由 P 与 Vdc 推算

- 状态：active
- 条目：#17 高压安全-Y电容指标（核对表 17）；#58 P3额定功率相电流（核对表 54）及其他交流电流条目 #43/#44/#42/#57/#59/#60
- 闸门：`electrical/extract.py` Y 电容规则摘录改为「标题句 … 表格单元」原文片段；`_looks_like_ocr_garbage` 只数贴字的 `&`；`_is_ac_phase_current_field` + `_derived_fits_field` 拒收交流电流推算值。`electrical/tests/test_extract_quality.py::SuperEvoQualityGateTests.test_supervo_ycap_table_stores_as_found` / `test_ac_phase_current_cannot_be_derived_from_dc_bus`

## 代价

`SuperEvo_1000V__DPR_2026年09月16日14：11：08.xlsx`：
- #17 Y电容「未检索到」，而 6.5.8 原文表格明确写 `Y+≤130nF & Y-≤130nF`（HVDC± 对地）。
- #54 P3额定功率相电流被模型算成 `86.6Arms`（I=P/(√3U)，P=120kW，U=800V），标局部对应。同表 P3 峰值 465Arms、P1 持续 200Arms，86.6 差一个量级，会把人带偏。
- 74 条已检索到里 73 条与仅规则相同；模型 11.5 分钟净贡献 = 1 个对的条款号 + 1 个错数 + 1 个错条款。

## 根因

1. Y 电容规则命中了 130nF，但把摘录拼成「Y-电容选择 Y+≤130nF」——不是原文连续片段，`_value_in_source` 按「值和摘录都对不上原文」判为编造丢弃。DHTS 的 660nF 表格写法 `PCM 660nF` 走另一条路径，所以从没暴露。
2. 摘录改成表格行后，`_looks_like_ocr_garbage` 数到 4 个 `&` 判为扫描花字，格子降成局部对应。规则原意是抓 `th#Hi#E&E` 这类贴着字母的 `&`，`130nF & Y-` 两边带空格是正常连接词。
3. 提示词允许 `I=P/(√3U)`，模型把直流母线 800V 当交流线电压代入。P=√3UI 要交流线电压有效值，还差功率因数和调制比，从功率和 Vdc 算不出相电流。`_derived_fits_field` 对相电流只查「有没有 A」，没查能不能算。

## 反事实

- 只放宽 `_value_in_source`：会同时放过真编造的值；应让规则给出真摘录。
- 把 `&` 从花字判定里整个拿掉：`Y&E&E&F` 这类扫描花字放行；只数贴字的 `&` 两头都保住（测试里两例都钉了）。
- 不拒相电流推算、只在备注写公式：现场看到 86.6Arms 仍会当成参考值。直流侧电流（BOOST 输入电流）由 P 与 Vdc 推算仍允许。
- 不得反过来用清单示例 `≤500nf` / `250Arms` 顶替当份。

## 二级依据

- SuperEvo 6.5.8：`The Y-capacitors of the PCM shall be less then the values below` + 表格 `Y+≤130nF & Y-≤130nF`；注「130nF 为目标值」。
- SuperEvo 2.3.2 指标表：P3 峰值 465Arms@10s、P1 持续 200Arms@30min；P3 额定驱动功率 120kW@800V 是直流侧功率与母线电压。
- 物理卡 `P=√3UI` 适用条件：交流线电压有效值；知识库 physics.yaml 该卡说明「同条款内已给出…」，未给交流电压不适用。
- 交叉 `2026-09-07-pcm-hvac-amps-not-xcm-600`（SuperEvo 按当份写法解析）、`2026-09-07-ocr-excerpt-note-is-concrete`（花字判定的原意）。

## 闸门

- 仅规则整份 SuperEvo：#17 已检索到 `Y+≤130nF、Y-≤130nF（HVDC±对地）`，条款 6.5.8，无花字备注；其余 115 行无变化。DHTS 仍 660nF、对黄金 115/116（#61 靠模型，预期）。
- `_derived_fits_field` 对 相电流/交流电流/ASC电流/堵转电流 一律 False；`BOOST输入额定电流` 推算仍 True；原文写明的 `250Arms持续` 走正常路径仍收。
- 撤掉 `_is_ac_phase_current_field` 测试即红（反事实已验）。
- 4LDHT260 扫描件仅规则修前修后逐格比对：零差异（该份规则路径本就没有花字降级格；花字判定的既有测试样本 `th#Hi#E&E I)#H#R#4E` 仍判花字）。
