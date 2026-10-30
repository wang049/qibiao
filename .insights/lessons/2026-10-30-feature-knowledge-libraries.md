# 2026-10-30 电驱和 HSI 各有对照库

- 状态：active
- 条目：知识库
- 闸门：`tests/test_knowledge.py`（`test_arch_and_hsi_libraries_do_not_supply_values`）

## 代价

电驱拆解和 HSI 出表如果去用电机控制器那 120 项的典型值，会把别的文件里的规格写进当份表。

## 反事实

不把这两份库和 SOR 选段分开，下一次检索仍可能把清单别名拿去填架构规格或引脚。库里如果写下死区时间或电阻值，出表就会拿库内的数填格。

## 二级依据

- 电驱核对已在用：同条中英数值一致；同文件重量不得超出该文件写明的上限；同文件输出电压范围、机械冲击加速度前后一致。封面和目录不参与。
- HSI 分配规则：同一电机 PWM 在同一个 ATOM；同一相上下桥共用通道且下桥为互补 N 输出；三相电流在不同 group 的同一 channel，备份不计入。手册没有 ATOM 时不标冲突。
- 功率板按接插件脚出表，不按 MCU 引脚符号去对。外部上拉下拉只认接到电源或地的电阻。

## 闸门

`test_arch_and_hsi_libraries_do_not_supply_values`：两份库 `fill_from_kb` 为 false，条目 `retrieve` 为 false。HSI 库正文不出现死区时间数字。未知库名返回空。
