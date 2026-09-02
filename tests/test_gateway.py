from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from electrical_krow.config import load_settings
from electrical_krow.gateway import create_app
from electrical_krow.llm import ChatResult
from electrical_krow.login import AuthSession
from electrical_krow.mock_server import DEMO_USER


class GatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings(server_url="http://127.0.0.1:18766")
        self.client = TestClient(create_app(self.settings))

    def test_index(self) -> None:
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("SOR填表", resp.text)
        self.assertIn("开始出表", resp.text)
        self.assertIn("识别模型", resp.text)
        self.assertIn("规则先填，模型只补空缺项", resp.text)
        self.assertIn("按模板写出页码与原文摘录", resp.text)
        self.assertIn("step-desc", resp.text)
        self.assertIn('id="model"', resp.text)
        self.assertIn("/static/app.js", resp.text)

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
        self.assertIn("上传到本场所服务器", js.text)
        self.assertIn("文件只在本机读取", js.text)
        self.assertIn("save_sheet", js.text)
        self.assertIn("download", js.text)
        self.assertIn("局部对应", js.text)
        self.assertIn("未检索到", js.text)
        self.assertNotIn("coverage_note", js.text)
        self.assertNotIn("不按数字稿约五分钟", js.text)

    def test_health(self) -> None:
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("ok", data)
        self.assertTrue(data.get("fill"))
        self.assertTrue(data.get("model"))
        self.assertEqual(data.get("delivery"), "client")
        self.assertFalse(data.get("busy"))

    def test_site_health_copy(self) -> None:
        settings = load_settings(
            server_url="http://127.0.0.1:18766", delivery="site"
        )
        client = TestClient(create_app(settings))
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
        client = TestClient(create_app(settings))
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
        changed = self.client.post("/api/model", json={"model": "qwen-plus"})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json()["model"], "qwen-plus")
        sess = self.client.get("/api/session")
        self.assertEqual(sess.json()["model"], "qwen-plus")
        health = self.client.get("/api/health")
        self.assertEqual(health.json()["model"], "qwen-plus")
        bad = self.client.post("/api/model", json={"model": "bad name"})
        self.assertEqual(bad.status_code, 400)

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

    def test_cloud_rejects_page_image(self) -> None:
        settings = load_settings(server_url="https://api.krow.cn")
        client = TestClient(create_app(settings))
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
        client = TestClient(create_app(settings))
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
        client = TestClient(create_app(settings))
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
        client = TestClient(create_app(settings))
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


if __name__ == "__main__":
    unittest.main()
