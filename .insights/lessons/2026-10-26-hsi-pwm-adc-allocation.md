# 2026-10-26 P1 PWM 与三相电流的分配规则

- 状态：active
- 条目：HSI IO 分配
- 闸门：`tests/test_hsi.py`（`test_p1_pwm_must_share_one_atom_and_complementary_bridge`、`test_phase_currents_must_share_a_channel_across_groups`）

## 代价

P1 的六路 PWM 若散落在不同 ATOM，或同一相上桥、下桥不是同一通道的互补输出，出表仍标成待人工确认。三相电流若落在同一 group 或不同 channel，也看不出来。

## 反事实

不按手册复用核对 ATOM 和 DTM，下一次 P1 上桥 ATOM1 CH1、下桥 ATOM2 CH3 仍不会标成约束冲突。不按 ADC 表核对 group 和 channel，三相电流挤在同一 group 的不同 channel 时，表上仍像已经配好。手册复用只有 TOUT、没有 ATOM 时若也标冲突，会把手册没写的通道说成已经违反规则。

## 二级依据

- 规则：P1 的 PWM 配置在同一个 ATOM；同一相上桥、下桥为同一通道的互补输出，例如上桥 `GTM0_ATOM1_CH1→CDTM1 DTM4_1`，下桥 `GTM0_ATOM1_CH1→CDTM1 DTM4_1N`。
- 规则：三相电流配置在不同 group 的同一个 channel。
- 吉利模板 `3_ADC Table`：P1 为 Gr2/Gr3/Gr4 的 Ch1（IA `P00.11`、IB `AN29`、IC `P31.1`）；P3 为 Gr0/Gr1/Gr5 的 Ch0（IA `AN0`、IB `AN4`、IC `AN8`）。备份电流不计入这三相。
- 吉利模板端口名：`PWM_AH_P1` 至 `PWM_CL_P1` 为 P1 发波。

## 闸门

`test_p1_pwm_must_share_one_atom_and_complementary_bridge`：ATOM 或通道或 DTM 互补对不上时标在对应引脚；按示例配好，或手册只有 TOUT 时不标。
`test_phase_currents_must_share_a_channel_across_groups`：吉利模板的三相电流不标冲突；同一 group 且 channel 不一致时标冲突。
