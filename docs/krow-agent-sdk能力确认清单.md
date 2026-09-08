# krow-agent-sdk 能力确认清单

**用途**：确认 SDK 是否具备以下能力。请在「是否支持」列填写，需要补充的写在「说明」列。
**版本**：`krow-agent-sdk 0.9.2.2` + 本机 `krow-agent-sdk-runtime 0.9.1.11`（Python 3.12）。runtime 不在公网 PyPI，需用官方安装方式配对；若已有 0.9.2.2 runtime，请在说明列注明。
**背景**：指定场所 Windows 工位客户端。已用 SDK 做登录、读 PDF/Word/Excel、向场所识别服务分段 chat。作业路径预先编排，**不** `agent.run()` 开放规划。知识库只用于「认这条规格是清单哪一项、互斥、已确认公式」；抽出值只来自当份材料或当份已出现的量按公式计算。禁止用库内示例/典型值填格，禁止公网向量，整库不出场所。请按这个约束回答，不要按文档入库 + RAG 问答来理解。

---

## 一、认条（不经过问答 / 向量）

| # | 能力 | 是否支持 | 说明 |
|---|---|---|---|
| 1.1 | **不调用** `KnowledgeServiceV2.ask()`、**不打 embedding**，仅按别名/标签在本机认条 | | |
| 1.2 | `krow_agent_sdk.data.query_global_ontology` 可用于上述认条（纯内存/SQLite，zero-LLM） | | |
| 1.3 | 可按条目状态过滤：未确认 / 未开通检索的条目**不参与**查询 | | |
| 1.4 | 同一概念可挂强别名、弱别名，查询时可区分权重（不要弱别名抢选段） | | |
| 1.5 | 可表达互斥 / 禁配（如 P1 与 P3、三种纹波），查询结果能带上互斥对象 id | | |
| 1.6 | 宿主**不** `agent.run()`、不加载 ACT 时，1.1–1.5 仍可用 | | |

**补充问题**

- 1.7　`query_global_ontology` 的匹配范围是 alias / label / definition 哪些字段？有无整词、最短长度限制？
- 1.8　未确认条目若已写入 Ontology，官方推荐是「不要写入」还是「写入但查询时过滤」？
- 1.9　认条结果能否稳定返回我们自己的条款序号（如清单 #14），而不是只有内部 object id？

> **1.1 和 1.6 是我们最关心的。** 做不到就继续用我们自己的关键词索引，不接 Ontology。

---

## 二、建设与落盘（真源在我们仓库）

| # | 能力 | 是否支持 | 说明 |
|---|---|---|---|
| 2.1 | 条款真源是宿主 YAML/JSON，发布时**写入**本机 `GlobalOntologyStore`，工位只读 | | |
| 2.2 | 写入走公开、稳定 API（不必直接 `from modules.knowledge.global_ontology_store import ...`） | | |
| 2.3 | `krow_agent_sdk.data` 只读 facade **之外**有官方写入入口 | | |
| 2.4 | 可指定 Ontology SQLite 目录（工位 `%LOCALAPPDATA%`），不写进用户打开的规格书目录 | | |
| 2.5 | 一次发布可整体替换该版本对象（可回滚到上一发布，不必手工删库） | | |
| 2.6 | 公式/物理关系可作为对象入库，并带「禁止用该对象填取值」类标记 | | |

**补充问题**

- 2.7　推荐的对象类型是 `Concept`（条款）+ `Relation`（互斥/see），还是应建成 `Entity`？`kind` 自定义是否必须先注册 Domain Pack？
- 2.8　`GlobalOntologyStore.add` 的幂等规则：同一 `id` 是更新还是冲突？
- 2.9　官方是否反对把 `xlsx` 参考示例、企标典型值写进 `definition`？有没有「只展示、不可取值」字段？

---

## 三、Domain Pack

| # | 能力 | 是否支持 | 说明 |
|---|---|---|---|
| 3.1 | `with_domain_pack_manifest(yaml或dict)` 注册自定义电控包（不继承 k12/legal/medical） | | |
| 3.2 | 可扩展实体种类：`clause`、`physics_law` | | |
| 3.3 | 可扩展关系种类：`conflicts_with`、`see_also`、`excludes` | | |
| 3.4 | 仅激活 pack、**不** `agent.run()` 时，Ontology 读写仍按该 pack 的 kind 校验 | | |
| 3.5 | 激活 pack **不会**改变分段 chat 的填表内容（不会把 pack 的 few-shot 写进抽出值） | | |

**补充问题**

- 3.6　工位不用 Planner/ACT 时，还要不要 `with_domain_pack_manifest`？只为通过 kind 校验的话，有更小的注册方式吗？
- 3.7　manifest 里的 `planner_hint_insert` / `few_shot` 在未 `run()` 时会不会被 chat 分段请求带上？

---

## 四、Windows 工位交付 / 无向量

| # | 能力 | 是否支持 | 说明 |
|---|---|---|---|
| 4.1 | 只用 `krow-agent-sdk`（不含 runtime）即可做 1.1 认条 | | |
| 4.2 | 认条/Ontology **必须**打 `krow-agent-sdk-runtime` 的 win_amd64 | | |
| 4.3 | Ontology 本机 SQLite 即可，**不**依赖 Elasticsearch | | |
| 4.4 | 认条/发布 **不**调用 embedding / `with_text_encoder_model` | | |
| 4.5 | 建设期和运行期均可关闭知识编译、文档 chunk 入库 | | |
| 4.6 | 关闭向量后，登录 + 读文档 + 分段 chat 仍可用 | | |

**补充问题**

- 4.7　runtime 绿包大约多少体积？除 Cython 模块外，jieba / networkx / ES 哪些是 Ontology 认条的硬依赖？
- 4.8　`with_text_encoder_model` 或默认知识编译会不会对 `server_url` 发 embedding？如何保证场所内也**零向量**，只保留 chat 提取？
- 4.9　Darwin 开发机 runtime 与 Windows 工位 runtime 的 API 是否同一套？有无仅桌面端才有的知识库 UI 依赖？

> **4.3 / 4.4 与 1.1 同等优先。** 做不到无 ES、无 embedding，我们不会把条款库迁到 SDK。

---

## 五、手册原文检索（第 2、3 项以后，仍禁止填典型值）

| # | 能力 | 是否支持 | 说明 |
|---|---|---|---|
| 5.1 | 本机读取手册/过往文档，按关键词返回**页码 + 原文摘录**，不生成结论 | | |
| 5.2 | 上述检索**不**走 `ask()`，也不用目录/典型值补空 | | |
| 5.3 | `KnowledgeServiceV2.search()` 可在无 ES、无 embedding 下降级（例如只 SQLite/倒排） | | |
| 5.4 | `DocumentParserPlugin` 只替换「默认读 PDF」路径，不进入填表/问答 | | |

**补充问题**

- 5.5　第 2、3 项这种「对着手册找出处」，官方建议 `search()`、解析器插件，还是宿主自做索引、SDK 只负责 `read_document`？
- 5.6　`add_file` 是否必然做实体抽取/LLM 编译？能否「只切块索引、不抽取」？

---

## 六、其他

| # | 问题 |
|---|---|
| 6.1 | `LLMSourceModule.KNOWLEDGE_GRAPH`（「知识库」）在分段 chat 场景会不会被自动带上？如何避免？ |
| 6.2 | `get_memory_stats` / `query_memories` 是否跨任务持久？我们需求是不保存人员偏好或会话记忆。 |
| 6.3 | 公式「仅当输入量来自当份材料才允许计算」是否在 SDK 有一等能力，还是宿主自己算？ |

---

## 优先级

时间有限的话，先回这五条即可：

1. **1.1 / 1.6** 能否本机认条、不 `ask()`、不 `agent.run()`
2. **4.3 / 4.4** 能否无 ES、无 embedding
3. **4.1 / 4.2** 工位包要不要打 runtime
4. **2.2 / 2.3** 有没有稳定写入 API
5. **3.5 / 3.7** 激活 Domain Pack 会不会污染分段 chat 填表

其余可后补说明。
