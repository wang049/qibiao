from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from electrical_krow.errors import LoginError
from electrical_krow.login import login_with_api_key, login_with_password
from electrical_krow.mock_server import DEMO_PASSWORD, DEMO_TOKEN, DEMO_USER, create_app


class LoginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def test_password_login(self) -> None:
        resp = self.client.post(
            "/api/auth/login",
            json={"username": DEMO_USER, "password": DEMO_PASSWORD},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["access_token"], DEMO_TOKEN)

    def test_bad_password(self) -> None:
        resp = self.client.post(
            "/api/auth/login",
            json={"username": DEMO_USER, "password": "nope"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_cloud_login_and_key(self) -> None:
        resp = self.client.post(
            "/auth/login",
            json={"email": "demo@krow.cn", "password": DEMO_PASSWORD, "device_code": None},
        )
        self.assertEqual(resp.status_code, 200)
        token = resp.json()["access_token"]
        self.assertTrue(token.startswith("eyJ"))
        key = self.client.post(
            "/api-keys",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "electrical-krow"},
        )
        self.assertEqual(key.status_code, 200)
        self.assertTrue(key.json()["key"].startswith("sk-user-"))

    def test_api_key_format(self) -> None:
        session = login_with_api_key("sk-user-jx3rv76no4v2rf2erqk0fj0d60tbbr0569vzoad9")
        self.assertEqual(session.source, "api_key")
        self.assertTrue(session.access_token.startswith("sk-"))
        with self.assertRaises(LoginError):
            login_with_api_key("not-a-key")

    def test_mobile_rejected(self) -> None:
        with self.assertRaises(LoginError) as ctx:
            login_with_password("https://api.krow.cn", "18858691866", "secret")
        self.assertIn("邮箱", str(ctx.exception))

    def test_portal_host_405_hints_rdapi(self) -> None:
        class Resp:
            status_code = 405
            text = ""

            def json(self):
                raise ValueError("empty")

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, *args, **kwargs):
                return Resp()

        with patch("electrical_krow.login.httpx.Client", FakeClient):
            with self.assertRaises(LoginError) as ctx:
                login_with_password(
                    "https://rdagents.aurobaytech-t.com", "zeru@example.com", "x"
                )
        msg = str(ctx.exception)
        self.assertIn("HTTP 405", msg)
        self.assertIn("https://rdapi.aurobaytech-t.com", msg)
        self.assertNotIn("https://api.rdagents.aurobaytech-t.com", msg)

    def test_unregistered_email_uses_server_message(self) -> None:
        class Resp:
            status_code = 404
            text = '{"error":"该邮箱未注册，请先注册"}'

            def json(self):
                return {"error": "该邮箱未注册，请先注册"}

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, *args, **kwargs):
                return Resp()

        with patch("electrical_krow.login.httpx.Client", FakeClient):
            with self.assertRaises(LoginError) as ctx:
                login_with_password("https://api.krow.cn", "nobody@krow.cn", "x")
        self.assertIn("未注册", str(ctx.exception))

    def test_reuses_cached_key_and_cleans_old(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        store = KeyStore()
        store.keys = [
            {"id": "old-1", "name": "electrical-krow"},
            {"id": "old-2", "name": "electrical-krow"},
            {"id": "keep", "name": "kad-desktop"},
        ]

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, url, **kwargs):
                if url.endswith("/auth/login"):
                    return JsonResp(
                        200,
                        {
                            "access_token": "eyJmock.token",
                            "user": {"email": "demo@krow.cn"},
                        },
                    )
                if url.rstrip("/").endswith("/api-keys"):
                    return store.create()
                return JsonResp(404, {})

            def get(self, url, **kwargs):
                if url.rstrip("/").endswith("/api-keys"):
                    return JsonResp(200, {"keys": list(store.keys)})
                return JsonResp(404, {})

            def delete(self, url, **kwargs):
                key_id = url.rstrip("/").rsplit("/", 1)[-1]
                store.delete(key_id)
                return JsonResp(200, {"success": True})

        with (
            patch("electrical_krow.login.httpx.Client", FakeClient),
            patch("electrical_krow.login.data_root", return_value=tmp),
        ):
            first = login_with_password("https://api.krow.cn", "demo@krow.cn", "x")
            self.assertTrue(first.access_token.startswith("sk-user-"))
            names = [item["name"] for item in store.keys]
            self.assertEqual(names.count("electrical-krow"), 1)
            self.assertIn("kad-desktop", names)
            second = login_with_password("https://api.krow.cn", "demo@krow.cn", "x")
        self.assertEqual(second.access_token, first.access_token)
        self.assertEqual(store.created, 1)
        shutil.rmtree(tmp, ignore_errors=True)


class JsonResp:
    def __init__(self, status_code: int, data: dict):
        self.status_code = status_code
        self._data = data
        self.text = json.dumps(data)

    def json(self):
        return self._data


class KeyStore:
    def __init__(self) -> None:
        self.keys: list[dict] = []
        self.created = 0

    def create(self) -> JsonResp:
        self.created += 1
        ident = f"key{self.created:07d}"
        secret = "a3f9k2m7x8p1q4w6e5r0t9y2u7i3o5a8"
        full = f"sk-user-{ident}{secret}"
        info = {
            "id": f"id-{self.created}",
            "name": "electrical-krow",
            "key": full,
        }
        self.keys.append({"id": info["id"], "name": info["name"]})
        return JsonResp(200, info)

    def delete(self, key_id: str) -> None:
        self.keys = [item for item in self.keys if item["id"] != key_id]


if __name__ == "__main__":
    unittest.main()
