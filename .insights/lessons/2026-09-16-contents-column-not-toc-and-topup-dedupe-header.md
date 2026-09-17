# 2026-09-16 逆变器 SR：表头里的 CONTENTS 不是目录页；补抽判重要剥掉页眉

- 状态：active
- 条目：#67/#115 冷却回路压降（词典 71/119）；连带所有靠选段/补抽才能进模型的条目
- 闸门：`electrical/extract.py::_is_front_matter` 只认目录标题（独占一行的 Contents / Table of Contents / 目录 / Revision History）；`_topup_chunks` 判重键改为 `_fold_text(_strip_running_header(text))[:80]`。`electrical/tests/test_extract_quality.py::InverterSrFixTests.test_body_page_with_contents_column_is_not_front_matter` / `test_topup_dedupe_uses_stripped_header_key`

## 代价

`Inverter_SR_from_Outside_2026年09月16日15：02：04.xlsx`：892 s、34 次模型调用、0 段失败，已检索到 12 = 仅规则 12，模型净增 0 格。

- 第 65 页 Table 3.12 `COOLING PASS PRESSURE DROP < 300mbar, @12lpm @65℃` 是当份唯一的冷却压降值，#67/#115 漏；第 59 页 3.3.6 非功能要求页模型也没看到。
- 补抽 10 段全部是主抽已送过的页，10 次调用（约 5 分钟）白花。同日 4LDHT260 扫描件 35 次调用里也有同样的重复。

## 根因

1. `_is_front_matter` 在页首 900 字里见到 `contents` 就当目录页。逆变器 SR 的正文表头 `CATEGORY CONTENTS TARGET`（p65/p76/p77）和句子 `contents stated in ES/MS`（p59）都命中，整页从选段和补抽里剔除。99 页里 7 页被判目录，真目录只有 p2（Revision History）和 p3（`<Table of Contents>`）。
2. `_topup_chunks` 用「原始页开头 80 字」判重，但主抽送出的段经过 `_strip_running_header` 剥了页眉。每页带 `Writing Team … PAGE n/99` 页眉的文档，原始键永远不在已送文本里，判重形同没有。

## 反事实

- 把 `contents` 整个从目录判定里拿掉：DHTS/SuperEvo 的目录页靠 `目录` 与 `Requisite documents` 仍能判，但英文规格书只写 `Contents` 一行的会漏判；改成只认独占一行/Table of Contents 两头都保住（测试钉了 5 种写法）。
- 判重改用整段包含：多页拼段时逐页判 `in` 代价大且页眉差异仍会漏；对键做同样的剥离最省。
- 不能因此放松 `_value_fits_field`：`< 300mbar, @12lpm @65℃` 本就放行（单位提示 kPa / bar / mbar @ L/min @ ℃），漏是因为没送页、没问条目。
- 当份 Table 3.9 是 DC 电容器件规格（100MΩ、0.1mA 暗电流、10G 振动），仍按 `2026-09-07-inverter-sr-cap-ripple-not-bus` 不进 #13/#20/#71；本次出表没填它们是对的。

## 二级依据

- 当份 p65 `2) Inverter CAE Analysis Requirements … CATEGORY CONTENTS TARGET (*May vary depending on vehicle measurement) … COOLING PASS PRESSURE DROP < 300mbar, @12lpm @65℃ … Table 3.12`。
- 当份 p3 `<Table of Contents> 1. Overview 2. System Requirements …`；p2 `Revision History`。
- deepseek-v4-pro 对含 p65 的段实测返回 `seq 71/119 冷却回路压降 = < 300mbar, @12lpm @65℃`，条款 3.3.7，`_store_cell` 正常入库。
- 交叉 `2026-09-16-select-chunks-by-gap-and-split-retry`（选段按空缺找页）、`2026-09-16-prompt-lists-field-by-strong-alias-ratio`（选到的页也要问到条目）。

## 闸门

- 四份文档目录页判定修前→修后：Inverter SR 7 页→2 页（p2/p3），4LDHT260 扫描 p4 不变，DHTS160/SuperEvo 均 0 不变。
- 四份文档补抽与主抽重复段：Inverter SR 10/10→0/6，4LDHT260 扫描→0/7，DHTS160→0/9，SuperEvo→0/8。
- Inverter SR 修后：p65 进主抽第 0 段，prompt 列出 冷却回路压降；p59 进主抽第 6 段。
- 待做：重启后整份重跑 Inverter SR，#67/#115 应为已检索到、调用次数应少于 34；压降是 CAE 分析目标（*May vary…），是否算正式指标待专家裁定。
