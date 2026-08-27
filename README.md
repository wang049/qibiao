# 电子电器 · SOR填表（登录）

给指定场所部署用的登录与识别接入。填表仍走 `electrical` 流水线（读文件 → 分流 → 规则 + 分段识别 → Excel），不要改成开放式 Agent 抄表。

本期工位验收仍是本机出表。本服务只绑 `127.0.0.1`。规格书不出公网。

## 做什么

1. **登录**：用户名密码 `POST /api/auth/login`，或 `KROW_API_KEY`（由 `krow_agent_sdk.auth` 校验）。
2. **识别**：`POST /v1/chat/completions`，请求体和出表分段抽取同一形态。
3. **登录页**：浏览器先登录；出表程序可把 `SPEC_SHEET_LLM_URL` 指到 `http://127.0.0.1:18765`（仍是回环）。

没有内网地址时，用本机联调服务（账号 `demo` / `demo`）。

## 启动

```bash
cd /Users/wwj/电子电器项目/electrical-krow
export PATH="$HOME/.venv/bin:$HOME/.local/bin:$PATH"
export PYTHONPATH=.

python -m electrical_krow mock --port 18766

# 另开终端
export KROW_SERVER_URL=http://127.0.0.1:18766
python -m electrical_krow gateway

open http://127.0.0.1:18765/
```

有内网地址时：

```bash
export KROW_SERVER_URL=https://内网识别服务
export KROW_USERNAME=...
export KROW_PASSWORD=...
# 或 export KROW_API_KEY=sk-user-...
python -m electrical_krow gateway
```

## 和出表服务联调

出表服务默认仍打本机识别。要切到本登录页：

```bash
export SPEC_SHEET_LLM_URL=http://127.0.0.1:18765
```

先登录，再出表。接受出表程序用的 `Authorization: Bearer local`（最近一次登录会话）。

```bash
python -m electrical_krow probe
```

## 测试

```bash
cd /Users/wwj/电子电器项目/electrical-krow
PYTHONPATH=. python -m unittest discover -s tests -v
```
