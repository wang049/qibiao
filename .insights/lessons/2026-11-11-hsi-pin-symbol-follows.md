# 2026-11-11 端口表的球号改了，后面的球号格跟着变

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_pin_symbol_column_follows_onto_later_sheets`）

## 代价

DHTE400 表头 C 列写着 Pin_Symbol，格子里是球号 `N7`。归档时这一列只做跳转，不写成引用。工程师改了 C 列，ADC 的 Ball# 仍是原来的字。

## 反事实

继续不引用球号格，下一份端口表把 `N7` 改成别的球号，`3_ADC Table` 的 Ball# 还是 `N7`。引脚符号 `P00.8` 在表头为 Ball 的 B 列，SPI 的 PIN 已经指向 B 列。

## 二级依据

- 会议口径：主要改端口表，后面各页跟着变，工程师打开归档文件直接改。
- 发布稿正文：B 列是 `P00.8`、`AN0`，C 列表头是 Pin_Symbol，格子是 `N7`、`W13`。ADC 的 Ball# 与 C 列相同。

## 闸门

`test_pin_symbol_column_follows_onto_later_sheets`：SPI 的 PIN 引用端口表 `B4`。ADC 的 Ball# 引用端口表 `C4`。
