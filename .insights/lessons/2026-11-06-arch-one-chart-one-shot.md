# 2026-11-06 同一页的多张曲线各截一张、各摘一张表

- 状态：active
- 条目：电驱需求拆解出表
- 闸门：`tests/test_arch_figures.py`（`test_any_document_splits_each_chart_from_its_own_table`、`test_outlined_condition_page_excerpts_the_sentences_and_the_table`）

## 代价

一页上的 8 阶、24 阶、48 阶噪声曲线被收成一张截图。三张表的转速和分贝写进同一张格子，横轴 `0、5000、10000、15000` 也成了一行。

## 反事实

同一页已经认出两张以上的曲线数据表时，若仍把曲线和这些表合成一张图再整页识成一张表，下次 `2500` 不会落在自己的那张图下面，`15000` 仍会变成表的最后一行。只截数据表、不带上它右侧那条曲线时，图标仍然是半张。曲线下缘停在照片上沿时，`[P1, P3 respectively]` 仍被裁掉；左缘越过自己的数据表时，旁边那张曲线的坐标会卷进来。图上已经画过的转速表若再按文字层写一遍，8 阶、24 阶、48 阶会各出现两次。标题先译一遍再交给模型，译文会叠成三四段。纯数字表仍写成摘录并翻译时，`0 / 10`、`2500 / 60` 仍会占行。图框从正文第一行起算、不识上方页眉时，`Attachment1` 这种标题仍会漏掉。同一段编号工况若按条拆成十几行，`Attachment1` 到 `④` 仍会各占一条。这一段要收成一行，格子里的换行跟原文一致。规格表若按整页截图把每一行撑高，`Load / Speed rate` 会比原表长出很多。表行只跟字高，截图缩进这些行里。页眉只在图框离页顶不到 110 点时才识，`Attachment2. Bench test target` 这种离曲线较远的标题仍会漏掉。文字层把 `Specifications` 拆成 `S` 和 `pecifications`、把 `8th/24th/48th` 拆成单行时，若先按坐标词删掉再拼接，这句仍是 `S pecifications`，阶次也没了。

## 二级依据

- 确认口径：`docs/knowledge/arch_kb.yaml` 卡片 `arch-chart-screenshot`。任何输入文件都按这一套。每张曲线连同它自己的数据表各成一张截图。纯数字数据表只留在截图里，不摘录、不翻译。图框上方的页眉标题、编号条款、曲线标题和说明按行摘录并翻译。一条编号条款的双语摘录写在同一行。不看文件名，也不限转速、噪声这两个词。横轴刻度不进表。规格表仍按原列画出。

## 闸门

`test_numbered_clause_excerpt_stays_on_one_line`：`① Bench test sweep rate` 的双语摘录不含换行，列宽够这一行，格子不折行。
`test_attachment_title_above_the_body_is_its_own_row`：第 2 页页眉 `Attachment2. Bench test target` 单独成行，不并进 `1. Specifications`。
`test_any_document_splits_each_chart_from_its_own_table`：表头是 `kW / Torque` 和 `Speed / Power` 时，仍拆成两张截图，纯数字表不写入摘录格子。
`test_outlined_condition_page_excerpts_the_sentences_and_the_table`：第 1 页摘出 `Attachment1` 和 `1. P1 Motor NVH TEST`。噪声页拆成 8 阶、24 阶、48 阶三张截图，纯数字表不进摘录。8 阶截图的右缘小于 520、下缘小于 350。48 阶截图的左缘大于 360。电机照片另成一张。
