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

    def test_chat_accepts_openai_image_url(self) -> None:
        resp = self.client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEMO_TOKEN}"},
            json={
                "model": "krow-ocr-table",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "读图"},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "data:image/png;base64,iVBORw0KGgo="
                                },
                            },
                        ],
                    }
                ],
            },
        )
        self.assertEqual(resp.status_code, 200)
        text = resp.json()["choices"][0]["message"]["content"]
        self.assertIn("HVDC", text)
        self.assertIn("380", text)

    def test_complete_forwards_only_whitelisted_extra(self) -> None:
        import json
        from unittest.mock import patch

        import httpx

        from electrical_krow.login import AuthSession
        from electrical_krow.llm import complete

        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(request.content))
            return httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": "{}"}}]},
            )

        real_client = httpx.Client

        def client_factory(**kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(**kwargs)

        with patch("electrical_krow.llm.httpx.Client", side_effect=client_factory):
            complete(
                "https://api.krow.cn",
                AuthSession(access_token="tok", username="u", source="password"),
                [{"role": "user", "content": "hi"}],
                model="deepseek-v4-pro",
                extra={
                    "thinking": {"type": "disabled"},
                    "reasoning_effort": None,
                    "max_tokens": 4096,
                    "options": {"num_predict": 1},
                },
            )
        self.assertEqual(seen["thinking"], {"type": "disabled"})
        self.assertEqual(seen["max_tokens"], 4096)
        self.assertNotIn("reasoning_effort", seen)
        self.assertNotIn("options", seen)

    def test_ocr_endpoint(self) -> None:
        empty = self.client.post(
            "/v1/ocr",
            headers={"Authorization": f"Bearer {DEMO_TOKEN}"},
            json={"task": "table"},
        )
        self.assertEqual(empty.status_code, 400)
        resp = self.client.post(
            "/v1/ocr",
            headers={"Authorization": f"Bearer {DEMO_TOKEN}"},
            json={
                "task": "table",
                "image": "data:image/jpeg;base64,aGVsbG8=",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body.get("success"))
        self.assertIn("HVDC", body["text"])
        self.assertEqual(body.get("model"), "krow-ocr-table")


if __name__ == "__main__":
    unittest.main()
