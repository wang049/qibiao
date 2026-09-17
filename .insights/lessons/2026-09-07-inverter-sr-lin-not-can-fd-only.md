# 2026-09-07 逆变器 SR：同句有 LIN 不得只留 CAN FD

- 状态：active
- 条目：#114 通讯方式
- 闸门：`electrical/tests/test_extract_quality.py`（`test_can_fd_with_lin_is_not_can_fd_only`）；`electrical/extract.py` `_lock_field_semantics`、裸 `CAN FD` `add()`、`CAN / CAN-FD / LIN` 摘录

## 代价

`Inverter SR from Outside` #114 抽出值写成 `CAN FD`，原文摘录却是 `The inverter must support CAN, CAN-FD, and LIN communication.` 条款 `3.3.6`（Software Requirements）对，取值漏 LIN。

## 反事实

不跳过同段 LIN 时的裸 CAN FD、不把「must support CAN, CAN-FD, and LIN」写成摘录、摘录扩句带上 LIN 后仍不改抽出值，下次仍会只留下 CAN FD。

## 二级依据

- 清单 #114：通讯方式，要当份写明的总线。逆变器 SR `3.3.6`：CAN、CAN-FD 和 LIN；LIN 还要求可作多从机 master。
- 交叉：规则注释已写「同段已有 LIN 时留给后面的 CAN/CAN-FD/LIN」，但后段 `add("CAN FD")` 未挡 LIN，摘录只取了 `CAN-FD` 四字。

## 闸门

- 同段有 `\bLIN\b` 时不再 `add("CAN FD")`。
- `CAN / CAN-FD / LIN` 的摘录用完整 support 句。
- `_copied_from_example`：清单示例是 `CAN / CAN FD / LIN / 以太网`，抽出值像示例但摘录已有 LIN 时不算抄模板。
- `_lock_field_semantics`：摘录已有 CAN-FD 与 LIN、抽出值没有 LIN → 改成 `CAN / CAN-FD / LIN`。
- 回归：含 Test Specification 与 support 句时，规则格和 `_store_cell` 后都含 LIN，不得为 `CAN FD`。
