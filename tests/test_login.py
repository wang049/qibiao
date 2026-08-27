from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from electrical_krow.errors import LoginError
from electrical_krow.login import login_with_api_key
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

    def test_api_key_format(self) -> None:
        session = login_with_api_key("sk-user-jx3rv76no4v2rf2erqk0fj0d60tbbr0569vzoad9")
        self.assertEqual(session.source, "api_key")
        self.assertTrue(session.access_token.startswith("sk-"))
        with self.assertRaises(LoginError):
            login_with_api_key("not-a-key")


if __name__ == "__main__":
    unittest.main()
