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
    def test_extract_pipeline_lives_in_this_repo(self) -> None:
        import os

        from electrical_krow.bridge import electrical_root
        from electrical_krow.paths import PROJECT_ROOT

        old = os.environ.pop("ELECTRICAL_ROOT", None)
        try:
            root = electrical_root()
        finally:
            if old is not None:
                os.environ["ELECTRICAL_ROOT"] = old
        self.assertEqual(root, (PROJECT_ROOT / "electrical").resolve())
        self.assertTrue((root / "electrical" / "pipeline.py").is_file())

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

    def test_job_reports_groups_pending_and_live_counts(self) -> None:
        """结果摘要：分组结论 + 待专家口径格数；出表中：分段 n/N 与已抽出实时计数。"""
        from electrical_krow.bridge import ensure_electrical

        ensure_electrical()
        from electrical.progress import report_stats
        from electrical.schema import ExtractedCell

        seen_live: dict[str, object] = {}

        def fake_run(incoming, out, **kwargs):
            report_stats(chunk_done=3, chunk_total=9, filled=41)
            jid = self.client.get("/api/health").json()["active_job"]["id"]
            snap = self.client.get(f"/api/jobs/{jid}").json()
            seen_live.update({k: snap.get(k) for k in ("chunk_done", "chunk_total", "filled")})
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"xlsx-ok")
            cells = [
                ExtractedCell(name="设计范围是否包含P1", seq=1, value="是", review_status="已检索到"),
                ExtractedCell(name="设计范围是否包含P3", seq=2, value="", review_status="未检索到"),
                ExtractedCell(name="直流母线电压范围", seq=5, value="250-450V", review_status="已检索到",
                              note="待专家口径：区间还是标称"),
                ExtractedCell(name="额外项", seq=0, value="x", review_status="已检索到", extra=True,
                              note="待专家口径：不算"),
            ]
            return SimpleNamespace(
                output_xlsx=out, cells=cells, elapsed_seconds=0.4, likely_scan=False,
                pending_review=2, filled=3, extract=True, kind_label="电控 DPR", kind_note="",
                stopped_early=False,
            )

        with patch("electrical_krow.jobs._run_pipeline", side_effect=fake_run), \
             patch("electrical_krow.jobs.JobStore._previous_done", return_value=None):
            started = self.client.post(
                "/api/jobs",
                files={"file": ("spec.txt", "额定功率 400 W".encode(), "text/plain")},
            )
            self.assertEqual(started.status_code, 200, started.text)
            job_ids = [started.json()["id"]]
            data = None
            for _ in range(60):
                data = self.client.get(f"/api/jobs/{job_ids[0]}").json()
                if data["status"] in {"done", "error"}:
                    break
                time.sleep(0.05)
        self.assertEqual(data["status"], "done", data)
        self.assertEqual(data["pending_note"], 1)
        groups = {g["name"]: g for g in data["groups"]}
        self.assertEqual(groups["设计范围"], {"name": "设计范围", "total": 2, "found": 1, "partial": 0, "miss": 1})
        self.assertEqual(groups["直流高压"]["found"], 1)
        self.assertNotIn("其他", groups)
        self.assertEqual(data["compare"], {})
        self.assertEqual(seen_live, {"chunk_done": 3, "chunk_total": 9, "filled": 41})
        # 历史里也带摘要字段
        rows = self.client.get("/api/jobs").json()["jobs"]
        rec = next(r for r in rows if r["id"] == job_ids[0])
        self.assertEqual(rec["pending_note"], 1)
        self.assertEqual(len(rec["groups"]), 2)

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

    def test_records_can_be_filed_into_a_folder(self) -> None:
        path = Path(self._tmp.name) / "jobs.jsonl"
        rows = [
            {
                "id": "j1",
                "status": "done",
                "source": "DHTS160 DPR.docx",
                "username": DEMO_USER,
                "created_at": 1,
                "download": "/files/a.xlsx",
            },
            {
                "id": "j2",
                "status": "done",
                "source": "DHTS160 DPR.docx",
                "username": DEMO_USER,
                "created_at": 2,
                "download": "/files/b.xlsx",
            },
        ]
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        listed = self.client.get("/api/jobs")
        self.assertEqual(listed.status_code, 200, listed.text)
        body = listed.json()
        self.assertEqual([row["id"] for row in body["jobs"]], ["j2", "j1"])
        self.assertTrue(all("folder_id" not in row for row in body["jobs"]))
        self.assertEqual(body["folders"], [])
        made = self.client.post("/api/records/folders", json={"kind": "jobs", "name": "本周复核"})
        self.assertEqual(made.status_code, 200, made.text)
        folder_id = made.json()["folder"]["id"]
        placed = self.client.post(
            "/api/records/place",
            json={"kind": "jobs", "record_id": "j1", "folder_id": folder_id},
        )
        self.assertEqual(placed.status_code, 200, placed.text)
        again = self.client.get("/api/jobs").json()
        by_id = {row["id"]: row for row in again["jobs"]}
        self.assertEqual(by_id["j1"]["folder_id"], folder_id)
        self.assertNotIn("folder_id", by_id["j2"])
        self.assertEqual(again["folders"][0]["name"], "本周复核")
        self.assertEqual(self.client.get("/api/hsi/history").json()["folders"], [])
        dup = self.client.post("/api/records/folders", json={"kind": "jobs", "name": "本周复核"})
        self.assertEqual(dup.status_code, 400)
        self.assertIn("同名", dup.json()["detail"])
        missing = self.client.post(
            "/api/records/place",
            json={"kind": "jobs", "record_id": "nope", "folder_id": folder_id},
        )
        self.assertEqual(missing.status_code, 400)
        cleared = self.client.post(
            "/api/records/place",
            json={"kind": "jobs", "record_id": "j1", "folder_id": ""},
        )
        self.assertEqual(cleared.status_code, 200, cleared.text)
        back = {row["id"]: row for row in self.client.get("/api/jobs").json()["jobs"]}
        self.assertNotIn("folder_id", back["j1"])
        page = self.client.get("/static/app.js").text
        self.assertIn("/api/records/folders", page)
        self.assertIn("/api/records/place", page)
        self.assertIn("新建文件夹", self.client.get("/static/i18n.js").text)

    def test_detection_file_can_sit_in_a_folder_with_the_output(self) -> None:
        path = Path(self._tmp.name) / "jobs.jsonl"
        path.write_text(
            json.dumps(
                {
                    "id": "j1",
                    "status": "done",
                    "source": "DHTS160 DPR.docx",
                    "username": DEMO_USER,
                    "created_at": 10,
                    "download": "/files/a.xlsx",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        kept = self.client.app.state.jobs.keep_source(
            username=DEMO_USER,
            kind="jobs",
            filename="DHTS160 DPR.docx",
            data=b"spec-bytes",
            run_id="j1",
            group_title="DHTS160 DPR.docx",
        )
        listed = self.client.get("/api/jobs").json()["jobs"]
        by_id = {row["id"]: row for row in listed}
        self.assertEqual(by_id["j1"]["group_title"], "DHTS160 DPR.docx")
        self.assertEqual(by_id[kept["id"]]["role"], "source")
        self.assertEqual(by_id[kept["id"]]["source"], "DHTS160 DPR.docx")
        made = self.client.post("/api/records/folders", json={"kind": "jobs", "name": "项目甲"})
        folder_id = made.json()["folder"]["id"]
        added = self.client.post(
            "/api/records/sources",
            data={"kind": "jobs", "folder_id": folder_id},
            files={"file": ("手册.pdf", b"%PDF-1.4", "application/pdf")},
        )
        self.assertEqual(added.status_code, 200, added.text)
        source_id = added.json()["source"]["id"]
        again = {row["id"]: row for row in self.client.get("/api/jobs").json()["jobs"]}
        self.assertEqual(again[source_id]["folder_id"], folder_id)
        self.assertEqual(again[source_id]["role"], "source")
        downloaded = self.client.get(f"/api/records/sources/{source_id}/file")
        self.assertEqual(downloaded.status_code, 200, downloaded.text)
        self.assertEqual(downloaded.content, b"%PDF-1.4")


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

    def test_hsi_files_stay_out_of_extract_history(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "spec.xlsx").write_bytes(b"xlsx")
            (root / "HSI-TC499-BGA436-1-20261014.xlsx").write_bytes(b"hsi")
            store = JobStore(output_dir=root)
            store.remember_hsi(
                name="HSI-TC38x-BGA516-1-20261014.xlsx",
                username="alice",
                mcu="TC38x",
                package="BGA516",
                pins=307,
                changes=0,
                version="TC38x-BGA516-1",
            )
            (root / "HSI-TC38x-BGA516-1-20261014.xlsx").write_bytes(b"hsi")
            extract = {str(row.get("source") or "") for row in store.list_recent()}
            self.assertIn("spec", extract)
            self.assertFalse(any(name.startswith("HSI-") for name in extract))
            planning = store.list_hsi(username="alice")
            names = {str(row.get("source") or "") for row in planning}
            self.assertEqual(
                names,
                {
                    "HSI-TC38x-BGA516-1-20261014.xlsx",
                    "HSI-TC499-BGA436-1-20261014.xlsx",
                },
            )
            remembered = next(row for row in planning if "TC38x" in str(row.get("source")))
            self.assertEqual(remembered["pins"], 307)
            self.assertEqual(remembered["package"], "BGA516")

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


class ResultSummaryTests(unittest.TestCase):
    """同名文件对比与按历史估时：纯函数。"""

    def test_compare_with_previous_reads_last_sheet_and_lists_diff(self) -> None:
        from electrical_krow.bridge import ensure_electrical
        from electrical_krow.jobs import compare_with_previous

        ensure_electrical()
        from electrical.schema import ExtractedCell, empty_template_rows
        from electrical.write_excel import write_review_workbook

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            prev_cells = empty_template_rows()
            for cell in prev_cells[:3]:
                cell.value = "1"
                cell.review_status = "已检索到"
                cell.confidence = 0.95
                cell.page = "3"
                cell.excerpt = "value 1"
            for cell in prev_cells[3:]:
                cell.review_status = "未检索到"
            write_review_workbook(
                prev_cells, out / "spec_prev.xlsx",
                source_name="spec.docx", likely_scan=False, parser="test",
            )
            now_cells = empty_template_rows()
            for cell in now_cells[1:5]:
                cell.value = "2"
                cell.review_status = "已检索到"
            for cell in [now_cells[0]] + now_cells[5:]:
                cell.review_status = "未检索到"
            previous = {"id": "p1", "download": "/files/spec_prev.xlsx", "created_at": 10}
            cmp = compare_with_previous(now_cells, previous, out)
            self.assertEqual((cmp["prev_found"], cmp["found"]), (3, 4))
            self.assertEqual(cmp["gained"], [now_cells[3].name, now_cells[4].name])
            self.assertEqual(cmp["lost"], [prev_cells[0].name])
            self.assertEqual(cmp["prev_id"], "p1")
            # 上一份文件不在目录 / 路径越界 → 空，不报错
            self.assertEqual(compare_with_previous(now_cells, {"download": "/files/none.xlsx"}, out), {})
            self.assertEqual(compare_with_previous(now_cells, {"download": "/files/../x.xlsx"}, out), {})
            self.assertEqual(compare_with_previous(now_cells, None, out), {})

    def test_estimate_prefers_same_kind_and_medium_then_falls_back(self) -> None:
        from electrical_krow.inspect_doc import estimate_seconds

        hist = [
            {"status": "done", "kind_label": "电控 DPR", "likely_scan": False, "elapsed_seconds": 600},
            {"status": "done", "kind_label": "电控 DPR", "likely_scan": False, "elapsed_seconds": 900},
            {"status": "done", "kind_label": "电控 DPR", "likely_scan": True, "elapsed_seconds": 1700},
            {"status": "done", "kind_label": "逆变器 SR", "likely_scan": False, "elapsed_seconds": 300},
            {"status": "error", "kind_label": "电控 DPR", "likely_scan": False, "elapsed_seconds": 5},
            {"status": "done", "kind_label": "电控 DPR", "extract": False, "elapsed_seconds": 2},
            {"status": "done", "kind_label": "电控 DPR", "stopped_early": True, "elapsed_seconds": 50},
        ]
        est = estimate_seconds(hist, kind_label="电控 DPR", likely_scan=False)
        self.assertEqual((est["estimate_seconds"], est["estimate_n"], est["estimate_scope"]), (750, 2, "同类型同介质"))
        est = estimate_seconds(hist, kind_label="电控 DPR", likely_scan=True)
        self.assertEqual((est["estimate_seconds"], est["estimate_scope"]), (1700, "同类型同介质"))
        est = estimate_seconds(hist, kind_label="逆变器 SR", likely_scan=True)
        self.assertEqual((est["estimate_seconds"], est["estimate_scope"]), (300, "同类型"))
        est = estimate_seconds(hist, kind_label="非电控规格", likely_scan=False)
        self.assertEqual((est["estimate_n"], est["estimate_scope"]), (4, "全部历史"))
        self.assertEqual(estimate_seconds([], kind_label="电控 DPR", likely_scan=False)["estimate_n"], 0)


if __name__ == "__main__":
    unittest.main()
