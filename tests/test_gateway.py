from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from electrical_krow.config import CLOUD_API_URL, SITE_API_URL, load_settings
from electrical_krow.errors import LLMError
from electrical_krow.gateway import create_app
from electrical_krow.llm import ChatResult
from electrical_krow.login import AuthSession
from electrical_krow.mock_server import DEMO_USER


class GatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.settings = load_settings(server_url="http://127.0.0.1:18766")
        self.client = TestClient(
            create_app(self.settings, output_dir=Path(self._tmp.name))
        )

    def test_index(self) -> None:
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("SOR 出表", resp.text)
        self.assertIn("开始出表", resp.text)
        self.assertIn("识别模型", resp.text)
        self.assertIn("规则先填，模型只补空缺项", resp.text)
        self.assertIn("按模板写出页码与原文摘录", resp.text)
        self.assertIn("step-desc", resp.text)
        self.assertIn('id="model"', resp.text)
        self.assertIn("/static/app.js", resp.text)
        self.assertIn("/static/i18n.js", resp.text)
        self.assertIn("/static/kb.js", resp.text)
        self.assertIn("知识库", resp.text)
        self.assertIn('id="kb-card"', resp.text)
        self.assertIn('id="rail-kb"', resp.text)
        self.assertIn('id="rail-extract"', resp.text)
        self.assertIn('id="home-card"', resp.text)
        self.assertIn("styles.css?v=20261103a", resp.text)
        self.assertIn("i18n.js?v=20261105g", resp.text)
        self.assertIn("app.js?v=20261106a", resp.text)
        self.assertIn('data-target="io-manual"', resp.text)
        self.assertIn('data-kind="arch"', resp.text)
        self.assertIn('data-kind="hsi"', resp.text)
        self.assertNotIn("source-pick", resp.text)
        js = self.client.get("/static/app.js").text
        self.assertIn("fileFromSource", js)
        self.assertIn("mcuInput.value = detected", js)
        self.assertIn("io.pickLocal", js)
        self.assertIn('id="rail-tab-hsi"', resp.text)
        self.assertIn('id="hsi-list"', resp.text)
        self.assertIn('id="io-dl"', resp.text)
        self.assertIn('id="io-mcu-field"', resp.text)
        self.assertIn("ioMcuReady", js)
        self.assertIn('id="io-mcu-menu"', resp.text)
        self.assertIn("TC399", resp.text)
        self.assertLess(resp.text.find('id="io-manual"'), resp.text.find('id="io-mcu"'))
        self.assertLess(resp.text.find('id="io-mcu"'), resp.text.find('id="io-package-field"'))
        self.assertIn("TC387", resp.text)
        self.assertIn("TC324", resp.text)
        self.assertIn('id="io-package-field"', resp.text)
        self.assertIn('id="io-package-choices"', resp.text)
        self.assertIn('id="env-busy"', resp.text)
        self.assertIn("js-open-settings", resp.text)
        self.assertIn("settings-dialog", resp.text)
        # 常规设置：外观 / 布局 / 识别环境三页；首屏内联脚本按 localStorage 套主题
        for tab in ("appearance", "layout", "general", "extract", "env", "about"):
            self.assertIn(f'data-tab="{tab}"', resp.text)
            self.assertIn(f'data-panel="{tab}"', resp.text)
        for pref in (
            "lang", "theme", "accent", "zoom", "font", "contrast", "motion", "density", "rail", "autoOpen",
            "rememberUser", "notify", "sound", "confirmClose",
        ):
            self.assertIn(f'data-pref="{pref}"', resp.text)
        # 模型推理不进设置：跟上游默认（开）
        self.assertNotIn('data-pref="thinking"', resp.text)
        self.assertIn('id="pref-model"', resp.text)
        self.assertIn('id="about-list"', resp.text)
        self.assertIn('data-about="client"', resp.text)
        self.assertNotIn('data-about="knowledge"', resp.text)
        self.assertNotIn('id="about-open-output"', resp.text)
        self.assertNotIn('id="about-copy"', resp.text)
        self.assertIn('data-value="system"', resp.text)
        self.assertIn("跟随系统", resp.text)
        self.assertIn("对比度", resp.text)
        self.assertIn("减弱动画", resp.text)
        self.assertIn('data-value="80"', resp.text)
        self.assertIn('data-value="150"', resp.text)
        self.assertIn("prefers-reduced-motion: reduce", resp.text)
        self.assertIn('localStorage.getItem("electrical.prefs")', resp.text)
        self.assertIn("prefers-color-scheme: dark", resp.text)
        self.assertIn('id="settings-reset"', resp.text)
        self.assertIn('id="env-choices"', resp.text)
        self.assertIn("id=\"st-qc\"", resp.text)
        self.assertIn("先看文件能不能读", resp.text)
        self.assertNotIn("当前登录账号发起", resp.text)
        self.assertIn('id="job-list"', resp.text)
        self.assertIn("工作台", resp.text)
        self.assertIn("SOR 参数提取", resp.text)
        self.assertIn("开始出表", resp.text)
        self.assertNotIn("新建出表", resp.text)
        self.assertNotIn("后续节点", resp.text)
        self.assertNotIn("核心能力", resp.text)
        self.assertNotIn("分节点交付", resp.text)
        self.assertNotIn("能力 2", resp.text)
        self.assertNotIn("id=\"nav-work\"", resp.text)
        self.assertNotIn("交给 Agent", resp.text)
        self.assertNotIn("agent.run", resp.text)
        self.assertNotIn("新建对话", resp.text)

    def test_static_assets(self) -> None:
        css = self.client.get("/static/styles.css")
        js = self.client.get("/static/app.js")
        self.assertEqual(css.status_code, 200)
        self.assertIn(".drop", css.text)
        self.assertIn(".step-desc", css.text)
        self.assertIn("no-store", (css.headers.get("cache-control") or "").lower())
        self.assertEqual(js.status_code, 200)
        self.assertIn("/api/jobs", js.text)
        self.assertIn("Bearer local", js.text)
        self.assertIn("/api/models", js.text)
        i18n = self.client.get("/static/i18n.js")
        self.assertEqual(i18n.status_code, 200)
        self.assertIn("上传到本场所服务器", i18n.text)
        self.assertIn("Files are uploaded to this site server", i18n.text)
        self.assertIn("文件只在本机读取", i18n.text)
        self.assertIn("Files are read on this computer only", i18n.text)
        self.assertIn("局部对应", i18n.text)
        self.assertIn("未检索到", i18n.text)
        self.assertIn("库不提供取值", i18n.text)
        self.assertIn("Start Extraction", i18n.text)
        self.assertIn("Drop a file, or click to choose", i18n.text)
        self.assertIn("OCR only applies to scans.", i18n.text)
        self.assertIn("Check for mismatch", i18n.text)
        self.assertIn("Template fitting", i18n.text)
        self.assertNotIn("Rules fill first; the model only fills gaps", i18n.text)
        self.assertIn("Add source information", i18n.text)
        self.assertIn("Recent workbooks", i18n.text)
        self.assertIn('"pref.theme": "Theme"', i18n.text)
        self.assertIn("Overall Color Theme", i18n.text)
        self.assertIn("Follow OS", i18n.text)
        self.assertIn("Use credentials to sign in.", i18n.text)
        self.assertIn("Permission needed for first-time use.", i18n.text)
        self.assertIn("The default model will update with each extraction job.", i18n.text)
        self.assertIn("Opens automatically when the job is done.", i18n.text)
        self.assertNotIn("Use credentials to sign-in", i18n.text)
        self.assertNotIn("Drop a specification, or click to choose", i18n.text)
        self.assertIn("function applyStaticI18n", i18n.text)
        self.assertIn("function langFromQuery", i18n.text)
        self.assertIn("function localizeJobMessage", i18n.text)
        self.assertIn("function kindLabelText", i18n.text)
        self.assertIn("Motor controller DPR", i18n.text)
        self.assertIn("same-type, same-medium", i18n.text)
        self.assertIn("function fileInfoKindLabel(", js.text)
        self.assertIn("本机模型已完成第", i18n.text)
        self.assertIn("Completed segment {a}/{b}", i18n.text)
        self.assertIn("function paintJobStatus(", js.text)
        self.assertIn("save_sheet", js.text)
        self.assertIn("download", js.text)
        self.assertIn('tx("stat.partial")', js.text)
        self.assertIn('tx("stat.miss")', js.text)
        self.assertNotIn("qa_verdict", js.text)
        self.assertIn('tx("hero.kb.lead")', js.text)
        self.assertNotIn("已见主题", js.text)
        self.assertNotIn("coverage_note", js.text)
        self.assertNotIn("不按数字稿约五分钟", js.text)
        kb = self.client.get("/static/kb.js")
        self.assertEqual(kb.status_code, 200)
        self.assertIn("/api/knowledge", kb.text)
        self.assertIn('tx("kb.back")', kb.text)
        self.assertNotIn(".yaml", kb.text)
        self.assertNotIn("clause_lexicon", kb.text)
        # 知识库页只留三张统计卡和一句口径，列表里未确认条目不写字、悬停才解释
        self.assertNotIn('tx("kb.stat.edges")', kb.text)
        self.assertNotIn('tx("kb.stat.groups")', kb.text)
        self.assertNotIn('tx("kb.stat.retrieve")', kb.text)
        self.assertNotIn('tx("kb.stat.secret")', kb.text)
        self.assertNotIn("catalog.rule ||", kb.text)
        self.assertIn('tx("kb.pendingTip")', kb.text)
        page = self.client.get("/").text
        self.assertNotIn("kb.noFill", page)
        self.assertIn("库只提供条目含义、出处和条目间关系，抽出值一律来自当份规格书。", page)
        i18n = self.client.get("/static/i18n.js")
        self.assertIn('"hero.kb.kicker": "本机知识库"', i18n.text)
        self.assertIn('"kb.onPrem": "不出公网"', i18n.text)
        self.assertIn('"kb.open": "可检索"', i18n.text)
        self.assertNotIn("场所知识库", i18n.text)
        self.assertNotIn("禁止用库填数", i18n.text)
        self.assertIn(".kb-graph-wrap", css.text)
        self.assertIn(".rail-fn", css.text)
        self.assertIn(".fn-card", css.text)
        self.assertIn(".fn-card.is-later", css.text)
        self.assertNotIn(".fn-card.is-soon", css.text)
        self.assertIn(".rail", css.text)
        self.assertNotIn(".rail-new", css.text)
        self.assertIn(".job-row", css.text)
        self.assertIn(".settings-dialog", css.text)
        self.assertRegex(
            css.text, r"\[hidden\]\s*\{[^}]*display:\s*none\s*!important"
        )
        self.assertIn("#login-card:not([hidden])", css.text)
        self.assertIn("loadJobs", js.text)
        self.assertIn('$("who").textContent = name', js.text)
        self.assertIn('tx("status.waitPrev")', js.text)
        self.assertIn("waitUntilIdle", js.text)
        self.assertIn("resumeActiveJob", js.text)
        self.assertIn("isBusyConflict", js.text)
        self.assertIn("/api/settings", js.text)
        self.assertIn("js-open-settings", js.text)
        # 常规设置只存本机 localStorage，跟随系统用 matchMedia 监听，父壳可用 ?theme= 指定
        self.assertIn('"electrical.prefs"', js.text)
        self.assertIn("prefers-color-scheme: dark", js.text)
        self.assertIn("function applyPrefs(", js.text)
        self.assertIn("function themeFromQuery(", js.text)
        self.assertIn("function langFromQuery(", i18n.text)
        self.assertIn("function applyUiLang(", js.text)
        self.assertIn('const title = tx("brand.agent")', js.text)
        self.assertIn("function environmentLabel(", js.text)
        self.assertIn('tx("env.cloud")', js.text)
        self.assertIn('tx("env.site")', js.text)
        self.assertIn("function applyEnvLock(", js.text)
        self.assertIn("is-pack-locked", js.text)
        self.assertIn("environment_locked", js.text)
        self.assertIn("function jobIsRunning(", js.text)
        self.assertIn('tx("env.busy")', js.text)
        self.assertIn("本包为现场识别，不能切换到公网联调。", i18n.text)
        self.assertIn("cannot switch to the public cloud.", i18n.text)
        self.assertIn("Cannot switch during a running job.", i18n.text)
        self.assertIn("从可用环境中选择。可能需要重新登录。", i18n.text)
        self.assertIn("Automatically extract contents from SOR.", i18n.text)
        self.assertIn("Documentation", i18n.text)
        self.assertIn('"home.chipStds": "Standards"', i18n.text)
        self.assertNotIn("home.chipNoKb", i18n.text)
        self.assertIn(".settings-dialog p.env-busy", css.text)
        self.assertIn(".env-choices.is-locked", css.text)
        self.assertIn("applyDesktopTitle", js.text)
        self.assertIn("api.set_title(title)", js.text)
        self.assertIn("settings-reset", js.text)
        self.assertNotIn("/api/prefs", js.text)
        # 出表偏好：工位页不传 thinking（跟上游默认）；完成后自动打开只对本页发起的任务
        self.assertNotIn('body.append("thinking"', js.text)
        self.assertIn("/open", js.text)
        self.assertIn("startedHere", js.text)
        self.assertIn("function applyDefaultModel(", js.text)
        self.assertIn("function loadAbout(", js.text)
        # 通用：记住邮箱只存邮箱不存密码；完成提醒只对本页任务；关窗确认走 beforeunload
        self.assertIn('"electrical.lastUser"', js.text)
        self.assertNotIn("electrical.lastPass", js.text)
        self.assertIn("function finishAlert(", js.text)
        self.assertIn("Notification.requestPermission", js.text)
        self.assertIn('addEventListener("beforeunload"', js.text)
        self.assertIn("/api/output/open", js.text)
        self.assertIn('tx("model.recommended")', js.text)
        self.assertIn("prefers-reduced-motion: reduce", js.text)
        self.assertIn("function motionReduced(", js.text)
        self.assertIn("function motionAttr(", js.text)
        for attr in ("data-theme", "data-accent", "data-zoom", "data-font", "data-contrast", "data-motion", "data-density", "data-rail"):
            self.assertIn(f'html[{attr}=', css.text, attr)
        self.assertIn('html[data-theme="dark"]', css.text)
        self.assertIn("color-scheme: dark", css.text)
        self.assertIn('html[data-zoom="80"]', css.text)
        self.assertIn('html[data-zoom="150"]', css.text)
        self.assertIn('html[data-contrast="high"]', css.text)
        self.assertIn('html[data-motion="reduce"]', css.text)
        self.assertIn('html[data-rail="right"] body.is-logged .desk { flex-direction: row-reverse; }', css.text)
        self.assertIn(".settings-tab", css.text)
        self.assertIn(".swatches", css.text)
        # 深浅色都靠变量：面板底色不再写死白色
        self.assertNotIn("background: #fff;", css.text)
        self.assertIn('tx("result.chunkFail"', js.text)
        self.assertIn("chunk_error", js.text)
        self.assertNotIn('tx("result.qa"', js.text)
        self.assertNotIn("交给 Agent", js.text)

    def test_embed_contract_for_electron_host(self) -> None:
        html = self.client.get("/?embed=1")
        self.assertEqual(html.status_code, 200)
        self.assertIn("SOR 出表", html.text)
        js = self.client.get("/static/app.js").text
        css = self.client.get("/static/styles.css").text
        i18n = self.client.get("/static/i18n.js").text
        self.assertIn("function embedMode(", js)
        self.assertIn("ELECTRICAL_API_BASE", js)
        self.assertIn("embed=1", js)
        self.assertIn("electricalApiUrl", js)
        self.assertIn("body.is-embed", css)
        self.assertIn("if (embedMode()) return null", js)
        self.assertIn("function langFromQuery", i18n)
        self.assertIn('q.get("lang")', html.text)
        self.assertIn('data-pref="lang"', html.text)

    def test_jobs_list_requires_login(self) -> None:
        resp = self.client.get("/api/jobs")
        self.assertEqual(resp.status_code, 401)

    def test_health(self) -> None:
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("ok", data)
        self.assertTrue(data.get("fill"))
        self.assertTrue(data.get("model"))
        self.assertEqual(data.get("delivery"), "client")
        self.assertFalse(data.get("busy"))
        self.assertIsNone(data.get("active_job"))
        self.assertIn("environment", data)
        data = self.client.get("/api/settings").json()
        self.assertEqual(len(data.get("environments") or []), 2)
        ids = {item["id"] for item in data["environments"]}
        self.assertEqual(ids, {"cloud", "site"})
        self.assertFalse(data.get("environment_locked"))

    def test_site_health_copy(self) -> None:
        settings = load_settings(
            server_url="http://127.0.0.1:18766", delivery="site"
        )
        client = TestClient(create_app(settings, output_dir=Path(self._tmp.name)))
        data = client.get("/api/health").json()
        self.assertEqual(data.get("delivery"), "site")
        page = client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="brand-sub"', page.text)
        self.assertIn('id="drop-hint"', page.text)

    def test_site_flag_forces_delivery(self) -> None:
        from electrical_krow.gateway import listen_from_args, parse_gateway_argv

        args = parse_gateway_argv(["--site", "--host", "127.0.0.1", "--port", "18767"])
        settings, host, port, origin = listen_from_args(args)
        self.assertEqual(settings.delivery, "site")
        self.assertEqual(host, "127.0.0.1")
        self.assertEqual(port, 18767)
        self.assertEqual(origin, "http://127.0.0.1:18767")

    def test_login_then_complete(self) -> None:
        session = AuthSession(access_token="tok", username=DEMO_USER, source="password")
        result = ChatResult(
            content='{"ok":true,"rows":[]}',
            model="qwen2.5:7b",
            raw={
                "choices": [
                    {"message": {"role": "assistant", "content": '{"ok":true,"rows":[]}'}}
                ]
            },
        )
        with patch("electrical_krow.gateway.login_with_password", return_value=session):
            login = self.client.post(
                "/api/login",
                json={"username": DEMO_USER, "password": "demo"},
            )
        self.assertEqual(login.status_code, 200)
        with patch("electrical_krow.gateway.complete", return_value=result):
            chat = self.client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer local"},
                json={
                    "model": "qwen2.5:7b",
                    "messages": [
                        {"role": "system", "content": "你只输出一个 JSON 对象。"},
                        {"role": "user", "content": "hi"},
                    ],
                },
            )
        self.assertEqual(chat.status_code, 200)
        self.assertIn("rows", chat.json()["choices"][0]["message"]["content"])

    def test_chat_passes_thinking_controls_upstream(self) -> None:
        """出表只要 JSON：thinking / reasoning_effort / max_tokens 要透传到识别服务。"""
        session = AuthSession(access_token="tok", username=DEMO_USER, source="password")
        result = ChatResult(content="{}", model="deepseek-v4-pro", raw={"choices": []})
        seen: dict[str, object] = {}

        def fake_complete(_url, _auth, _messages, **kwargs):
            seen.update(kwargs)
            return result

        with patch("electrical_krow.gateway.login_with_password", return_value=session):
            self.client.post("/api/login", json={"username": DEMO_USER, "password": "demo"})
        with patch("electrical_krow.gateway.complete", side_effect=fake_complete):
            chat = self.client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer local"},
                json={
                    "model": "deepseek-v4-pro",
                    "messages": [{"role": "user", "content": "hi"}],
                    "thinking": {"type": "disabled"},
                    "reasoning_effort": "low",
                    "max_tokens": 4096,
                    "options": {"num_predict": 1536},
                },
            )
        self.assertEqual(chat.status_code, 200)
        self.assertEqual(
            seen["extra"],
            {"thinking": {"type": "disabled"}, "reasoning_effort": "low", "max_tokens": 4096},
        )
        self.assertNotIn("options", seen)

    def test_chat_refreshes_stale_key(self) -> None:
        session = AuthSession(
            access_token="sk-user-dead",
            username=DEMO_USER,
            source="password",
            raw={"jwt": "eyJmock.token"},
        )
        result = ChatResult(
            content='{"ok":true,"rows":[]}',
            model="deepseek-v4-pro",
            raw={
                "choices": [
                    {"message": {"role": "assistant", "content": '{"ok":true,"rows":[]}'}}
                ]
            },
        )
        seen: list[str] = []

        def fake_complete(_url, auth, _messages, **_kwargs):
            seen.append(auth.access_token)
            if auth.access_token == "sk-user-dead":
                raise LLMError("识别未授权（401）。请重新登录。")
            return result

        def fake_refresh(_url, auth, **_kwargs):
            return AuthSession(
                access_token="sk-user-fresh",
                username=auth.username,
                source="password",
                raw=auth.raw,
            )

        with patch("electrical_krow.gateway.login_with_password", return_value=session):
            login = self.client.post(
                "/api/login",
                json={"username": DEMO_USER, "password": "demo"},
            )
        self.assertEqual(login.status_code, 200)
        with (
            patch("electrical_krow.gateway.complete", side_effect=fake_complete),
            patch("electrical_krow.gateway.refresh_sdk_key", side_effect=fake_refresh),
        ):
            chat = self.client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer local"},
                json={
                    "model": "deepseek-v4-pro",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        self.assertEqual(chat.status_code, 200, chat.text)
        self.assertIn("sk-user-dead", seen)
        self.assertIn("sk-user-fresh", seen)

    def test_chat_stale_key_without_jwt_is_401(self) -> None:
        session = AuthSession(access_token="tok", username=DEMO_USER, source="password")
        with patch("electrical_krow.gateway.login_with_password", return_value=session):
            login = self.client.post(
                "/api/login",
                json={"username": DEMO_USER, "password": "demo"},
            )
        self.assertEqual(login.status_code, 200)

        def fake_complete(_url, _auth, _messages, **_kwargs):
            raise LLMError("识别未授权（401）。请重新登录。")

        with patch("electrical_krow.gateway.complete", side_effect=fake_complete):
            chat = self.client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer local"},
                json={
                    "model": "deepseek-v4-pro",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        self.assertEqual(chat.status_code, 401, chat.text)
        self.assertIn("重新登录", chat.json()["detail"])

    def test_complete_without_login(self) -> None:
        resp = self.client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        self.assertEqual(resp.status_code, 401)

    def test_jobs_without_login(self) -> None:
        resp = self.client.post(
            "/api/jobs",
            files={"file": ("a.txt", b"hello", "text/plain")},
        )
        self.assertEqual(resp.status_code, 401)

    def test_client_jobs_without_cookie_reuse_login(self) -> None:
        session = AuthSession(access_token="tok", username=DEMO_USER, source="password")
        with patch("electrical_krow.gateway.login_with_password", return_value=session):
            login = self.client.post(
                "/api/login",
                json={"username": DEMO_USER, "password": "demo"},
            )
        self.assertEqual(login.status_code, 200)
        self.client.cookies.clear()
        resp = self.client.post(
            "/api/jobs",
            files={"file": ("a.txt", b"hello", "text/plain")},
        )
        self.assertNotEqual(resp.status_code, 401, resp.text)

    def test_site_jobs_without_cookie_still_401(self) -> None:
        settings = load_settings(server_url="http://127.0.0.1:18766", delivery="site")
        client = TestClient(create_app(settings, output_dir=Path(self._tmp.name)))
        session = AuthSession(access_token="tok", username=DEMO_USER, source="password")
        with patch("electrical_krow.gateway.login_with_password", return_value=session):
            login = client.post(
                "/api/login",
                json={"username": DEMO_USER, "password": "demo"},
            )
        self.assertEqual(login.status_code, 200)
        client.cookies.clear()
        resp = client.post(
            "/api/jobs",
            files={"file": ("a.txt", b"hello", "text/plain")},
        )
        self.assertEqual(resp.status_code, 401)

    def test_missing_job_is_404_after_login(self) -> None:
        session = AuthSession(access_token="tok", username=DEMO_USER, source="password")
        with patch("electrical_krow.gateway.login_with_password", return_value=session):
            login = self.client.post(
                "/api/login",
                json={"username": DEMO_USER, "password": "demo"},
            )
        self.assertEqual(login.status_code, 200)
        listed = self.client.get("/api/jobs")
        self.assertEqual(listed.status_code, 200)
        self.assertIsInstance(listed.json().get("jobs"), list)
        resp = self.client.get("/api/jobs/does-not-exist")
        self.assertEqual(resp.status_code, 404)

    def test_models_require_login(self) -> None:
        resp = self.client.get("/api/models")
        self.assertEqual(resp.status_code, 401)

    def test_client_bind_rejects_all_interfaces(self) -> None:
        from electrical_krow.gateway import main as gateway_main

        settings = load_settings(
            server_url="http://127.0.0.1:18766", gateway_host="0.0.0.0"
        )
        with patch("electrical_krow.gateway.load_settings", return_value=settings):
            with patch("electrical_krow.gateway.uvicorn.run") as run:
                with self.assertRaises(SystemExit) as raised:
                    gateway_main(["--no-browser"])
        run.assert_not_called()
        self.assertIn("客户端模式", str(raised.exception))

    def test_list_and_set_model(self) -> None:
        session = AuthSession(access_token="tok", username=DEMO_USER, source="password")
        with patch("electrical_krow.gateway.login_with_password", return_value=session):
            login = self.client.post(
                "/api/login",
                json={"username": DEMO_USER, "password": "demo"},
            )
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.json().get("model"))
        with patch(
            "electrical_krow.gateway.list_models",
            return_value=["deepseek-v4-pro", "qwen-plus"],
        ):
            listed = self.client.get("/api/models")
        self.assertEqual(listed.status_code, 200)
        body = listed.json()
        self.assertIn("deepseek-v4-pro", body["models"])
        self.assertIn("qwen-plus", body["models"])
        self.assertEqual(body["recommended"], "deepseek-v4-pro")
        changed = self.client.post("/api/model", json={"model": "qwen-plus"})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json()["model"], "qwen-plus")
        sess = self.client.get("/api/session")
        self.assertEqual(sess.json()["model"], "qwen-plus")
        health = self.client.get("/api/health")
        self.assertEqual(health.json()["model"], "qwen-plus")
        bad = self.client.post("/api/model", json={"model": "bad name"})
        self.assertEqual(bad.status_code, 400)

    def test_models_replace_default_missing_from_site_list(self) -> None:
        self._login()
        with patch(
            "electrical_krow.gateway.list_models",
            return_value=["ZHIPU/GLM-5.2"],
        ):
            body = self.client.get("/api/models").json()
        self.assertEqual(body["models"], ["ZHIPU/GLM-5.2"])
        self.assertEqual(body["model"], "ZHIPU/GLM-5.2")
        self.assertEqual(self.client.get("/api/session").json()["model"], "ZHIPU/GLM-5.2")

    def test_chat_falls_back_when_model_unavailable(self) -> None:
        self._login()
        seen: list[str] = []
        ok = ChatResult(
            content='{"rows":[]}',
            model="ZHIPU/GLM-5.2",
            raw={"choices": [{"message": {"content": '{"rows":[]}'}}]},
        )

        def fake_complete(_url, _auth, _messages, **kwargs):
            name = str(kwargs.get("model") or "")
            seen.append(name)
            if name == "deepseek-v4-pro":
                raise LLMError(
                    '识别服务 HTTP 400: {"error":"This model is currently unavailable. Please try another model."}'
                )
            return ok

        with patch("electrical_krow.gateway.complete", side_effect=fake_complete):
            with patch(
                "electrical_krow.gateway.list_models",
                return_value=["deepseek-v4-pro", "ZHIPU/GLM-5.2"],
            ):
                chat = self.client.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer local"},
                    json={
                        "model": "deepseek-v4-pro",
                        "messages": [{"role": "user", "content": "hi"}],
                    },
                )
        self.assertEqual(chat.status_code, 200, chat.text)
        self.assertEqual(seen, ["deepseek-v4-pro", "ZHIPU/GLM-5.2"])
        again: list[str] = []

        def fake_again(_url, _auth, _messages, **kwargs):
            again.append(str(kwargs.get("model") or ""))
            return ok

        with patch("electrical_krow.gateway.complete", side_effect=fake_again):
            second = self.client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer local"},
                json={
                    "model": "deepseek-v4-pro",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(again, ["ZHIPU/GLM-5.2"])

    def _login(self, client: TestClient | None = None) -> TestClient:
        target = client or self.client
        session = AuthSession(access_token="tok", username=DEMO_USER, source="password")
        with patch("electrical_krow.gateway.login_with_password", return_value=session):
            login = target.post(
                "/api/login",
                json={"username": DEMO_USER, "password": "demo"},
            )
        self.assertEqual(login.status_code, 200)
        return target

    def test_health_carries_versions_for_about_page(self) -> None:
        data = self.client.get("/api/health").json()
        v = data.get("versions") or {}
        for key in ("client", "sdk", "runtime", "knowledge", "python", "platform"):
            self.assertIn(key, v)
        self.assertTrue(v["python"])
        self.assertTrue(v["client"])
        # 包内版本号与 pyproject 一致
        import re

        from electrical_krow import __version__

        pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        self.assertEqual(re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1), __version__)
        self.assertEqual(data.get("output_dir"), self._tmp.name)
        self.assertEqual(len(str(data.get("stamp") or "")), 16)

    def test_new_table_gets_a_job_before_the_file(self) -> None:
        session = AuthSession(access_token="tok", username=DEMO_USER, source="password")
        with patch("electrical_krow.gateway.login_with_password", return_value=session):
            self.client.post("/api/login", json={"username": DEMO_USER, "password": "demo"})
        opened = self.client.post(
            "/api/enterprise-test/compare",
            headers={"Authorization": "Bearer local"},
        )
        self.assertEqual(opened.status_code, 200)
        first = opened.json()
        self.assertTrue(first["job_id"])
        self.assertEqual(first["steps"]["read"], "run")
        self.assertFalse(first["done"])
        import io
        from urllib.parse import quote

        from openpyxl import Workbook

        buf = io.BytesIO()
        book = Workbook()
        book.active.append(["1.1", "新项目"])
        book.save(buf)
        book.close()
        with patch(
            "electrical_krow.gateway.compare_manual_file",
            return_value={"reply": "ok", "tables": [{"title": "对比表", "headers": [], "rows": []}], "page_note": ""},
        ), patch("electrical_krow.gateway.open_locally"):
            saved = self.client.put(
                f"/api/enterprise-test/compare/{first['job_id']}/file",
                content=buf.getvalue(),
                headers={
                    "Authorization": "Bearer local",
                    "X-Filename": quote("新表-2026.xlsx"),
                    "Content-Type": "application/octet-stream",
                },
            )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["job_id"], first["job_id"])
        self.assertEqual(saved.json()["steps"]["read"], "done")
        again = self.client.put(
            f"/api/enterprise-test/compare/{first['job_id']}/file",
            content=buf.getvalue(),
            headers={
                "Authorization": "Bearer local",
                "X-Filename": quote("新表-2026.xlsx"),
                "Content-Type": "application/octet-stream",
            },
        )
        self.assertEqual(again.status_code, 404)

    def test_empty_table_marks_the_job_failed(self) -> None:
        session = AuthSession(access_token="tok", username=DEMO_USER, source="password")
        with patch("electrical_krow.gateway.login_with_password", return_value=session):
            self.client.post("/api/login", json={"username": DEMO_USER, "password": "demo"})
        opened = self.client.post(
            "/api/enterprise-test/compare",
            headers={"Authorization": "Bearer local"},
        )
        job_id = opened.json()["job_id"]
        from urllib.parse import quote

        saved = self.client.put(
            f"/api/enterprise-test/compare/{job_id}/file",
            content=b"",
            headers={
                "Authorization": "Bearer local",
                "X-Filename": quote("空表.xlsx"),
                "Content-Type": "application/octet-stream",
            },
        )
        self.assertEqual(saved.status_code, 400)
        view = self.client.get(
            f"/api/enterprise-test/compare/{job_id}",
            headers={"Authorization": "Bearer local"},
        )
        self.assertEqual(view.status_code, 200)
        body = view.json()
        self.assertTrue(body["done"])
        self.assertIn("文件是空的", body["error"])
        self.assertTrue(any("开始读正文" in line for line in body.get("detect") or []))

    def test_intake_reads_the_table_like_other_tools(self) -> None:
        import io
        from openpyxl import Workbook

        session = AuthSession(access_token="tok", username=DEMO_USER, source="password")
        with patch("electrical_krow.gateway.login_with_password", return_value=session):
            self.client.post("/api/login", json={"username": DEMO_USER, "password": "demo"})
        buf = io.BytesIO()
        book = Workbook()
        grid = book.active
        grid.append(["序号", "试验项目", "试验标准号及名称", "目标要求"])
        grid.append(["1.1", "绝缘", "Q/JLY J7110218D-2025", "满足图纸"])
        book.save(buf)
        book.close()
        saved = self.client.post(
            "/api/enterprise-test/intake",
            files={"file": ("电机表.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers={"Authorization": "Bearer local"},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        body = saved.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["rows"], 1)
        self.assertEqual(body["name"], "电机表.xlsx")
        self.assertIn("输入完成", body["say"])
        self.assertIn("接下来打开 http://arsm.aurobaytech.com/home/index", body["say"])

    def test_local_pick_reads_both_input_tables_and_writes_the_sheet(self) -> None:
        motor = Path(r"D:\企标测试\输入条件") / "(电机DVP)DVP-001.xlsx"
        control = Path(r"D:\企标测试\输入条件") / "(电控DVP)DVP-002.xlsx"
        if not motor.is_file() or not control.is_file():
            self.skipTest("输入条件不在这台电脑上")
        session = AuthSession(access_token="tok", username=DEMO_USER, source="password")
        with patch("electrical_krow.gateway.login_with_password", return_value=session):
            self.client.post("/api/login", json={"username": DEMO_USER, "password": "demo"})
        page = self.client.get("/")
        self.assertIn("生成对比表", page.text)
        headers = {"Authorization": "Bearer local"}
        with patch("electrical_krow.gateway.open_locally"):
            self._pick_and_compare(headers, ((motor, 63), (control, 110)))

    def _pick_and_compare(self, headers: dict[str, str], tables: tuple[tuple[Path, int], ...]) -> None:
        for path, rows in tables:
            with patch("electrical_krow.gateway.pick_table_path", return_value=str(path)):
                picked = self.client.post("/api/enterprise-test/pick", headers=headers)
            self.assertEqual(picked.status_code, 200, picked.text)
            body = picked.json()
            self.assertTrue(body["ok"])
            self.assertFalse(body["cancelled"])
            self.assertEqual(body["name"], path.name)
            self.assertEqual(body["rows"], rows)
            self.assertNotIn("读不出", body["say"])
            started = self.client.post(
                "/api/enterprise-test/compare",
                headers={**headers, "X-Hold-Id": body["hold_id"]},
            )
            self.assertEqual(started.status_code, 200, started.text)
            job_id = started.json()["job_id"]
            done: dict = {}
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                view = self.client.get(f"/api/enterprise-test/compare/{job_id}", headers=headers)
                self.assertEqual(view.status_code, 200, view.text)
                done = view.json()
                if done.get("done"):
                    break
                time.sleep(0.4)
            self.assertTrue(done.get("done"), done)
            self.assertEqual(done.get("error") or "", "")
            self.assertTrue(str(done.get("reply") or "").startswith("已生成对比表"))
            self.assertIn("网址无法解析", str(done.get("page_note") or done.get("detail") or ""))

    def test_intake_accepts_a_table_larger_than_one_megabyte(self) -> None:
        import os

        session = AuthSession(access_token="tok", username=DEMO_USER, source="password")
        with patch("electrical_krow.gateway.login_with_password", return_value=session):
            self.client.post("/api/login", json={"username": DEMO_USER, "password": "demo"})
        payload = os.urandom(2 * 1024 * 1024)
        saved = self.client.post(
            "/api/enterprise-test/intake",
            files={"file": ("电控表.xlsx", payload, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers={"Authorization": "Bearer local"},
        )
        self.assertNotIn("没有收到测试表文件", saved.text)
        self.assertNotIn("Part exceeded", saved.text)
        self.assertNotIn("maximum size", saved.text)
        self.assertEqual(saved.status_code, 400, saved.text)

    def test_detect_log_records_the_job_and_a_page_line(self) -> None:
        session = AuthSession(access_token="tok", username=DEMO_USER, source="password")
        with patch("electrical_krow.gateway.login_with_password", return_value=session):
            self.client.post("/api/login", json={"username": DEMO_USER, "password": "demo"})
        log_path = Path(self._tmp.name) / "企标检测日志.txt"
        with patch("electrical_krow.gateway.etest_detect_path", return_value=log_path):
            opened = self.client.post(
                "/api/enterprise-test/compare",
                headers={"Authorization": "Bearer local"},
            )
            noted = self.client.post(
                "/api/enterprise-test/detect",
                headers={"Authorization": "Bearer local"},
                json={"line": "停在接收测试表"},
            )
        self.assertEqual(opened.status_code, 200)
        self.assertTrue(any("event=job" in line for line in opened.json().get("detect") or []))
        self.assertEqual(noted.status_code, 200)
        text = log_path.read_text(encoding="utf-8")
        self.assertIn("event=job", text)
        self.assertIn("message=停在接收测试表", text)
        self.assertNotIn("password", text)

    def test_new_run_overwrites_the_previous_detect_log(self) -> None:
        session = AuthSession(access_token="tok", username=DEMO_USER, source="password")
        with patch("electrical_krow.gateway.login_with_password", return_value=session):
            self.client.post("/api/login", json={"username": DEMO_USER, "password": "demo"})
        log_path = Path(self._tmp.name) / "企标检测日志.txt"
        log_path.write_text("2026-11-19 旧的一次使用\n", encoding="utf-8")
        with patch("electrical_krow.gateway.etest_detect_path", return_value=log_path):
            noted = self.client.post(
                "/api/enterprise-test/detect",
                headers={"Authorization": "Bearer local", "X-Etest-Reset": "1"},
                json={"line": "side=page event=start step=read say=本次使用"},
            )
        self.assertEqual(noted.status_code, 200)
        text = log_path.read_text(encoding="utf-8")
        self.assertNotIn("旧的一次使用", text)
        self.assertIn("本次使用", text)

    def test_health_carries_workbench_summary_numbers_only(self) -> None:
        """工作台统计卡 / 知识库摘要卡：只有版本与数量，不带条目内容或源文件。"""
        data = self.client.get("/api/health").json()
        kb = data.get("knowledge") or {}
        self.assertTrue(kb.get("version"))
        for key in ("clauses", "physics", "enterprise", "groups"):
            self.assertIsInstance(kb.get(key), int)
        self.assertGreater(kb["clauses"], 100)
        self.assertNotIn("clauses_list", kb)
        self.assertFalse(any(isinstance(v, (list, dict)) for v in kb.values()))
        self.assertIsInstance(data.get("pending_rulings"), int)

    def test_workbench_and_result_summary_markup(self) -> None:
        """工作台只留 SOR 出表一张卡；出表相关（一行统计、最近核对表、体检卡、实时计数、分组条形）都在出表页，嵌入时才看得到。"""
        page = self.client.get("/").text
        for marker in (
            'id="work-meta"', 'id="work-recent"', 'id="work-recent-list"', 'id="work-open-dir"',
            'id="file-info"', 'id="live"',
        ):
            self.assertIn(marker, page)
        for gone in ('id="home-stats"', 'id="home-recent"', 'id="home-open-dir"', 'id="home-flow"', 'id="home-kb"'):
            self.assertNotIn(gone, page)
        home = page[page.index('id="home-card"'):page.index('id="arch-card"')]
        self.assertEqual(home.count('class="fn-card'), 5)
        self.assertIn('data-go="icd"', home)
        self.assertIn("ICD 规划", home)
        self.assertIn('data-go="bom"', home)
        self.assertIn("CE BOM 输出", home)
        self.assertIn("进入出表", home)
        self.assertIn("HSI生成", home)
        self.assertIn('data-go="io"', home)
        self.assertIn('data-go="arch"', home)
        self.assertIn("电驱需求拆解", home)
        self.assertIn('id="io-card"', page)
        self.assertIn('id="icd-card"', page)
        self.assertIn('id="rail-icd"', page)
        self.assertIn('id="icd-file"', page)
        self.assertIn('id="bom-card"', page)
        self.assertIn('id="rail-bom"', page)
        self.assertIn("电子件用 AD 导出的 BOM", page)
        self.assertIn('id="bom-previous"', page)
        self.assertNotIn('id="bom-template"', page)
        self.assertIn('id="arch-card"', page)
        self.assertIn('id="arch-files"', page)
        self.assertIn("multiple", page[page.index('id="arch-files"'):page.index('id="arch-files"') + 120])
        self.assertIn('id="rail-arch"', page)
        self.assertIn('id="rail-tab-arch"', page)
        self.assertIn('id="rail-tab-icd"', page)
        self.assertIn('id="rail-tab-bom"', page)
        self.assertIn('id="icd-list"', page)
        self.assertIn('id="bom-list"', page)
        self.assertIn('id="arch-list"', page)
        self.assertNotIn("上传规格书", home)
        self.assertNotIn('id="home-foot"', page)
        self.assertEqual(home.count("禁止用库填数"), 0)
        self.assertNotIn("规则先填，模型只补空缺。抽出值只来自当份规格书", home)
        self.assertNotIn("home.cardBody", home)
        self.assertIn("自动从 SOR 抽取内容。", home)
        self.assertIn("文档", home)
        self.assertIn("标准", home)
        self.assertNotIn("人工确认后定稿", home)
        # 最近核对表在 work-card 内、result 之后
        work = page.index('id="work-card"')
        self.assertLess(page.index('id="result"'), page.index('id="work-recent"'))
        self.assertLess(work, page.index('id="work-recent"'))
        self.assertLess(page.index('id="work-recent"'), page.index('id="kb-card"'))
        js = self.client.get("/static/app.js").text
        i18n = self.client.get("/static/i18n.js").text
        for marker in (
            "/api/inspect", "renderHome", "renderRecent", "workMetaText", "groupBarsMarkup", "compareMarkup",
            "liveLine", "chunk_done", "pending_note", "kindTag",
            'tx("stat.pending")', 'tx("compare.head")', "/api/output/open",
        ):
            self.assertIn(marker, js)
        self.assertIn("待专家口径", i18n)
        self.assertIn("与上次同名文件对比", i18n)
        self.assertNotIn("homeStatCards", js)
        self.assertIn("title='", js)
        self.assertIn("function goExtract", js)
        self.assertIn("function clearExtractOutcome", js)
        self.assertIn("rail-extract\").onclick = () => goExtract({ clearFile: true })", js)
        self.assertNotIn("rail-new", js)
        self.assertIn("/api/arch", js)
        self.assertIn("function renderArch", js)
        # 一次选一个也能攒成一批：自己累积，不靠原生文件框
        self.assertIn("function addArchFiles", js)
        self.assertIn("function removeArchFile", js)
        # 两份以上可一键清空；按钮在 label 里，须拦住默认的弹出选择
        self.assertIn("function clearArchFiles", js)
        self.assertIn('id="arch-clear"', page)
        self.assertIn("setRailRecordTab(\"arch\")", js)
        self.assertIn("openHistory", js)
        css = self.client.get("/static/styles.css").text
        for marker in (".work-meta", ".work-recent", ".recent-row", ".file-info", ".gbar-track", ".compare", ".job-tag", ".live"):
            self.assertIn(marker, css)
        self.assertNotIn(".home-stat", css)
        self.assertNotIn(".flow-step", css)
        self.assertNotIn(".home-foot", css)
        self.assertIn(".job-copy", css)
        self.assertIn(".job-meta-text", css)
        self.assertIn("line-height: 1.35", css)
        self.assertIn("class='job-copy'", js)

    def test_io_sheet_opens_blank_workbook(self) -> None:
        self._login()
        with patch("electrical_krow.gateway.open_locally") as opened:
            resp = self.client.post("/api/io-sheet")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["name"], "IO口初始配置表.xlsx")
        path = Path(self._tmp.name) / "IO口初始配置表.xlsx"
        self.assertTrue(path.is_file())
        opened.assert_called_once()
        from openpyxl import load_workbook

        book = load_workbook(path, data_only=True)
        try:
            rows = list(book["IO口初始配置表"].iter_rows(values_only=True))
        finally:
            book.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "手册引脚号")
        self.assertEqual(rows[0][6], "端口名")

    def test_hsi_route_copies_built_workbook(self) -> None:
        from electrical_krow.hsi_book import DEFAULT_HSI_TEMPLATE, HsiResult

        self._login()
        seen = {}

        def fake_build(template, datasheet, dest, package="", previous=None, ask=None, on_progress=None, schematic=None, mcu=""):
            seen["template"] = Path(template)
            seen["ask"] = ask
            dest = Path(dest)
            dest.write_bytes(b"hsi-bytes")
            return HsiResult(dest, "TC38x", "BGA516", "TC38x-BGA516-1", 2, 0)

        with patch("electrical_krow.gateway.build_hsi", side_effect=fake_build), patch(
            "electrical_krow.gateway.open_locally"
        ) as opened:
            resp = self.client.post(
                "/api/hsi",
                data={"package": "BGA516"},
                files={
                    "datasheet": ("infineon-tc38x-datasheet-en.pdf", b"%PDF-1.4", "application/pdf"),
                },
            )
        self.assertEqual(seen["template"], DEFAULT_HSI_TEMPLATE)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["version"], "TC38x-BGA516-1")
        self.assertEqual(resp.json()["changes"], 0)
        # 没带上一版：页面据此说「没有上一版」，而不是「无差异」
        self.assertIs(resp.json()["previous"], False)
        from datetime import date

        stamp = date.today().strftime("%Y%m%d")
        self.assertEqual(resp.json()["download"], f"/files/HSI-TC38x-BGA516-1-{stamp}.xlsx")
        got = self.client.get(resp.json()["download"])
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.content, b"hsi-bytes")
        saved = Path(self._tmp.name) / f"HSI-TC38x-BGA516-1-{stamp}.xlsx"
        self.assertEqual(saved.read_bytes(), b"hsi-bytes")
        opened.assert_called_once()
        history = self.client.get("/api/hsi/history")
        self.assertEqual(history.status_code, 200, history.text)
        names = [row.get("source") for row in history.json()["records"]]
        self.assertIn(f"HSI-TC38x-BGA516-1-{stamp}.xlsx", names)
        self.assertIs(history.json()["records"][0]["previous"], False)
        # 带了上一版且 0 条差异：previous 为真，变更表留空但不是「没有上一版」
        with patch("electrical_krow.gateway.build_hsi", side_effect=fake_build), patch(
            "electrical_krow.gateway.open_locally"
        ):
            again = self.client.post(
                "/api/hsi",
                data={"package": "BGA516"},
                files={
                    "datasheet": ("infineon-tc38x-datasheet-en.pdf", b"%PDF-1.4", "application/pdf"),
                    "previous": ("HSI-TC38x-BGA516-1.xlsx", b"PK\x03\x04", "application/octet-stream"),
                },
            )
        self.assertEqual(again.status_code, 200, again.text)
        self.assertIs(again.json()["previous"], True)
        self.assertEqual(again.json()["changes"], 0)
        self.assertIs(self.client.get("/api/hsi/history").json()["records"][0]["previous"], True)

    def test_hsi_progress_moves_and_closes_when_done(self) -> None:
        from electrical_krow.hsi_book import HsiResult
        from electrical_krow import gateway as gw

        self._login()
        job = "hsi-job-1"
        seen: dict[str, object] = {}

        def fake_build(template, datasheet, dest, package="", previous=None, ask=None, on_progress=None, schematic=None, mcu=""):
            self.assertTrue(callable(on_progress))
            on_progress(48, "pins", "2")
            with gw._HSI_PROGRESS_LOCK:
                seen["mid"] = dict(gw._HSI_PROGRESS[job])
            dest = Path(dest)
            dest.write_bytes(b"hsi-bytes")
            return HsiResult(dest, "TC38x", "BGA516", "TC38x-BGA516-1", 2, 0)

        with patch("electrical_krow.gateway.build_hsi", side_effect=fake_build), patch(
            "electrical_krow.gateway.open_locally"
        ):
            resp = self.client.post(
                "/api/hsi",
                data={"package": "BGA516"},
                files={"datasheet": ("tc38x.pdf", b"%PDF-1.4", "application/pdf")},
                headers={"X-Hsi-Progress": job},
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(seen["mid"], {"percent": 48, "stage": "pins", "detail": "2", "done": False})
        done = self.client.get(f"/api/hsi/progress/{job}")
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(done.json(), {"percent": 100, "stage": "write", "detail": "", "done": True})
        missing = self.client.get("/api/hsi/progress/missing")
        self.assertEqual(missing.json(), {"percent": 0, "stage": "read", "detail": "", "done": False})
        page = self.client.get("/").text
        js = self.client.get("/static/app.js").text
        i18n = self.client.get("/static/i18n.js").text
        self.assertIn('id="io-progress"', page)
        self.assertIn("/api/hsi/progress/", js)
        self.assertIn("X-Hsi-Progress", js)
        self.assertIn("payload.done", js)
        self.assertIn("正在读取手册 {detail}", i18n)
        self.assertIn("正在读取网表 {detail}", i18n)
        self.assertIn("正在核对约束 {detail}", i18n)

        def fail_build(template, datasheet, dest, package="", previous=None, ask=None, on_progress=None, mcu=""):
            on_progress(12, "read", "1/4")
            raise ValueError("手册中没有读到封装引脚表。")

        with patch("electrical_krow.gateway.build_hsi", side_effect=fail_build), patch(
            "electrical_krow.gateway.open_locally"
        ):
            bad = self.client.post(
                "/api/hsi",
                data={"package": "BGA516"},
                files={"datasheet": ("tc38x.pdf", b"%PDF-1.4", "application/pdf")},
                headers={"X-Hsi-Progress": "hsi-job-bad"},
            )
        self.assertEqual(bad.status_code, 400, bad.text)
        closed = self.client.get("/api/hsi/progress/hsi-job-bad")
        self.assertEqual(closed.json()["done"], True)

    def test_arch_route_builds_contrast_and_records_history(self) -> None:
        from electrical_krow.arch_contrast import ContrastResult, Unreadable

        self._login()
        seen: dict[str, object] = {}

        def fake_build(sources, dest, ask=None, on_progress=None):
            if on_progress:
                on_progress(40, "tables", "260605_LDC_SR.pdf 1/2")
            seen["names"] = [Path(p).name for p in sources]
            seen["ask"] = ask
            dest = Path(dest)
            dest.write_bytes(b"arch-bytes")
            return ContrastResult(dest, 1, 51, 2, (Unreadable("BHDC.pdf", 67, "没有文字层"),), params=40, conflicts=3, model_used=True)

        with patch("electrical_krow.gateway.build_contrast", side_effect=fake_build), patch(
            "electrical_krow.gateway.open_locally"
        ) as opened:
            resp = self.client.post(
                "/api/arch",
                files=[
                    ("files", ("260605_LDC_SR.pdf", b"%PDF-1.4", "application/pdf")),
                    ("files", ("BHDC.pdf", b"%PDF-1.4", "application/pdf")),
                ],
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        # 文件名原样进对照稿，不带上传序号
        self.assertEqual(seen["names"], ["260605_LDC_SR.pdf", "BHDC.pdf"])
        data = resp.json()
        self.assertTrue(data["name"].startswith("架构对照-"))
        self.assertTrue(data["name"].startswith("架构对照-260605_LDC_SR+BHDC-"))
        self.assertTrue(data["name"].endswith(".xlsx"))
        self.assertEqual((data["params"], data["conflicts"], data["model_used"]), (40, 3, True))
        self.assertEqual((data["image_tables"], data["figures"], data["reqs"], data["shots"]), (0, 0, 0, 0))
        self.assertTrue(callable(seen["ask"]))  # 参数指认走网关的模型通道，不在出表模块里建会话
        self.assertEqual(data["unreadable"][0]["name"], "BHDC.pdf")
        got = self.client.get(data["download"])
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.content, b"arch-bytes")
        opened.assert_called_once()
        history = self.client.get("/api/arch/history")
        self.assertEqual(history.status_code, 200, history.text)
        names = [row.get("source") for row in history.json()["records"]]
        self.assertIn(data["name"], names)
        self.assertEqual(history.json()["records"][0]["rows"], 51)
        # 不进 SOR 出表记录
        jobs = [row.get("source") for row in self.client.get("/api/jobs").json()["jobs"]]
        self.assertNotIn(data["name"], jobs)
        bad = self.client.post(
            "/api/arch",
            files=[("files", ("sr.pptx", b"SCDSA004", "application/octet-stream"))],
        )
        self.assertEqual(bad.status_code, 400)
        self.assertIn("PDF", bad.json()["detail"])

    def test_hsi_packages_route_lists_packages(self) -> None:
        self._login()
        with patch(
            "electrical_krow.gateway.packages_in_pdf",
            return_value=("LFBGA516", "LFBGA292"),
        ):
            resp = self.client.post(
                "/api/hsi/packages",
                files={
                    "datasheet": (
                        "Infineon-TC39x-DataSheet-v01_02-EN.pdf",
                        b"%PDF-1.4",
                        "application/pdf",
                    ),
                },
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["mcu"], "TC39x")
        self.assertEqual(resp.json()["packages"], ["LFBGA516", "LFBGA292"])
        page = self.client.get("/")
        self.assertIn('id="io-package-choices"', page.text)
        self.assertIn("/api/hsi/packages", self.client.get("/static/app.js").text)
        empty = None
        with patch("electrical_krow.gateway.packages_in_pdf", return_value=()):
            empty = self.client.post(
                "/api/hsi/packages",
                files={
                    "datasheet": (
                        "Infineon-TC39x-DataSheet-v01_02-EN.pdf",
                        b"%PDF-1.4",
                        "application/pdf",
                    ),
                },
            )
        self.assertEqual(empty.status_code, 400)

    def test_hsi_templates_listed_and_schematic_requires_one(self) -> None:
        from electrical_krow.hsi_book import HsiResult, hsi_template_for_schematic

        listed = self.client.get("/api/hsi/templates")
        self.assertEqual(listed.status_code, 200, listed.text)
        rows = listed.json()["templates"]
        self.assertEqual([row["id"] for row in rows], ["TC499", "TC387", "TC399"])
        self.assertEqual(listed.json()["default"], "TC499")
        page = self.client.get("/")
        self.assertIn('id="io-template-choices"', page.text)
        self.assertIn('id="io-template"', page.text)
        js = self.client.get("/static/app.js").text
        self.assertIn("/api/hsi/templates", js)
        self.assertIn("template_id", js)
        self._login()
        missing = self.client.post(
            "/api/hsi",
            data={"mode": "schematic"},
            files={"schematic": ("board.edf", b"(edif demo)", "application/octet-stream")},
        )
        self.assertEqual(missing.status_code, 400)
        self.assertIn("模板", missing.json()["detail"])
        seen = {}

        def fake_revise(base, dest, schematic, *, on_progress=None):
            seen["base"] = Path(base)
            dest = Path(dest)
            dest.write_bytes(b"sch-hsi")
            return HsiResult(dest, "TC499", "", "", 2, 0, schematic_updates=2)

        with patch("electrical_krow.gateway.revise_hsi_from_schematic", side_effect=fake_revise), patch(
            "electrical_krow.gateway.open_locally"
        ):
            ok = self.client.post(
                "/api/hsi",
                data={"mode": "schematic", "template_id": "TC499"},
                files={"schematic": ("board.edf", b"(edif demo)", "application/octet-stream")},
            )
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(seen["base"], SCHEMATIC_HSI_TEMPLATE)
        self.assertEqual(ok.json()["schematic_updates"], 2)

    def test_inspect_requires_login_and_reports_type_pages_estimate(self) -> None:
        from electrical_krow.mock_server import DEMO_USER

        pdf = self._tiny_pdf()
        resp = self.client.post("/api/inspect", files={"file": ("x.pdf", pdf, "application/pdf")})
        self.assertEqual(resp.status_code, 401)
        session = AuthSession(access_token="tok", username=DEMO_USER, source="password")
        with patch("electrical_krow.gateway.login_with_password", return_value=session):
            self.client.post("/api/login", json={"username": DEMO_USER, "password": "demo"})
        bad = self.client.post("/api/inspect", files={"file": ("x.bin", b"xx", "application/octet-stream")})
        self.assertEqual(bad.status_code, 400)
        resp = self.client.post("/api/inspect", files={"file": ("spec.pdf", pdf, "application/pdf")})
        self.assertEqual(resp.status_code, 200, resp.text)
        info = resp.json()
        self.assertEqual(info["page_count"], 1)
        self.assertEqual(info["size"], len(pdf))
        self.assertIn("kind_label", info)
        self.assertIn("likely_scan", info)
        # 没有历史就不估时，不编数字
        self.assertEqual(info["estimate_n"], 0)
        self.assertEqual(info["estimate_seconds"], 0)

    def test_oversize_upload_is_rejected(self) -> None:
        self._login()
        payload = b"0123456789"
        with patch("electrical_krow.paths.MAX_BYTES", 4), patch("electrical_krow.paths.MAX_MB", 0):
            inspect = self.client.post(
                "/api/inspect",
                files={"file": ("a.pdf", payload, "application/pdf")},
            )
            job = self.client.post(
                "/api/jobs",
                files={"file": ("a.pdf", payload, "application/pdf")},
                data={"thinking": "off"},
            )
        self.assertEqual(inspect.status_code, 400)
        self.assertEqual(job.status_code, 400)
        self.assertIn("超过", inspect.text)

    def test_digital_job_skips_remote_ocr_probe(self) -> None:
        self._login()
        pdf = self._tiny_pdf()
        with patch.object(self.client.app.state.jobs, "start", return_value="job1"):
            with patch("electrical_krow.gateway.prepare_page_ocr") as ocr:
                with patch("electrical_krow.gateway.prepare_page_vision") as vision:
                    resp = self.client.post(
                        "/api/jobs",
                        files={"file": ("spec.pdf", pdf, "application/pdf")},
                        data={"thinking": "off"},
                    )
        self.assertEqual(resp.status_code, 200, resp.text)
        ocr.assert_not_called()
        vision.assert_not_called()
        self.assertEqual(os.environ.get("SPEC_SHEET_PAGE_OCR"), "0")
        os.environ.pop("SPEC_SHEET_PAGE_OCR", None)

    @staticmethod
    def _tiny_pdf() -> bytes:
        import fitz

        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "XCM DPR 电控 P1逆变器 额定功率 120 kW " * 8)
        data = doc.tobytes()
        doc.close()
        return data

    def test_jobs_thinking_flag_sets_env_and_rejects_bad_value(self) -> None:
        """/api/jobs 表单 thinking：off/空关掉推理；on 才走上游默认。"""
        self._login()
        os.environ.pop("SPEC_SHEET_LLM_THINKING", None)
        bad = self.client.post(
            "/api/jobs",
            files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")},
            data={"thinking": "maybe"},
        )
        self.assertEqual(bad.status_code, 400)
        seen: list[tuple[str, str | None]] = []

        def fake_start(filename, incoming, out, *, model="", username="", thinking=""):
            seen.append((thinking, os.environ.get("SPEC_SHEET_LLM_THINKING")))
            return "job1"

        with patch.object(self.client.app.state.jobs, "start", side_effect=fake_start):
            with patch("electrical_krow.gateway.prepare_page_ocr", return_value=False):
                with patch("electrical_krow.gateway.prepare_page_vision", return_value=""):
                    for mode in ("off", "on", ""):
                        resp = self.client.post(
                            "/api/jobs",
                            files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")},
                            data={"thinking": mode},
                        )
                        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(seen, [("off", "disabled"), ("on", None), ("", "disabled")])
        os.environ.pop("SPEC_SHEET_LLM_THINKING", None)

    def test_open_file_locally_only_inside_output_dir(self) -> None:
        self._login()
        sheet = Path(self._tmp.name) / "X_DPR_核对表.xlsx"
        sheet.write_bytes(b"PK")
        with patch("electrical_krow.gateway.open_locally") as opened:
            ok = self.client.post(f"/api/files/{sheet.name}/open")
            self.assertEqual(ok.status_code, 200, ok.text)
            self.assertEqual(ok.json()["name"], sheet.name)
            opened.assert_called_once()
            self.assertEqual(opened.call_args.args[0], sheet.resolve())
            missing = self.client.post("/api/files/nope.xlsx/open")
            self.assertEqual(missing.status_code, 404)
            escape = self.client.post("/api/files/..%2Fetc%2Fpasswd/open")
            self.assertIn(escape.status_code, (404, 400, 422))
        self.assertEqual(opened.call_count, 1)

    def test_open_output_dir_opens_output_root(self) -> None:
        self.assertEqual(self.client.post("/api/output/open").status_code, 401)
        self._login()
        with patch("electrical_krow.gateway.open_locally") as opened:
            resp = self.client.post("/api/output/open")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(Path(resp.json()["path"]).resolve(), Path(self._tmp.name).resolve())
        opened.assert_called_once()
        self.assertEqual(Path(opened.call_args.args[0]).resolve(), Path(self._tmp.name).resolve())

    def test_open_file_requires_login(self) -> None:
        resp = self.client.post("/api/files/a.xlsx/open")
        self.assertEqual(resp.status_code, 401)

    def test_logout_clears_session(self) -> None:
        self._login()
        sess = self.client.get("/api/session")
        self.assertTrue(sess.json().get("logged_in"))
        self.assertTrue(sess.json().get("username"))
        with patch("electrical_krow.gateway.revoke_sdk_key"):
            out = self.client.post("/api/logout", json={})
        self.assertEqual(out.status_code, 200)
        sess = self.client.get("/api/session")
        self.assertFalse(sess.json().get("logged_in"))
        self.assertNotIn("username", sess.json())

    def test_cloud_rejects_page_image(self) -> None:
        settings = load_settings(server_url="https://api.krow.cn")
        client = TestClient(create_app(settings, output_dir=Path(self._tmp.name)))
        self._login(client)
        chat = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer local"},
            json={
                "model": "deepseek-v4-pro",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "读图"},
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64,aaa"},
                            },
                        ],
                    }
                ],
            },
        )
        self.assertEqual(chat.status_code, 403, chat.text)
        self.assertIn("公网", chat.json().get("detail") or "")

    def test_site_forwards_page_image_to_vision_model(self) -> None:
        settings = load_settings(
            server_url="https://rdapi.aurobaytech-t.com",
            vision_model="krow-ocr-table",
            chat_model="deepseek-v4-pro",
        )
        client = TestClient(create_app(settings, output_dir=Path(self._tmp.name)))
        self._login(client)
        seen: dict[str, object] = {}
        result = ChatResult(
            content="HVDC bus voltage 380 V",
            model="krow-ocr-table",
            raw={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "HVDC bus voltage 380 V",
                        }
                    }
                ]
            },
        )

        def fake_complete(_url, _auth, messages, **kwargs):
            seen["model"] = kwargs.get("model")
            seen["messages"] = messages
            return result

        with patch("electrical_krow.gateway.complete", side_effect=fake_complete):
            chat = client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer local"},
                json={
                    "model": "deepseek-v4-pro",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "读图"},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": "data:image/png;base64,aaa"},
                                },
                            ],
                        }
                    ],
                },
            )
        self.assertEqual(chat.status_code, 200, chat.text)
        self.assertEqual(seen.get("model"), "krow-ocr-table")
        from electrical_krow.vision import message_has_image

        self.assertTrue(message_has_image(seen["messages"]))

    def test_site_text_chat_without_vision_rejects_image(self) -> None:
        settings = load_settings(
            server_url="https://rdapi.aurobaytech-t.com",
            vision_model="",
            chat_model="deepseek-v4-pro",
        )
        client = TestClient(create_app(settings, output_dir=Path(self._tmp.name)))
        self._login(client)
        extra = {"SPEC_SHEET_VISION_MODEL": "", "SPEC_SHEET_PAGE_VISION": "0"}
        with patch.dict("os.environ", extra, clear=False):
            import os

            os.environ.pop("SPEC_SHEET_VISION_MODEL", None)
            chat = client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer local"},
                json={
                    "model": "ZHIPU/GLM-5.2",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "读图"},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": "data:image/png;base64,aaa"},
                                },
                            ],
                        }
                    ],
                },
            )
        self.assertEqual(chat.status_code, 400, chat.text)

    def test_cloud_ocr_forwards_page_image(self) -> None:
        settings = load_settings(server_url="https://api.krow.cn")
        client = TestClient(create_app(settings, output_dir=Path(self._tmp.name)))
        self._login(client)
        with patch(
            "electrical_krow.gateway.recognize_page",
            return_value={
                "success": True,
                "text": "HVDC bus voltage 380 V",
                "pages": [],
                "task": "table",
                "error": None,
                "model": "krow-ocr-table",
            },
        ) as ocr:
            resp = client.post(
                "/v1/ocr",
                headers={"Authorization": "Bearer local"},
                json={
                    "task": "table",
                    "image": "data:image/jpeg;base64,aGVsbG8=",
                },
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("380", resp.json()["text"])
        ocr.assert_called_once()
        args, kwargs = ocr.call_args
        self.assertEqual(args[0], "https://api.krow.cn")
        self.assertEqual(kwargs.get("task") or "table", "table")

    def test_ocr_without_login(self) -> None:
        resp = self.client.post(
            "/v1/ocr",
            json={"task": "table", "image": "data:image/jpeg;base64,aGVsbG8="},
        )
        self.assertEqual(resp.status_code, 401)

    def test_knowledge_requires_login_and_hides_files(self) -> None:
        denied = self.client.get("/api/knowledge")
        self.assertEqual(denied.status_code, 401)
        self._login()
        resp = self.client.get("/api/knowledge")
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertFalse(data.get("fill_from_kb"))
        self.assertTrue(data.get("version"))
        self.assertGreaterEqual(len(data.get("clauses") or []), 116)
        arch = self.client.get("/api/knowledge?library=arch")
        self.assertEqual(arch.status_code, 200, arch.text)
        arch_data = arch.json()
        self.assertEqual(arch_data.get("kind"), "arch")
        self.assertFalse(arch_data.get("fill_from_kb"))
        self.assertEqual((arch_data.get("stats") or {}).get("retrieve"), 0)
        hsi = self.client.get("/api/knowledge?library=hsi")
        self.assertEqual(hsi.status_code, 200, hsi.text)
        self.assertEqual(hsi.json().get("kind"), "hsi")
        self.assertFalse(hsi.json().get("fill_from_kb"))
        blob = json.dumps(data, ensure_ascii=False)
        self.assertNotIn(".yaml", blob)
        self.assertNotIn("docs/clause", blob)
        self.assertNotIn("physics.yaml", blob)

    def _env_client(self, server_url: str) -> tuple[TestClient, Path]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        extra = {"ELECTRICAL_KROW_DATA": str(root)}
        patcher = patch.dict(os.environ, extra, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        settings = load_settings(server_url=server_url)
        client = TestClient(create_app(settings, output_dir=root))
        return client, root

    def test_switch_environment_updates_health_and_logs_out(self) -> None:
        client, raw = self._env_client("http://127.0.0.1:18766")
        self._login(client)
        with patch("electrical_krow.gateway.revoke_sdk_key"):
            resp = client.post("/api/settings", json={"id": "site"})
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertTrue(data.get("changed"))
        self.assertEqual(data.get("id"), "site")
        self.assertEqual(data.get("server"), SITE_API_URL)
        self.assertFalse(data.get("logged_in"))
        health = client.get("/api/health").json()
        self.assertEqual(health.get("server"), SITE_API_URL)
        self.assertEqual(health.get("environment"), "site")
        self.assertEqual(health.get("environment_label"), "现场识别")
        self.assertFalse(client.get("/api/session").json().get("logged_in"))
        overlay = raw / "server_env.json"
        self.assertTrue(overlay.is_file())
        with patch("electrical_krow.gateway.revoke_sdk_key"):
            again = client.post("/api/settings", json={"id": "cloud"})
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json().get("server"), CLOUD_API_URL)
        self.assertEqual(client.get("/api/health").json().get("environment"), "cloud")

    def test_switch_environment_rejects_unknown_and_busy(self) -> None:
        client, _raw = self._env_client("http://127.0.0.1:18766")
        bad = client.post("/api/settings", json={"id": "https://evil.example"})
        self.assertEqual(bad.status_code, 400)
        empty = client.post("/api/settings", json={"id": ""})
        self.assertEqual(empty.status_code, 400)
        with patch.object(client.app.state.jobs, "busy", return_value=True):
            busy = client.post("/api/settings", json={"id": "site"})
        self.assertEqual(busy.status_code, 409)

    def test_same_environment_does_not_logout(self) -> None:
        client, _raw = self._env_client(CLOUD_API_URL)
        self._login(client)
        resp = client.post("/api/settings", json={"id": "cloud"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertFalse(resp.json().get("changed"))
        self.assertTrue(client.get("/api/session").json().get("logged_in"))

    def test_site_pack_cannot_switch_to_cloud(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        ini = root / "config.ini"
        ini.write_text(
            "[krow]\n"
            f"server_url = {SITE_API_URL}\n"
            "lock_environment = true\n",
            encoding="utf-8",
        )
        extra = {
            "ELECTRICAL_KROW_CONFIG": str(ini),
            "ELECTRICAL_KROW_DATA": str(root),
        }
        patcher = patch.dict(os.environ, extra, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("KROW_SERVER_URL", None)
        settings = load_settings()
        client = TestClient(create_app(settings, output_dir=root))
        data = client.get("/api/settings").json()
        self.assertTrue(data.get("environment_locked"))
        self.assertEqual([item["id"] for item in data.get("environments") or []], ["site"])
        self.assertTrue(client.get("/api/health").json().get("environment_locked"))
        denied = client.post("/api/settings", json={"id": "cloud"})
        self.assertEqual(denied.status_code, 403)
        self.assertIn("现场识别", denied.json().get("detail") or "")
        self.assertEqual(client.get("/api/health").json().get("server"), SITE_API_URL)


if __name__ == "__main__":
    unittest.main()
