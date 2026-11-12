"""整表黄金：专家认可的核对表冻结后，逐格守住状态与数字。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from electrical.eval import ROW_SCHEMA, _numbers, freeze, load_review_rows, score_rows
from electrical.schema import STATUS_FOUND, STATUS_MISS, STATUS_PARTIAL

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "examples" / "golden" / "dhts160_dpr.json"
LESSONS = ROOT.parent / "electrical-krow" / ".insights" / "lessons"

HEADERS = ["核对状态", "分组", "需求序号", "需求条目", "抽出值", "页码", "条款号", "原文摘录", "人工填写", "复核备注", "置信度"]


def _workbook_from(rows: list[dict], path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "电控设计需求"
    ws.append(["XCM控制器前期设计最小化输入清单（规格书抽取核对）"])
    ws.append(HEADERS)
    for r in rows:
        ws.append([
            r["status"], "", str(r["seq"]), r["name"], r["value"],
            r.get("page", ""), r.get("clause", ""), "", "", "", "",
        ])
    wb.save(path)
    return path


class GoldenFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_golden_is_full_table(self) -> None:
        self.assertEqual(self.spec["schema"], ROW_SCHEMA)
        rows = self.spec["rows"]
        self.assertEqual([r["seq"] for r in rows], list(range(1, 117)))
        statuses = {r["status"] for r in rows}
        self.assertEqual(statuses, {STATUS_FOUND, STATUS_MISS, STATUS_PARTIAL})
        for r in rows:
            if r["status"] == STATUS_MISS:
                self.assertEqual(r["value"], "未检索到", r["seq"])
            else:
                self.assertNotEqual(r["value"], "未检索到", r["seq"])
                self.assertNotIn("page", r)
        self.assertEqual(self.spec["compare"]["page"], "不比对")

    def test_golden_reflects_active_lessons(self) -> None:
        by_seq = {r["seq"]: r for r in self.spec["rows"]}
        # 行车升压 / 升压充电不得被 6.5.4 三种模式与 85kW 顶替
        self.assertIn("85kW", by_seq[4]["value_must_not"])
        self.assertIn("三种模式", by_seq[111]["value_must_not"])
        self.assertEqual(by_seq[111]["status"], STATUS_PARTIAL)
        # 极对数×转速只到局部对应
        self.assertEqual(by_seq[31]["status"], STATUS_PARTIAL)
        self.assertEqual(by_seq[48]["status"], STATUS_PARTIAL)
        # 耐电压不是 Continuous HVDC 950V
        self.assertIn("950", by_seq[14]["value_must_not"])
        # Boost输出性能不得抄升压效率整段（2026-09-16）
        self.assertIn("效率", by_seq[61]["value_must_not"])
        self.assertEqual(by_seq[61]["value"], "450 V")
        # P3 ASC 当份 6.5.8.1 写了 310Arms/20s/1300Arms@1ms，不再是「未检索到」；禁清单示例 1370
        for seq in (51, 53):
            self.assertEqual(by_seq[seq]["status"], "已检索到")
            self.assertEqual(by_seq[seq]["clause"], "6.5.8.1")
            self.assertIn("1370", by_seq[seq]["value_must_not"])
        self.assertIn("310", by_seq[51]["value"])
        self.assertIn("1300", by_seq[53]["value"])
        # 当份未给出的仍是未检索到，不得用方法标准号顶替
        for seq in (68, 95):
            self.assertEqual(by_seq[seq]["status"], STATUS_MISS)
        if LESSONS.is_dir():
            for r in self.spec["rows"]:
                if r.get("lesson"):
                    self.assertTrue((LESSONS / f"{r['lesson']}.md").is_file(), r["lesson"])

    def test_golden_has_no_forbidden_typical_values(self) -> None:
        blob = json.dumps(self.spec, ensure_ascii=False)
        self.assertNotRegex(blob, r"8000\s*小时")
        self.assertNotRegex(blob, r"通常\s*15\s*年")
        self.assertNotIn("参考 Q/JLP", blob)


class ScoreRowsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _rows(self) -> list[dict]:
        return [dict(r) for r in self.spec["rows"]]

    def test_identical_workbook_passes(self) -> None:
        xlsx = _workbook_from(self._rows(), self.dir / "same.xlsx")
        result = score_rows(xlsx, self.spec)
        self.assertTrue(result["ok"], result["failed"][:3])
        self.assertEqual(result["score"], "116/116")
        self.assertEqual(result["warned"], [])
        # 2026-09-16：#51/#53 P3 ASC 由未检索到改为已检索到（68/38 → 70/36）
        self.assertEqual(result["by_status"][STATUS_FOUND]["same"], 70)
        self.assertEqual(result["by_status"][STATUS_MISS]["same"], 36)
        self.assertEqual(result["by_status"][STATUS_PARTIAL]["same"], 10)

    def test_wording_change_only_warns_numbers_missing_fails(self) -> None:
        rows = self._rows()
        rows[66]["value"] = "压降 ≤35kPa（65℃、10L/min）"  # #67 措辞不同，数字齐
        rows[12]["value"] = "≥48MΩ"  # #13 丢了热态 2.5MΩ
        xlsx = _workbook_from(rows, self.dir / "text.xlsx")
        result = score_rows(xlsx, self.spec)
        self.assertFalse(result["ok"])
        self.assertTrue(any("#13" in f and "2.5" in f for f in result["failed"]))
        self.assertTrue(any("#67" in w and "措辞不同" in w for w in result["warned"]))
        self.assertFalse(any("#67" in f for f in result["failed"]))

    def test_status_drift_fails(self) -> None:
        rows = self._rows()
        rows[30]["status"] = STATUS_FOUND  # #31 局部对应被抬成已检索到
        rows[67]["status"] = STATUS_PARTIAL  # #68 未检索到被填
        rows[67]["value"] = "参考 Q/JLP 030602-07-2026A 7.3"
        xlsx = _workbook_from(rows, self.dir / "status.xlsx")
        result = score_rows(xlsx, self.spec)
        self.assertFalse(result["ok"])
        self.assertTrue(any("#31" in f and "状态" in f for f in result["failed"]))
        self.assertTrue(any("#68" in f and "应为未检索到" in f for f in result["failed"]))

    def test_lesson_bound_must_not_fails(self) -> None:
        rows = self._rows()
        rows[3]["value"] = "是；Boost/bypass/BUCK 三种模式，BUCK Max 85kW"  # #4 被 6.5.4 模式顶替
        rows[104]["value"] = "支持 HVIL 高压互锁"  # #105 用互锁勾选顶触指防护
        xlsx = _workbook_from(rows, self.dir / "lesson.xlsx")
        result = score_rows(xlsx, self.spec)
        self.assertTrue(any("#4" in f and "85kW" in f for f in result["failed"]))
        self.assertTrue(any("#105" in f and "HVIL" in f for f in result["failed"]))

    def test_clause_change_only_warns(self) -> None:
        rows = self._rows()
        rows[13]["clause"] = "6.9.3.2"
        xlsx = _workbook_from(rows, self.dir / "clause.xlsx")
        result = score_rows(xlsx, self.spec)
        self.assertTrue(result["ok"])
        self.assertTrue(any("#14" in w and "6.9.3.2" in w for w in result["warned"]))

    def test_missing_row_fails(self) -> None:
        rows = self._rows()[:-1]
        xlsx = _workbook_from(rows, self.dir / "short.xlsx")
        result = score_rows(xlsx, self.spec)
        self.assertTrue(any("#116" in f and "没有这一行" in f for f in result["failed"]))

    def test_freeze_round_trip(self) -> None:
        xlsx = _workbook_from(self._rows(), self.dir / "freeze.xlsx")
        spec = freeze(xlsx, source="DHTS160_DPR.docx", note="test")
        self.assertEqual(spec["schema"], ROW_SCHEMA)
        self.assertEqual(len(spec["rows"]), 116)
        self.assertEqual(spec["rows"][13]["clause"], "6.10.3.2")
        self.assertNotIn("page", spec["rows"][13])
        self.assertEqual(len(load_review_rows(xlsx)), 116)

    def test_number_extraction_normalizes(self) -> None:
        self.assertEqual(_numbers("≤35 kPa@65℃@10 L/min"), ["35", "65", "10"])
        self.assertEqual(_numbers("1,5 kW 和 1.50 kW"), ["1.5"])
        self.assertEqual(_numbers("未检索到"), [])


if __name__ == "__main__":
    unittest.main()
