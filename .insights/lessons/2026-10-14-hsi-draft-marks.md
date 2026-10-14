# 2026-10-14 模板对照不能写成已确认

- 状态：active
- 条目：HSI 端口表
- 闸门：`tests/test_hsi.py`（`test_first_issue_drops_template_history_and_unmatched_names`、`test_multiple_names_are_not_reduced_to_one`、`test_opposite_direction_is_marked_and_not_confirmed`、`test_second_issue_records_only_the_difference`）

## 代价

符号能对上吉利模板时，端口名、电平和 ASIL 被直接写入初始配置表，表上没有缺项、多候选、约束冲突，也没有单独留下的人工修订。重新生成会把改过的端口名换回模板，验收格也没有地方保留实测值。

## 反事实

不对缺项、多候选和方向相反单独标状态，也不把人工修订、验收实测从生成列里分开，下次仍会：符号一对上就把模板端口名写成表内结论；同一符号有两个端口名时留下后一个；手册方向与模板方向相反时看不出来；重新生成盖掉人工修订和已填实测。

## 二级依据

- 标书：交付初始配置表、手册依据、约束配置、人工修订记录。缺项、多个候选、约束冲突要标记，不强行输出确认结论。验收记录保留匹配、降额、安全相关项的实测值。技术协议未规定匹配率、安全率的数值阈值。
- 吉利模板 `2_Port Assignment`：数据列 B 为引脚符号，J 为 Pin Definition(Himalaya)，L 为 Level，M 为 ASIL，H 为 Direction，取值为 Input、Output、Input/Output。同一符号只应在这些列有一条对照；对不上的符号不补端口名。
