# 2026-11-12 抽出值不能超出这条原文摘录

- 状态：active
- 条目：#3 设计范围是否包含驱动升压功能、#13 高压安全-绝缘电阻、#44 P3峰值扭矩/时间/对应转速范围、#69 控制器重量
- 闸门：`electrical/tests/test_extract_quality.py`（`test_boost_control_alone_does_not_claim_a_platform_variant`、`test_ground_resistance_is_not_insulation`、`test_page_banner_leaves_the_excerpt_and_unsupported_number_is_partial`、`test_p3_peak_torque_keeps_duration_and_speed`、`test_clipped_boost_excerpt_keeps_both_sentences`）

## 代价

4LDHT 扫描件第 3 条在摘录只有 boost control 时仍写成「按 BOOST 架构做平台变型」。第 13 条把接地电阻 10mΩ 写成绝缘电阻。第 44 条只留下 400Nm，同一行的 10s 和 0–6500rpm 没进抽出值。第 69 条抽出值是 14.9 kg，摘录却是重量优化那句，前面还带着 Document Type 页眉。核对表用浅蓝、橙、黄，和页面上的绿、琥珀、红不是同一套。

## 反事实

只要出现 boost control 就写上平台变型，下一份没有 BOOST architecture 的扫描页仍会多出这句话。接地电阻的 mΩ 继续能通过绝缘电阻的判断，第 13 条仍是 10mΩ。峰值扭矩只收 Nm，时间和转速范围继续空着。页眉留在摘录里、数不在摘录里仍标已检索到，工程师对着格子对不上原页。

## 二级依据

- 当份 4LDHT 扫描件第 44 页有 `boost control`。`variants tailored to the BOOST architecture` 在下一句；这一句没进摘录时，抽出值不能写平台变型。两句都在时，摘录仍要从 `PCM is the control unit` 收到 architecture 那句。
- 第 32 页 4.2 写的是导电外壳两点之间接地电阻不大于 10mΩ。这不是绝缘电阻。
- 第 24 页同一行是 `P3 peak torque (@600A@10s@640V Nm 400Nm @0-6500rpm`。
- 第 22 页重量优化句没有 14.9。摘录里没有这个数时，不能标已检索到。

## 闸门

`test_boost_control_alone_does_not_claim_a_platform_variant`：只有 boost control 时，抽出值不含「平台变型」。
`test_clipped_boost_excerpt_keeps_both_sentences`：两句都在时，摘录仍含 architecture。
`test_ground_resistance_is_not_insulation`：接地电阻 10mΩ 不写入绝缘电阻，状态为未检索到。
`test_p3_peak_torque_keeps_duration_and_speed`：抽出值含 400Nm、10s、6500rpm。
`test_page_banner_leaves_the_excerpt_and_unsupported_number_is_partial`：页眉从摘录去掉；14.9 不在摘录里时为局部对应。
