from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from electrical_krow.errors import LLMError
from electrical_krow.login import AuthSession
from electrical_krow.quota import (
    classify_remote,
    looks_like_quota,
    note_remote,
    quota_error_message,
    usage_brief,
)


class ClassifyQuotaTests(unittest.TestCase):
    def test_402_is_quota(self) -> None:
        self.assertEqual(classify_remote(402, "payment required"), "quota")
        self.assertTrue(looks_like_quota(402, ""))

    def test_chinese_and_openai_wording(self) -> None:
        self.assertTrue(looks_like_quota(403, "账号算力不足，请充值"))
        self.assertTrue(
            looks_like_quota(
                429,
                '{"error":{"type":"insufficient_quota","message":"You exceeded your current quota"}}',
            )
        )
        self.assertTrue(
            looks_like_quota(
                200,
                "",
                {"error": {"type": "insufficient_quota", "message": "no credits"}},
            )
        )

    def test_401_generic_is_auth_but_quota_body_wins(self) -> None:
        self.assertEqual(classify_remote(401, "invalid api key"), "auth")
        self.assertEqual(classify_remote(401, "算力已用尽"), "quota")

    def test_429_without_quota_is_rate_limit(self) -> None:
        self.assertEqual(classify_remote(429, "Too Many Requests"), "rate_limit")

    def test_credential_is_not_quota(self) -> None:
        self.assertFalse(looks_like_quota(401, "invalid credential"))
        self.assertEqual(classify_remote(500, "internal error"), "other")
        self.assertEqual(classify_remote(200, "", {"choices": []}), "ok")

    def test_error_message_prefix(self) -> None:
        msg = quota_error_message(402, "余额不足", fallback="HTTP 402")
        self.assertIn("算力不足", msg)
        self.assertIn("402", msg)
        self.assertEqual(
            quota_error_message(500, "boom", fallback="识别服务 HTTP 500: boom"),
            "识别服务 HTTP 500: boom",
        )

    def test_usage_brief(self) -> None:
        self.assertEqual(
            usage_brief(
                {
                    "usage": {
                        "prompt_tokens": 12,
                        "completion_tokens": 3,
                        "total_tokens": 15,
                    }
                }
            ),
            "prompt_tokens=12 completion_tokens=3 total_tokens=15",
        )


class NoteRemoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("ELECTRICAL_KROW_DATA")
        os.environ["ELECTRICAL_KROW_DATA"] = self._tmp.name

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("ELECTRICAL_KROW_DATA", None)
        else:
            os.environ["ELECTRICAL_KROW_DATA"] = self._old
        self._tmp.cleanup()

    def test_writes_quota_log(self) -> None:
        note_remote("chat", 402, "算力不足", model="ZHIPU/GLM-5.2")
        log = Path(self._tmp.name) / "quota.log"
        self.assertTrue(log.is_file())
        text = log.read_text(encoding="utf-8")
        self.assertIn("[算力]", text)
        self.assertIn("判定=算力不足", text)
        self.assertIn("GLM-5.2", text)

    def test_chat_ok_logs_usage(self) -> None:
        note_remote(
            "chat",
            200,
            "",
            model="deepseek-v4-pro",
            payload={"usage": {"prompt_tokens": 8, "completion_tokens": 2}},
        )
        text = (Path(self._tmp.name) / "quota.log").read_text(encoding="utf-8")
        self.assertIn("判定=未提示不足", text)
        self.assertIn("prompt_tokens=8", text)


class CompleteQuotaTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("ELECTRICAL_KROW_DATA")
        os.environ["ELECTRICAL_KROW_DATA"] = self._tmp.name
        self.session = AuthSession(
            access_token="sk-user-aaaaaaaaaaaaaaaaaaaaaaaa",
            username="demo",
        )

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("ELECTRICAL_KROW_DATA", None)
        else:
            os.environ["ELECTRICAL_KROW_DATA"] = self._old
        self._tmp.cleanup()

    def test_complete_402_raises_quota(self) -> None:
        from electrical_krow.llm import complete

        class FakeResp:
            status_code = 402
            text = '{"error":{"type":"insufficient_quota","message":"算力不足"}}'

            def json(self):
                return {"error": {"type": "insufficient_quota"}}

        class FakeClient:
            def __init__(self, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_exc) -> bool:
                return False

            def post(self, *_a, **_k):
                return FakeResp()

        with patch("httpx.Client", FakeClient):
            with self.assertRaises(LLMError) as ctx:
                complete(
                    "https://api.krow.cn",
                    self.session,
                    [{"role": "user", "content": "hi"}],
                    model="ZHIPU/GLM-5.2",
                )
        self.assertIn("算力不足", str(ctx.exception))
        text = (Path(self._tmp.name) / "quota.log").read_text(encoding="utf-8")
        self.assertIn("判定=算力不足", text)
        self.assertIn("chat", text)


if __name__ == "__main__":
    unittest.main()
