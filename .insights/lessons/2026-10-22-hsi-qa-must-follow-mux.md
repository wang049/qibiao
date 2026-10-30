# 2026-10-22 质检不能否定手册里已经写出的复用

- 状态：active
- 条目：HSI 端口表
- 闸门：`tests/test_hsi.py`（`test_llm_conflict_that_denies_the_manual_mux_is_dropped`、`test_supply_stuck_to_a_function_name_goes_back_to_the_buffer`、`test_excerpt_drops_reserved_and_port_sheet_can_be_filtered`）

## 代价

`HSI-TC499-BGA436-1-20261022.xlsx` 里 15 行标成约束冲突，原因写成手册没有 SPI 主发或没有输出，同一格复用却已经有 `QSPI3_SLSO6 Master slave select output`、`QSPI5_SLSO1` 或 `GTM_TOUT`。`P22.5` 写成「无 CAN13_RXDC 接收能力，仅支持 CAN13_RXDC」，复用里就是 `CAN13_RXDC`。模型只看到复用前 300 字，主发项在后面，结论仍被写成冲突。

`P15.12` 的功能名是 `GTM_TIM2_IN3_6 VDDEXTH`，供电名粘在信号名上，下一行说明被拆成另一条复用。原文摘录和复用把一串 `Reserved` 铺进格子，列宽约 16、行高 16.5、没有换行。筛选停在 `A1:S326`，页码、原文摘录、核对状态、标记说明、人工修改不在筛选里。`C1` 的「返回首页」没有链到封面。

## 反事实

不丢掉和当份复用矛盾的模型结论，下次仍会把已经写出的主发、输出或具体信号标成「手册不具备」。不把粘在信号名后的 `VDDEXTH` 一类供电拆回缓冲，功能列仍会带上供电名。不从摘录和复用里拿掉 Reserved、不换行、不把筛选扩到人工修改、不给「返回首页」加封面链接，这几列打开后仍然读不全、筛不到。

## 二级依据

- 生成稿 `2_Port Assignment` 第 13 行 `P00.8`，复用含 `QSPI3_SLSO6 Master slave select output`，标记为「无SPI主发能力」。
- 同表第 158 行 `P22.5`，复用含 `CAN13_RXDC CAN receive input node 3`，标记为「无CAN13_RXDC接收能力，仅支持CAN13_RXDC」。
- 同表第 128 行 `P15.12`，复用以 `GTM_TIM2_IN3_6 VDDEXTH` 开头，并另有 `QSPI5_SLSO1 Master slave select output`，标记为「手册mux无输出能力」。
- 同表筛选范围为 `A1:S326`，`C1` 为「返回首页」且没有超链接。摘录列 `U` 宽约 16。
