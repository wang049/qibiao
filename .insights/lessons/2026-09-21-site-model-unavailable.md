# 2026-09-21 现场默认模型不可用

- 状态：active
- 条目：现场 DHTS1600 空缺项分段（27 段失败，规则 70 条）
- 闸门：`tests/test_llm.py::ModelUnavailableTests.test_looks_like_model_unavailable`；`tests/test_gateway.py::GatewayTests.test_chat_falls_back_when_model_unavailable`；`tests/test_gateway.py::GatewayTests.test_models_replace_default_missing_from_site_list`；`electrical/tests/test_extract_quality.py::ModelUnavailableTests.test_unavailable_model_is_not_a_chunk_skip`

## 代价

现场第三次出 DHTS1600，说明页写出真实原因：`识别服务 HTTP 400: This model is currently unavailable. Please try another model.` 包装成网关 502 后，抽取仍按「分段 JSON 坏了」拆半重试，27 段全失败。70 条已检索到是规则层；与上次对比只多了冷却回路压降、振动要求。配置默认 `deepseek-v4-pro` 在 `rdapi.aurobaytech-t.com` 当前不可用，下拉里还把它当推荐。

## 反事实

- 只读 `reasoning_content`、不认 unavailable：现场继续对死模型打满 27 段，两分钟出一张只有规则的表。
- 失败仍当 `_parse_failed`：模型不可用也会拆半重试，用户只看到「识别不完整」。
- 清单没有的默认模型仍插进 `/api/models`：下拉继续显示并选中 deepseek-v4-pro。

## 二级依据

- 现场回包原文：`{"error":"This model is currently unavailable. Please try another model."}`（工位 2026-09-21 17:45 说明页）。
- `.insights/AGENTS.md`：空缺项分段 JSON 必须打到能用的 chat 模型；规则先填不能代替分段。
- `packaging/windows/config.ini` / `使用说明.txt`：现场若没有 deepseek-v4-pro，应改用登录后清单里的 chat 模型。

## 闸门

- `looks_like_model_unavailable`：400 + try another model / currently unavailable / 模型不可用。
- `/v1/chat/completions` 遇到不可用即改打清单里下一个 chat 模型，并记住 `extract_model`，后续段不再打死模型。
- `/api/models`、出表开工：清单里没有当前默认时，改成清单中的 chat 模型，不把缺的默认插进下拉。
- `ExtractModelError` 不进 `_parse_failed`，避免再拆半空跑。
