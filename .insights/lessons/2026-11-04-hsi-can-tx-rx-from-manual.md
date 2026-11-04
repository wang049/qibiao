# 2026-11-04 CAN 表列出手册里的收发脚

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_can_rows_follow_manual_tx_rx`）

## 代价

`6_CAN` 清掉模板后是空的。手册里的 `CAN10_TXD`、`CAN10_RXDA` 只出现在端口表复用列。把模板网络名 `CANTX_M/T-DB` 或「动力CAN」写回去，会把上一份项目的总线分配当成这次手册的结果。

## 反事实

CAN 表继续只留空表头时，下一次 `P14.0` 的 `CAN10_TXD` 仍要到端口表里翻。若把 `CANTX_M/T-DB` 和「XCP CAN」写入 Net Name、Fuction Des，下一份表仍是 DHTE400 的项目分配。

## 二级依据

- 确认口径：6_CAN 里的收发脚要梳理出来。网络名和中文说明是项目分配，手册里没有。
- TC499 手册：`CAN10_TXD O5 CAN transmit output node 0`；`CAN10_RXDA CAN receive input node 0`。还有 `CANXL00_TXD`、`CANXL00_RXDG`。没有 `CAN0_NODE1_TXD` 这种模板名。
- 模板 `6_CAN` 第 38 行起是 `2. CAN模块TXD/RDX`，第 39 行 `P14.0`、`CAN0_NODE1_TXD`、`CANTX_M/T-DB`、`XCP CAN(调试)`。这些网络名和中文不写入。

## 闸门

`test_can_rows_follow_manual_tx_rx`：`P14.0` 的功能是 `CAN10_TXD` 和 `CAN10_RXDA`，I/O 为 `Output` 和 `Input`。Net Name 为空。Fuction Des 引用端口表名称，不含「XCP」「动力CAN」。只有 QSPI 的 `P00.8` 不进这张表。功能列宽至少 18，标题合并在 `A1:F1`，`CAN10_TXD` 不被截成 `CAN10_T`。
