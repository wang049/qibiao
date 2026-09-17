# Agent 自进化（.krow）

本目录由 krow-agent-sdk 落盘：skills、reasoning、wiki 编译产物、ontology、自进化 overlay。  
它管 **agent 自己怎么干活**，不管电控清单哪一条该怎么认。

| 目录 | 职责 |
| --- | --- |
| `.krow/` | agent 自进化（本目录） |
| `.insights/` | 业务知识治理的变动经验 |
| `docs/knowledge/` | wiki 锚定的相对不变量（确认后的认条/公式/方法） |

抽出值只来自当份材料。禁止用本目录、`.insights` 或 wiki 填核对表。  
工位不 `agent.run()` 开放规划。业务复盘写到 `.insights/lessons/`，元规则见 `.insights/AGENTS.md`。
