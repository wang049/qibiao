# 2026-09-21 现场分段失败：推理正文不在 content

- 状态：superseded
- 后续：现场第三次说明页证明 27 段失败的直接原因是模型 400 unavailable，见 `2026-09-21-site-model-unavailable.md`。读 `reasoning_content` 与默认关推理仍保留。
- 条目：现场 DHTS1600 空缺项分段（整层 27 段失败，规则层 70 条仍在）
- 闸门：`tests/test_llm.py::LlmTests.test_complete_uses_reasoning_content_when_content_empty`；`tests/test_gateway.py::GatewayTests.test_jobs_thinking_flag_sets_env_and_rejects_bad_value`；`electrical/tests/test_extract_quality.py::AssistantTextTests.test_reasoning_content_used_when_content_empty`；`electrical/tests/test_doc_qa.py::PipelineQaTests.test_chunk_error_reaches_workbook_cover`

## 代价

现场包连 `https://rdapi.aurobaytech-t.com`，同一份 DHTS1600 DPRR.docx 连出两次：2 分 22 秒 / 2 分 18 秒，都是 70 已检索到、26 局部、36 未检索到、27 段失败。本机公网联调同清单 DHTS160 要 10 分钟、失败 0–2 段。2 分钟出完说明不是 180 秒超时，是每一段很快回来但工位当成没 JSON。说明页只写「识别不完整」，看不出原因。

## 反事实

- 工位页继续不传 thinking、空值当「上游默认开推理」：现场 deepseek 把 JSON 放在 `reasoning_content`，`content` 为空；`extract` 只读 `message.content`，主抽+补抽+拆半全部 `_parse_failed`，再跑还是只有规则 70 条。
- 只改提示词「必须输出 JSON」、不读 `reasoning_content`、不关推理：现场回包形态不变，27 段失败不会少。
- 失败仍只记次数、不记原因：下次现场只能再猜超时或算力。

## 二级依据

- `.insights/AGENTS.md`：作业路径是规则先填 → 空缺项分段 JSON。70 条已检索到是规则层；27 段失败是分段 JSON 没进格子，不是核对表没做成。
- `electrical_krow/gateway.py` 原注释：出表只要 JSON；`deepseek-v4-pro` 开推理时单段常撞超时或把正文放到推理字段。
- 两次现场任务统计相同（70/26/36/4），证明模型层零贡献，不是偶发网络。

## 闸门

- `assistant_text` / `_assistant_text`：`content` 为空时用 `reasoning_content` / `reasoning`；网关回包把正文写回 `message.content`，抽取侧同一套读取。
- `/api/jobs` 的 thinking 空或 off → `SPEC_SHEET_LLM_THINKING=disabled`；只有显式 `on` 走上游默认。
- `ExtractMeta.chunk_error` 写入说明页「识别完整性」和任务 `chunk_error`，工位结果注记带次数和原因。
