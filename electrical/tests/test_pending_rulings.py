"""待专家口径标注：只进复核备注和批注，不改抽出值、不改检索结论。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from electrical import pending_rulings as pr
from electrical.schema import (
    STATUS_FOUND,
    STATUS_MISS,
    STATUS_PARTIAL,
    empty_template_rows,
    finalize_retrieval_statuses,
    review_item_no,
)
from electrical.write_excel import _review_status, write_review_workbook

RULINGS = pr._parse(
    {
        "rulings": [
            {"id": "ratio", "items": [75], "when": "filled", "note": "整组还是只填 P3"},
            {"id": "p3-speed", "items": [46], "when": "empty", "family": ["dpr"], "note": "能否取额定功率点转速"},
            {
                "id": "drop-cae",
                "items": [67, 115],
                "when": "filled",
                "family": ["inverter"],
                "match": "mbar",
                "note": "CAE 目标算不算指标",
            },
        ]
    }
)


def _rows():
    cells = empty_template_rows()
    return cells, {review_item_no(c.seq): c for c in cells}


class ParseAndApplyTests(unittest.TestCase):
    def test_parse_defaults_and_validation(self) -> None:
        self.assertEqual([r.id for r in RULINGS], ["ratio", "p3-speed", "drop-cae"])
        self.assertEqual(RULINGS[0].family, ())
        self.assertEqual(RULINGS[0].when, "filled")
        # 没 note / 没 items 的条目丢弃；when 非法回落 any
        parsed = pr._parse([{"items": [1]}, {"note": "x"}, {"items": 3, "when": "weird", "note": "y"}])
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].items, (3,))
        self.assertEqual(parsed[0].when, "any")

    def test_when_family_match_gates(self) -> None:
        cells, b = _rows()
        b[75].value = "P3 12.830"
        b[75].confidence = 0.9
        b[67].value = "压降≤25kPa@10L/min"  # DPR 的压降不标
        b[67].confidence = 0.9
        n = pr.apply_pending_rulings(cells, "dpr", RULINGS)
        self.assertEqual(n, 2)  # #75 filled + #46 empty(dpr)
        self.assertTrue(b[75].note.startswith(pr.PENDING_PREFIX))
        self.assertIn("整组", b[75].note)
        self.assertTrue(b[46].note.startswith(pr.PENDING_PREFIX))
        self.assertEqual(b[67].note, "")
        # inverter：mbar 命中才标
        cells2, b2 = _rows()
        b2[67].value = "< 300mbar, @12lpm @65℃"
        b2[67].confidence = 0.95
        b2[115].value = "≤25kPa"
        b2[115].confidence = 0.95
        n2 = pr.apply_pending_rulings(cells2, "inverter", RULINGS)
        self.assertEqual(n2, 1)
        self.assertIn("CAE", b2[67].note)
        self.assertEqual(b2[115].note, "")
        self.assertEqual(b2[46].note, "")  # family dpr 的条不标 inverter

    def test_value_and_status_untouched(self) -> None:
        cells, b = _rows()
        b[75].value = "P3 12.830"
        b[75].confidence = 0.9
        b[24].value = "140kW"
        b[24].confidence = 0.6
        b[24].note = "由物理公式计算：P=Tn/9550（代入 …）"
        pr.apply_pending_rulings(cells, "dpr", RULINGS)
        self.assertEqual(b[75].value, "P3 12.830")
        self.assertEqual(_review_status(b[75]), STATUS_FOUND)
        self.assertEqual(_review_status(b[46]), STATUS_MISS)
        finalize_retrieval_statuses(cells)
        self.assertEqual(b[75].review_status, STATUS_FOUND)
        self.assertEqual(b[46].review_status, STATUS_MISS)
        # 原有备注保留在前，标注追加在后；剥掉标注后仍是公式备注
        self.assertEqual(b[24].review_status, STATUS_PARTIAL)
        self.assertTrue(b[24].note.startswith("由物理公式计算"))

    def test_apply_twice_does_not_stack(self) -> None:
        cells, b = _rows()
        b[75].value = "P3 12.830"
        b[75].confidence = 0.9
        pr.apply_pending_rulings(cells, "dpr", RULINGS)
        self.assertEqual(pr.apply_pending_rulings(cells, "dpr", RULINGS), 0)
        self.assertEqual(b[75].note.count(pr.PENDING_PREFIX), 1)

    def test_note_helpers(self) -> None:
        note = "由物理公式计算：R=U/I；待专家口径：xx"
        self.assertEqual(pr.note_without_pending(note), "由物理公式计算：R=U/I")
        self.assertEqual(pr.pending_text(note), "待专家口径：xx")
        self.assertEqual(pr.note_without_pending("待专家口径：xx"), "")
        self.assertEqual(pr.pending_text("普通备注"), "")


class WorkbookTests(unittest.TestCase):
    def test_cover_line_and_note_cell(self) -> None:
        cells, b = _rows()
        b[75].value = "ICE 7.119；主减 3.462；P3 12.830"
        b[75].confidence = 0.9
        b[24].value = "140kW"
        b[24].confidence = 0.95
        pr.apply_pending_rulings(cells, "dpr", RULINGS)
        with tempfile.TemporaryDirectory() as tmp:
            out = write_review_workbook(
                cells,
                Path(tmp) / "demo.xlsx",
                source_name="demo.pdf",
                likely_scan=False,
                parser="x",
                kind_label="电控 DPR",
                family="dpr",
                extract=True,
            )
            wb = load_workbook(out)
            cover = {r[0]: r[1] for r in wb["01_封面"].iter_rows(values_only=True) if r and r[0]}
            self.assertEqual(cover["已检索到"], 2)
            self.assertEqual(cover["局部对应/需人工复核"], 0)
            self.assertIn("待专家口径", cover)
            ws = wb["02_需求核对"]
            rows = {r[2].value: r for r in ws.iter_rows(min_row=3) if isinstance(r[2].value, int)}
            r75, r24 = rows[75], rows[24]
            self.assertEqual(r75[0].value, STATUS_FOUND)
            self.assertTrue(str(r75[9].value).startswith(pr.PENDING_PREFIX))
            self.assertIsNotNone(r75[4].comment)
            self.assertFalse(r24[9].value)
            self.assertIsNone(r24[4].comment)


class ShippedFileTests(unittest.TestCase):
    def test_shipped_pending_rulings_are_well_formed(self) -> None:
        path = pr.pending_rulings_path()
        if path is None:
            self.skipTest("没有 pending_rulings.json")
        rulings = pr.load_pending_rulings()
        self.assertTrue(rulings)
        valid_items = {review_item_no(c.seq) for c in empty_template_rows()}
        for r in rulings:
            self.assertTrue(r.note, r.id)
            self.assertTrue(set(r.items) <= valid_items, (r.id, r.items))
            self.assertIn(r.when, {"filled", "empty", "any"})
            for fam in r.family:
                self.assertIn(fam, {"dpr", "inverter", "generic"}, r.id)
            self.assertTrue(r.lesson, f"{r.id} 缺 lesson 引用")
        # 每条都要有复盘可追
        lessons = path.parent.parent.parent / ".insights" / "lessons"
        if lessons.is_dir():
            for r in rulings:
                self.assertTrue((lessons / f"{r.lesson}.md").is_file(), r.lesson)


if __name__ == "__main__":
    unittest.main()
