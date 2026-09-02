# 电子电器 · SOR填表

先用开通的邮箱和密码登录，再拖入 PDF / Word / Excel 出核对表。

填表仍走 `electrical` 流水线（读文件 → 分流 → 规则 + 分段识别 → Excel）。识别按 KAD 指南对接：

1. `POST /auth/login`（email + password）拿到 JWT
2. `POST /api-keys` 创建 `sk-user-` Key（SDK 认这把，不认 JWT）
3. 抽取请求 `POST /v1/chat/completions`，Bearer 用这把 Key

两种交付壳、一套流水线。不要改成开放式 Agent 抄表。口径见 [docs/双端交付口径.md](docs/双端交付口径.md)。

| 形态 | 页面 | 规格书落点 |
| --- | --- | --- |
| 客户端（默认） | 只绑 `127.0.0.1` | 本机读取 |
| 网页端 | `delivery = site`，应用仍建议绑回环，内网 nginx HTTPS 转发 | 上传到场所服务器，不出公网 |

## 启动（客户端）

本机预览独立窗口（登录和出表仍是现在这套页面）：

```bash
cd /Users/wwj/电子电器项目/electrical-krow
export PATH="$HOME/.venv/bin:$HOME/.local/bin:$PATH"
export PYTHONPATH=.
export KROW_SERVER_URL=https://api.krow.cn
export KROW_CHAT_MODEL=deepseek-v4-pro

python -m electrical_krow desktop
```

仍可用 `python -m electrical_krow gateway` 只起服务并打开系统浏览器。

需要旁边的 `electrical` 工程（默认与本仓库同级），或设 `ELECTRICAL_ROOT`。

## Windows 客户端包

本机打 Windows 包（exe 安装包 + zip，不必先装 Python，平时无黑窗口）：

```bash
sh packaging/windows/build_zip.sh
```

产物：

- `dist/电子电器SOR填表-windows-x64.exe`（发给 Windows 同事：双击安装）
- `dist/电子电器SOR填表-windows-x64.zip`（解压后双击 `启动SOR填表.exe`）

用法见包内 `README.txt`：**独立窗口 + 嵌入 Python**，登录和出表在窗口内完成。客户现场只需改 `config.ini` 里的 `server_url`。

## 场所网页

本机预览（浏览器打开，文案为「场所网页 / 上传到本场所服务器」）：

```bash
python -m electrical_krow site --port 18767
```

浏览器会打开 `http://127.0.0.1:18767/`。生产部署见 [docs/场所网页部署.md](docs/场所网页部署.md)：`delivery = site`，应用绑回环，内网 nginx HTTPS 转发。不要把网关绑到公网。

## 测试

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
```
