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

    def test_health(self) -> None:
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("ok", resp.json())

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


if __name__ == "__main__":
    unittest.main()
