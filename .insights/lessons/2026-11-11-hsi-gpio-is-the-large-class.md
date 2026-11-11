# 2026-11-11 通用口不要算进专用分类

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_dedicated_symbols_get_a_manual_class`）

## 代价

分类把复用里出现的 CAN、PWM、ADC 当成这只脚的类别。通用口 `P00.8` 只要复用里有 `ADC_TMADC2CH6` 就算 ADC。专用类会到一百多，GPIO 反而变少。

## 反事实

继续按复用关键词归类，下一份手册出表里 CAN、PWM、SPI 仍是大类。`General-purpose input` 且复用里有 `CAN0_TXD` 的脚仍不是 GPIO。功能本身写着 `CAN transmit output` 的脚若也改成 GPIO，真正的 CAN 脚就空了。

## 二级依据

- 会议口径：分类按模板里的电源、ADC 这些，种类不多。GPIO 是没有专用功能、由人自己选的通用口，数量最多。把太大的范围全算进一个专用类，会出现一百多个。
- 复用仍全部列在复用列，不据此改 J 列。符号 `AN` 仍是 ADC。电源、地仍按脚名。

## 闸门

`test_dedicated_symbols_get_a_manual_class`：`P00.8` 功能是 Port、复用含 ADC，分类是 GPIO。功能写 PWM 的 `P02.1` 仍是 PWM。`CAN transmit output` 是 CAN，功能只写 Port 的同一脚是 GPIO。
