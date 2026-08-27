from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from electrical_krow.mock_server import DEMO_TOKEN, create_app


class LlmTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def test_chat_needs_auth(self) -> None:
        resp = self.client.post(
            "/v1/chat/completions",
            json={"model": "qwen2.5:7b", "messages": [{"role": "user", "content": "hi"}]},
        )
        self.assertEqual(resp.status_code, 401)

    def test_chat_ok(self) -> None:
        resp = self.client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEMO_TOKEN}"},
            json={
                "model": "qwen2.5:7b",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        self.assertEqual(resp.status_code, 200)
        text = resp.json()["choices"][0]["message"]["content"]
        self.assertIn("连接成功", text)

    def test_extract_json_shape(self) -> None:
        resp = self.client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEMO_TOKEN}"},
            json={
                "model": "qwen2.5:7b",
                "temperature": 0,
                "messages": [
                    {
                        "role": "system",
                        "content": "你只输出一个 JSON 对象。第一个字符是 {，最后一个是 }。",
                    },
                    {"role": "user", "content": "空 rows"},
                ],
            },
        )
        self.assertEqual(resp.status_code, 200)
        content = resp.json()["choices"][0]["message"]["content"]
        self.assertTrue(content.startswith("{"))
        self.assertIn("rows", content)


if __name__ == "__main__":
    unittest.main()
