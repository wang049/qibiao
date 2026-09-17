from __future__ import annotations

import json
import threading
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from electrical_krow.config import load_settings
from electrical_krow.gateway import create_app
from electrical_krow.jobs import JobStore, retrieval_counts, review_sheet_name
from electrical_krow.login import AuthSession
from electrical_krow.mock_server import DEMO_USER


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
            "DHTS160规格书_2026年09月04日10：25：33.xlsx",
        )

    def test_strips_unsafe_chars_and_extension(self) -> None:
        when = datetime(2026, 1, 2, 3, 4, 5)
        self.assertEqual(
            review_sheet_name("foo bar.docx", when),
            "foo_bar_2026年01月02日03：04：05.xlsx",
        )


class JobTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.settings = load_settings(server_url="http://127.0.0.1:18766")
        self.client = TestClient(
            create_app(self.settings, output_dir=Path(self._tmp.name))
        )
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
                qa_verdict="pass",
                qa_summary="通过。可读正文约 120 字。",
                stopped_early=False,
                chunk_failures=2,
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
        self.assertEqual(data.get("qa_verdict"), "pass")
        self.assertEqual(data.get("chunk_failures"), 2)
        self.assertNotIn("交叉检查不填抽出值", str(data.get("qa_summary") or ""))
        self.assertNotIn("已见主题", str(data.get("qa_summary") or ""))
        self.assertTrue(str(data["download"]).startswith("/files/"))
        self.assertTrue(str(data.get("knowledge_version") or "").strip())
        self.assertNotIn(".yaml", str(data.get("knowledge_version") or ""))
        name = str(data["download"]).rsplit("/", 1)[-1]
        self.assertRegex(
            name,
            r"^spec_\d{4}年\d{2}月\d{2}日\d{2}：\d{2}：\d{2}\.xlsx$",
        )
        dl = self.client.get(f"/files/{name}")
        self.assertEqual(dl.status_code, 200)
        self.assertEqual(dl.content, b"xlsx-ok")
        listed = self.client.get("/api/jobs")
        self.assertEqual(listed.status_code, 200)
        ids = [row.get("id") for row in listed.json().get("jobs") or []]
        self.assertIn(job_id, ids)
        self.assertEqual(
            next(
                row.get("username")
                for row in listed.json()["jobs"]
                if row.get("id") == job_id
            ),
            DEMO_USER,
        )
        self.assertEqual(
            next(
                row.get("qa_verdict")
                for row in listed.json()["jobs"]
                if row.get("id") == job_id
            ),
            "pass",
        )
        self.assertEqual(
            next(
                row.get("chunk_failures")
                for row in listed.json()["jobs"]
                if row.get("id") == job_id
            ),
            2,
        )

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
    def test_health_exposes_active_job_and_clears_after_done(self) -> None:
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
                stopped_early=False,
            )

        with patch("electrical_krow.jobs._run_pipeline", side_effect=fake_run):
            first = self.client.post(
                "/api/jobs",
                files={"file": ("spec.txt", "额定功率 400 W".encode(), "text/plain")},
            )
            self.assertEqual(first.status_code, 200, first.text)
            job_id = first.json()["id"]
            self.assertTrue(started.wait(2))
            health = self.client.get("/api/health").json()
            self.assertTrue(health.get("busy"))
            active = health.get("active_job") or {}
            self.assertEqual(active.get("id"), job_id)
            self.assertIn(active.get("status"), {"running", "paused", "pausing", "stopping"})
            release.set()
            for _ in range(40):
                snap = self.client.get(f"/api/jobs/{job_id}")
                if snap.json()["status"] in {"done", "error"}:
                    break
                time.sleep(0.05)
            for _ in range(40):
                if not self.client.get("/api/health").json().get("busy"):
                    break
                time.sleep(0.05)
            idle = self.client.get("/api/health").json()
            self.assertFalse(idle.get("busy"))
            self.assertIsNone(idle.get("active_job"))
            second = self.client.post(
                "/api/jobs",
                files={"file": ("spec2.txt", "额定功率 200 W".encode(), "text/plain")},
            )
            self.assertEqual(second.status_code, 200, second.text)
            second_id = second.json()["id"]
            for _ in range(40):
                snap = self.client.get(f"/api/jobs/{second_id}")
                if snap.json()["status"] in {"done", "error"}:
                    break
                time.sleep(0.05)
    def test_stop_conflict_says_ending(self) -> None:
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
                stopped_early=False,
            )

        with patch("electrical_krow.jobs._run_pipeline", side_effect=fake_run):
            first = self.client.post(
                "/api/jobs",
                files={"file": ("spec.txt", "额定功率 400 W".encode(), "text/plain")},
            )
            self.assertEqual(first.status_code, 200, first.text)
            job_id = first.json()["id"]
            self.assertTrue(started.wait(2))
            stopped = self.client.post(f"/api/jobs/{job_id}/stop")
            self.assertEqual(stopped.status_code, 200, stopped.text)
            self.assertEqual(stopped.json().get("status"), "stopping")
            second = self.client.post(
                "/api/jobs",
                files={"file": ("spec2.txt", "额定功率 200 W".encode(), "text/plain")},
            )
            self.assertEqual(second.status_code, 409)
            detail = second.json().get("detail") or ""
            self.assertIn("正在结束出表", detail)
            self.assertNotIn("请等当前这份完成后再提交", detail)
            release.set()
            for _ in range(40):
                snap = self.client.get(f"/api/jobs/{job_id}")
                if snap.json()["status"] in {"done", "error"}:
                    break
                time.sleep(0.05)


class JobOwnerListTests(unittest.TestCase):
    def test_list_only_current_login(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        settings = load_settings(server_url="http://127.0.0.1:18766")
        app = create_app(settings, output_dir=Path(tmp.name))
        alice = TestClient(app)
        bob = TestClient(app)

        def fake_login(_url, username, password, **_kwargs):
            return AuthSession(
                access_token="tok-" + username,
                username=username,
                source="password",
            )

        def fake_run(incoming, out, **kwargs):
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
                kind_label="电控 DPR",
                kind_note="",
                stopped_early=False,
            )

        with patch(
            "electrical_krow.gateway.login_with_password", side_effect=fake_login
        ):
            self.assertEqual(
                alice.post(
                    "/api/login",
                    json={"username": "alice@ex.com", "password": "demo"},
                ).status_code,
                200,
            )
            self.assertEqual(
                bob.post(
                    "/api/login",
                    json={"username": "bob@ex.com", "password": "demo"},
                ).status_code,
                200,
            )
        with patch("electrical_krow.jobs._run_pipeline", side_effect=fake_run):
            started = alice.post(
                "/api/jobs",
                files={"file": ("mine.txt", "额定功率 400 W".encode(), "text/plain")},
            )
            self.assertEqual(started.status_code, 200, started.text)
            job_id = started.json()["id"]
            for _ in range(40):
                snap = alice.get(f"/api/jobs/{job_id}")
                if snap.json()["status"] in {"done", "error"}:
                    break
                time.sleep(0.05)
        mine = [row.get("id") for row in alice.get("/api/jobs").json()["jobs"]]
        theirs = [row.get("id") for row in bob.get("/api/jobs").json()["jobs"]]
        self.assertIn(job_id, mine)
        self.assertNotIn(job_id, theirs)
        self.assertEqual(bob.get(f"/api/jobs/{job_id}").status_code, 404)


class JobHistoryTests(unittest.TestCase):
    def test_lists_existing_sheet_and_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            sheet = root / "spec_20260907100000.xlsx"
            sheet.write_bytes(b"xlsx")
            store = JobStore(output_dir=root)
            rows = store.list_recent()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["id"], "xlsx-spec_20260907100000.xlsx")
            snap = store.snapshot(rows[0]["id"])
            self.assertEqual(snap["status"], "done")
            self.assertEqual(snap["download"], "/files/spec_20260907100000.xlsx")

    def test_user_list_hides_tests_errors_and_foreign(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "orphan.xlsx").write_bytes(b"xlsx")
            store = JobStore(output_dir=root)
            path = root / "jobs.jsonl"
            rows = [
                {
                    "id": "a1",
                    "status": "error",
                    "source": "a.txt",
                    "detail": "没有读取器: 65e5994a_a.txt",
                    "created_at": 1,
                },
                {
                    "id": "t1",
                    "status": "done",
                    "source": "spec.txt",
                    "kind_label": "测试",
                    "download": "/files/t.xlsx",
                    "created_at": 2,
                },
                {
                    "id": "ok1",
                    "status": "done",
                    "source": "DHTS160.docx",
                    "download": "/files/d.xlsx",
                    "field_count": 120,
                    "created_at": 3,
                },
                {
                    "id": "mine",
                    "status": "done",
                    "source": "mine.docx",
                    "username": "alice",
                    "download": "/files/m.xlsx",
                    "created_at": 4,
                },
                {
                    "id": "other",
                    "status": "done",
                    "source": "other.docx",
                    "username": "bob",
                    "download": "/files/o.xlsx",
                    "created_at": 5,
                },
            ]
            path.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                encoding="utf-8",
            )
            listed = store.list_recent(username="alice")
            ids = {str(row.get("id") or "") for row in listed}
            self.assertEqual(ids, {"ok1", "mine"})
            self.assertEqual(store.snapshot("mine", username="alice")["id"], "mine")
            with self.assertRaises(HTTPException) as raised:
                store.snapshot("other", username="alice")
            self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
