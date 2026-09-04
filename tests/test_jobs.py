from __future__ import annotations

import threading
import time
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from electrical_krow.config import load_settings
from electrical_krow.gateway import create_app
from electrical_krow.jobs import retrieval_counts, review_sheet_name
from electrical_krow.login import AuthSession
from electrical_krow.mock_server import DEMO_USER
from electrical_krow.paths import OUTPUT_DIR


class RetrievalCountTests(unittest.TestCase):
    def test_counts_review_status(self) -> None:
        found, miss, partial = retrieval_counts(
            [
                SimpleNamespace(review_status="已检索到"),
                SimpleNamespace(review_status="局部对应/需人工复核"),
                SimpleNamespace(review_status="未检索到"),
                SimpleNamespace(review_status="通过"),
            ]
        )
        self.assertEqual((found, miss, partial), (1, 1, 1))

    def test_ignores_plain_values(self) -> None:
        self.assertEqual(retrieval_counts([1, 2, 3]), (0, 0, 0))
        self.assertEqual(retrieval_counts(None), (0, 0, 0))


class ReviewSheetNameTests(unittest.TestCase):
    def test_original_name_and_export_time(self) -> None:
        when = datetime(2026, 9, 4, 10, 25, 33)
        self.assertEqual(
            review_sheet_name("DHTS160规格书.pdf", when),
            "DHTS160规格书_20260904102533.xlsx",
        )

    def test_strips_unsafe_chars_and_extension(self) -> None:
        when = datetime(2026, 1, 2, 3, 4, 5)
        self.assertEqual(
            review_sheet_name("foo bar.docx", when),
            "foo_bar_20260102030405.xlsx",
        )


class JobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings(server_url="http://127.0.0.1:18766")
        self.client = TestClient(create_app(self.settings))
        session = AuthSession(access_token="tok", username=DEMO_USER, source="password")
        with patch("electrical_krow.gateway.login_with_password", return_value=session):
            login = self.client.post(
                "/api/login",
                json={"username": DEMO_USER, "password": "demo"},
            )
        self.assertEqual(login.status_code, 200)

    def test_login_then_job_and_download(self) -> None:
        def fake_run(incoming, out, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"xlsx-ok")
            return SimpleNamespace(
                output_xlsx=out,
                cells=[1, 2, 3],
                elapsed_seconds=1.25,
                likely_scan=False,
                pending_review=1,
                filled=2,
                extract=True,
                kind_label="测试",
                kind_note="",
                coverage_note="",
                stopped_early=False,
            )

        with patch("electrical_krow.jobs._run_pipeline", side_effect=fake_run):
            started = self.client.post(
                "/api/jobs",
                files={"file": ("spec.txt", "额定功率 400 W".encode(), "text/plain")},
            )
            self.assertEqual(started.status_code, 200, started.text)
            job_id = started.json()["id"]
            data = None
            for _ in range(40):
                snap = self.client.get(f"/api/jobs/{job_id}")
                self.assertEqual(snap.status_code, 200)
                data = snap.json()
                if data["status"] in {"done", "error"}:
                    break
                time.sleep(0.05)
        self.assertIsNotNone(data)
        self.assertEqual(data["status"], "done", data)
        self.assertEqual(data["filled"], 2)
        self.assertEqual(data["found"], 0)
        self.assertEqual(data["partial"], 0)
        self.assertEqual(data["miss"], 0)
        self.assertTrue(str(data["download"]).startswith("/files/"))
        self.assertTrue(str(data.get("knowledge_version") or "").strip())
        self.assertNotIn(".yaml", str(data.get("knowledge_version") or ""))
        name = str(data["download"]).rsplit("/", 1)[-1]
        self.assertRegex(name, r"^spec_\d{14}\.xlsx$")
        dl = self.client.get(f"/files/{name}")
        self.assertEqual(dl.status_code, 200)
        self.assertEqual(dl.content, b"xlsx-ok")
        (OUTPUT_DIR / name).unlink(missing_ok=True)

    def test_job_uses_selected_model(self) -> None:
        seen: dict[str, object] = {}

        def fake_run(incoming, out, **kwargs):
            seen.update(kwargs)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"xlsx-ok")
            return SimpleNamespace(
                output_xlsx=out,
                cells=[1],
                elapsed_seconds=0.2,
                likely_scan=False,
                pending_review=0,
                filled=1,
                extract=True,
                kind_label="测试",
                kind_note="",
                coverage_note="",
                stopped_early=False,
            )

        picked = self.client.post("/api/model", json={"model": "demo-llm"})
        self.assertEqual(picked.status_code, 200)
        with patch("electrical_krow.jobs._run_pipeline", side_effect=fake_run):
            started = self.client.post(
                "/api/jobs",
                files={"file": ("spec.txt", "额定功率 400 W".encode(), "text/plain")},
            )
            self.assertEqual(started.status_code, 200, started.text)
            job_id = started.json()["id"]
            for _ in range(40):
                snap = self.client.get(f"/api/jobs/{job_id}")
                data = snap.json()
                if data["status"] in {"done", "error"}:
                    break
                time.sleep(0.05)
        self.assertEqual(seen.get("model"), "demo-llm")
        name = str(self.client.get(f"/api/jobs/{job_id}").json()["download"]).rsplit(
            "/", 1
        )[-1]
        (OUTPUT_DIR / name).unlink(missing_ok=True)

    def test_job_reports_retrieval_counts(self) -> None:
        def fake_run(incoming, out, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"xlsx-ok")
            return SimpleNamespace(
                output_xlsx=out,
                cells=[
                    SimpleNamespace(review_status="已检索到"),
                    SimpleNamespace(review_status="局部对应/需人工复核"),
                    SimpleNamespace(review_status="未检索到"),
                    SimpleNamespace(review_status="未检索到"),
                ],
                elapsed_seconds=0.4,
                likely_scan=True,
                pending_review=4,
                filled=2,
                extract=True,
                kind_label="扫描件",
                kind_note="",
                coverage_note="",
                stopped_early=False,
            )

        with patch("electrical_krow.jobs._run_pipeline", side_effect=fake_run):
            started = self.client.post(
                "/api/jobs",
                files={"file": ("spec.txt", "额定功率 400 W".encode(), "text/plain")},
            )
            self.assertEqual(started.status_code, 200, started.text)
            job_id = started.json()["id"]
            data = None
            for _ in range(40):
                snap = self.client.get(f"/api/jobs/{job_id}")
                data = snap.json()
                if data["status"] in {"done", "error"}:
                    break
                time.sleep(0.05)
        self.assertIsNotNone(data)
        self.assertEqual(data["status"], "done", data)
        self.assertEqual(data["found"], 1)
        self.assertEqual(data["partial"], 1)
        self.assertEqual(data["miss"], 2)
        name = str(data["download"]).rsplit("/", 1)[-1]
        (OUTPUT_DIR / name).unlink(missing_ok=True)

    def test_unsupported_type(self) -> None:
        resp = self.client.post(
            "/api/jobs",
            files={"file": ("a.bin", b"xx", "application/octet-stream")},
        )
        self.assertEqual(resp.status_code, 400)

    def test_serial_jobs_return_409(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def fake_run(incoming, out, **kwargs):
            started.set()
            release.wait(timeout=5)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"xlsx-ok")
            return SimpleNamespace(
                output_xlsx=out,
                cells=[1],
                elapsed_seconds=0.1,
                likely_scan=False,
                pending_review=0,
                filled=1,
                extract=True,
                kind_label="测试",
                kind_note="",
                coverage_note="",
                stopped_early=False,
            )

        with patch("electrical_krow.jobs._run_pipeline", side_effect=fake_run):
            first = self.client.post(
                "/api/jobs",
                files={"file": ("spec.txt", "额定功率 400 W".encode(), "text/plain")},
            )
            self.assertEqual(first.status_code, 200, first.text)
            self.assertTrue(started.wait(2))
            self.assertTrue(self.client.get("/api/health").json().get("busy"))
            second = self.client.post(
                "/api/jobs",
                files={"file": ("spec2.txt", "额定功率 200 W".encode(), "text/plain")},
            )
            self.assertEqual(second.status_code, 409)
            detail = second.json().get("detail") or ""
            self.assertIn("全站同时一份", detail)
            release.set()
            job_id = first.json()["id"]
            for _ in range(40):
                snap = self.client.get(f"/api/jobs/{job_id}")
                if snap.json()["status"] in {"done", "error"}:
                    break
                time.sleep(0.05)
            name = str(self.client.get(f"/api/jobs/{job_id}").json()["download"]).rsplit(
                "/", 1
            )[-1]
            (OUTPUT_DIR / name).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
