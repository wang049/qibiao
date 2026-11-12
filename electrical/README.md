# 电子电器 · SOR填表

第一个功能：**工位电脑上丢进一份 PDF / Word / Excel，大约 5 分钟出一张可核对的表。**

规格书只在本机识别，**不出公网**。不做开放式聊天 Agent。流程是：

1. 本机 `document_reader` 读文件（带页码和表格）
2. 本机 Ollama（`127.0.0.1`）一次结构化抽取
3. 写成 Excel：值 + 页码 + 原文摘录 + 置信度；黄底 = 请人工看

扫描件 8 分钟是下一阶段（本机 OCR），这一版先打数字稿。5 分钟是否达标，要用**目标工位电脑 + 本机模型**重测，不能拿以前的 Krow Cloud 耗时当验收。

## 工位电脑准备

1. 安装 [Ollama](https://ollama.com)（Windows / macOS 均可）
2. 拉取本机模型（只需一次；离线工位用 U 盘拷模型，不要把规格书发上网）：

```bash
ollama pull qwen2.5:7b
```

3. 保持 Ollama 在后台运行（Windows 装好一般会自动起来）

不需要 `KROW_API_KEY`。程序默认只打 `http://127.0.0.1:11434`；若指向 `api.krow.cn` 或其他非本机地址，会直接失败。

可选环境变量：

```bash
export SPEC_SHEET_LLM_URL=http://127.0.0.1:11434
export SPEC_SHEET_LLM_MODEL=qwen2.5:7b
```

内存紧张用 `qwen2.5:7b`；工位有 16GB 以上内存可试 `qwen2.5:14b`（质量更好，更慢）。

## 工位本机出表

页面在 `electrical/frontend`，HTTP 服务在 `electrical/backend`。只监听本机 `127.0.0.1`，抽取仍走同一条流水线，文件不出公网。Ollama 先开着。

```bash
cd ~/电子电器项目/electrical
python -m electrical.backend
```

浏览器会打开 http://127.0.0.1:8765/ 。选 PDF / Word / Excel，点「开始出表」，完成后下载核对表。

命令行入口：`electrical`（出表）、`electrical-web`（页面）。

## 环境

Python 3.12。在项目目录：

```bash
cd ~/电子电器项目/electrical
export PATH="$HOME/.venv/bin:$HOME/.local/bin:$PATH"
```

## 先用示例文件测

项目里有一份虚构的「交流伺服电机」规格书，三种格式都有：

```bash
cd ~/电子电器项目/electrical
python -m electrical examples/sample_servo_spec.pdf
python -m electrical examples/sample_servo_spec.docx
python -m electrical examples/sample_servo_spec.xlsx
```

抽完打开 `output/sample_servo_spec_核对表.xlsx`。可对答案：型号 `SV-200A-400W`，额定功率 `400 W`，防护等级 `IP65`。

对照黄金答案打分（不调模型）：

```bash
python -m electrical.eval output/sample_servo_spec_核对表.xlsx examples/golden/sample_servo_spec.json
```

困难示例（历史型号 / 峰值电流 / 包装重量干扰）等客户文件前用来找抽错：

```bash
python -m electrical examples/sample_servo_spec_hard.pdf
python -m electrical.eval output/sample_servo_spec_hard_核对表.xlsx examples/golden/sample_servo_spec_hard.json
```

每本规格书只是中文、英文或德文其中一种（不是同一页三种语言）。核对表表头仍用中文，英文 `Type` / 德文 `Typ` 映射到「型号」。分别测：

```bash
python -m electrical examples/sample_servo_spec.pdf
python -m electrical examples/sample_servo_spec_en.pdf
python -m electrical examples/sample_servo_spec_de.pdf
```

德文示例用小数逗号（`2,8 A`、`1,35 kg`），打分时与 `2.8` / `1.35` 视为同一数值：

```bash
python -m electrical.eval output/sample_servo_spec_en_核对表.xlsx examples/golden/sample_servo_spec_en.json
python -m electrical.eval output/sample_servo_spec_de_核对表.xlsx examples/golden/sample_servo_spec_de.json
```

## 专家认可的整表黄金（防回退）

`examples/golden/dhts160_dpr.json` 由专家认可的 DHTS160 核对表冻结而来（2026-09-15，116 行）。改规则、词典、提示词或换模型后，重出一次再比：

```bash
python -m electrical /路径/DHTS160_DPR.docx -o output/dhts160_回归.xlsx
python -m electrical.eval output/dhts160_回归.xlsx examples/golden/dhts160_dpr.json
```

比对口径：核对状态必须一致；未检索到的必须仍是未检索到；有值的格黄金里的数字都要出现，措辞不同只告警；条款号不同只告警；页码不比。带 `value_must_not` 的行来自已结案复盘（如 #4 不得含三种模式 / 85kW）。

泛化体检（量「新文档也会走的那条路」的水平，不给日常出表用）：

```bash
# 只跑原文规则，不调模型（秒级）
SPEC_SHEET_RULES_ONLY=1 python -m electrical /路径/DHTS160_DPR.docx -o output/dhts160_仅规则.xlsx
# 跳过原文规则，只走词典认条 → 分段模型（要经已登录的本机网关）
SPEC_SHEET_MODEL_ONLY=1 SPEC_SHEET_LLM_URL=http://127.0.0.1:18765 python -m electrical /路径/DHTS160_DPR.docx -o output/dhts160_仅模型.xlsx --model deepseek-v4-pro
python -m electrical.eval output/dhts160_仅模型.xlsx examples/golden/dhts160_dpr.json
```

2026-09-15 基线：仅规则 115/116；仅模型 96/116（0 错填，17 漏、3 表格列缺失，8 段识别失败被丢弃），漏项集中在 14 段预算没覆盖到的第 2/4/5 章。

2026-09-16 起选段改为「按空缺找段」：`_select_chunks(..., rows=rows)` 对每个仍空缺条目用条目名 + 词典强别名 + 原文针做贪心覆盖；别名旁有数字单位或在标题行算强命中；`P1 / P3 / BOOST / 升压` 这类 3 条以上条目共用的泛词不算覆盖依据；覆盖贪心与性能词打分各留名额（打分至少 1/3）。补抽 `_topup_chunks` 用同一套覆盖只为主抽后仍空的条目找段；超过 12 万字的文档按长度加段（上限 22），补抽 10 段。整段识别失败（超时 / JSON 坏）时拆半重试一次（`_split_chunk_halves`），不再直接丢段。CLI 默认超时从 90 s 对齐到工位的 180 s：deepseek-v4-pro 一段 80–200 s，90 s 下四成段超时，之前仅模型基线里「8 段识别失败」就是这个原因。

2026-09-16 生产态（规则先填 + 模型补空缺，工位 180 s 超时）：114/116，4 分 59 秒，14 次调用，0 段失败。两处差异：#53 P3 主动短路电流新填「310 Arms / 20 s / 1300Arms@1ms」逐字来自 6.5.8.1，是黄金集偏保守（专家版那格为空）；#61 Boost 输出性能 450 V 漏——已修：泛词 `Boost` 不再让 2.3 零件号表冒充 6.5.4 升压页。

2026-09-16 列 prompt 条目也认词典强别名：`_chunk_fields` 在条目名分词零分时按强别名整词补分（英文别名整词、允许 s/es 复数，`creep` 不认 `creepage`）。此前「速比」二字切不出整词，选段把含速比表的页送进模型、prompt 却不列 #75，4LDHT260 扫描件与 SuperEvo 两份都静默漏；模型对该段两次实测均返回 `ICE 7.119/4.881/3.689/2.941；主减 3.462；P3 12.830`。三份文档逐段比对没有条目被挤出 top40，新列入的 电机类型/主动保险/网络安全 在守卫处全部拒格。

2026-09-16 待专家口径标注：`electrical/pending_rulings.py` 读 `electrical-krow/docs/knowledge/pending_rulings.json`（按核对表序号；`when` / `family` / `match` 三道门），出表时给命中格的复核备注追加「待专家口径：…」并加批注，说明页合计一行；`finalize_retrieval_statuses` / `_review_status` 判状态时剥掉这一段，抽出值与检索结论不受影响。口径定下后删条并落规则 / 黄金。`tests/test_pending_rulings.py`。

2026-09-16 逆变器 SR 两处选段漏洞：`_is_front_matter` 只认目录标题（独占一行的 Contents / Table of Contents / 目录 / Revision History），正文表头 `CATEGORY CONTENTS TARGET` 不再让 Table 3.12（冷却压降 <300mbar@12lpm）整页被剔；`_topup_chunks` 判重键改为剥页眉后的开头 80 字，带 running header 的文档补抽不再重送主抽已送过的页（Inverter SR 修前 10/10 段重复、34 次调用净增 0 格）。

2026-09-17 模型推理不进工位设置，默认跟上游（开）。`SPEC_SHEET_LLM_THINKING=disabled` → 请求带 `thinking.type=disabled`（`_thinking_controls`），只留给运维环境变量或 `/api/jobs` 表单 `thinking=off` 显式关。09-16 三份对比记录：开推理时 deepseek-v4-pro 单段常撞 180 s 超时再拆半重试（DHTS160 19 分钟 / 21 次调用 / 2 段失败），关掉后 DHTS160 黄金 116/116、SuperEvo 21.5 s（原 11.5 分）、4LDHT260 扫描件 3.4 分含 OCR（原十几分），三份零丢项零错值；差异只在同一原文的取舍（#55 堵转填一档还是三档、#69/#97 重量带不带 kg）。

2026-09-16 弱别名接入后仅模型：**102/116**（15 分钟，0 段失败）。重量 ×2、防腐 ×2、OD 集成、Boost 输出性能均转为命中；还漏 7 条（P1 位置传感器、CPSR、IGBT 温度精度、湿度、阻燃标准、限用物质、通讯方式），另 7 条找到页但取句与专家版不同（振动、寿命、低压电源、P3 堵转、直流电压 ×2、#18）。

2026-09-16 弱别名接入前仅模型（180 s 超时，18 段 + 补抽 10 段，16 分钟）：94/116。与 09-15 的 96/116 比：漏项 17 → 10，段失败 8 → 1；#53/#51 P3 ASC 是真实命中被保守黄金集判错；振动 / 寿命 / P3 堵转 / 低压电源 4 组现在能找到页并填值，但取的句子或数字与专家版不同（如振动填了正弦加随机 30h 而非 Q/JLP 030600 标准号），按整表评分算不一致。还漏的 10 条里 4 条是词典别名为空（重量 ×2、防腐 ×2）。

`控制器重量 / 重量要求 / 防腐等级 / 防腐要求 / 扭矩控制精度 / 转矩控制精度` 六条的别名在词典 `weak_aliases` 层（同槽两条共享，进不了 strong）。2026-09-16 起 `FieldSpec` 带 `weak_aliases` / `unit_cues`，找页与 prompt 认条用弱别名，prompt 别名提示仍只给强别名；不含条目核心字的弱别名（质量 / 涂层 / weight / mass）最多算顺带提及。词典本身没改。

新文档得到专家认可后同样冻结：

```bash
python -m electrical.eval /路径/专家认可.xlsx examples/golden/<doc>.json --freeze --source <源文件名> --note "认可日期与说明"
```

## 跑自己的规格书

```bash
cd ~/电子电器项目/electrical
python -m electrical /路径/你的规格书.pdf
```

Word / Excel 同样：

```bash
python -m electrical /路径/规格书.docx
python -m electrical /路径/参数表.xlsx
```

指定输出位置：

```bash
python -m electrical /路径/规格书.pdf -o ~/Desktop/核对表.xlsx
```

成功时终端类似：

```
源文件 : 某某规格书.pdf
扫描件 : 否（按数字稿处理）
输出   : /Users/你/电子电器项目/electrical/output/某某规格书_核对表.xlsx
字段   : 20 行，其中 8 行建议人工核对
耗时   : 47.2 秒
```

打开 xlsx：

- 工作表「核对表」：逐字段核对
- 黄底行：空值，或置信度 &lt; 0.8
- 「核对状态」下拉：待核对 / 通过 / 需修改

## 现在不要做的事

- 不要把规格书发到 `api.krow.cn` 或任何公网模型
- 不要 `git clone aullik5/krow`（私有仓，外部开发者不需要）
- 不要对整本规格书跑 `agent.run("帮我抄表")`（会超时、漏字段）

## 客户文件还没到时

先把困难示例和黄金答案在**本机模型、断公网**下跑通；同时向客户要 5 份脱敏样张（最好抄的、最厚的、表格最乱的、一本扫描件、一份他们现在的人工抄表）。不要先做开放式 Agent 或精细 OCR。

## 下一步

本机数字稿跑通、人工核对可接受、工位电脑耗时可接受之后，再加：Windows 拖放壳、本机扫描件 OCR、你们自己的字段模板。
