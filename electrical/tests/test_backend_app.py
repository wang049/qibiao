"""出表 HTTP 服务能拉起页面与静态资源。"""
from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from electrical.backend.app import app


class BackendAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_index_serves_frontend(self) -> None:
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        body = resp.text
        self.assertIn("本机出表", body)
        self.assertIn("/static/styles.css", body)
        self.assertIn("/static/app.js", body)
        self.assertIn("id=\"st-qc\"", body)
        self.assertIn("质检", body)

    def test_static_assets(self) -> None:
        css = self.client.get("/static/styles.css")
        js = self.client.get("/static/app.js")
        self.assertEqual(css.status_code, 200)
        self.assertIn(".drop", css.text)
        self.assertEqual(js.status_code, 200)
        self.assertIn("/api/jobs", js.text)

    def test_missing_job_is_404(self) -> None:
        resp = self.client.get("/api/jobs/does-not-exist")
        self.assertEqual(resp.status_code, 404)

    def test_health_shape(self) -> None:
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("ok", data)
        self.assertIn("model", data)


if __name__ == "__main__":
    unittest.main()
