"""出表结果对照：接口只读核对表上已有的抽出值、页码和原文，空值不拿示例填。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from electrical_krow.bridge import ensure_electrical
from electrical_krow.jobs import JobStore, review_sheet_items


class ReviewSheetItemTests(unittest.TestCase):
    def test_items_copy_the_sheet_and_leave_examples_out(self) -> None:
        ensure_electrical()
        from electrical.schema import ExtractedCell, empty_template_rows
        from electrical.write_excel import write_review_workbook

        example = "禁止填入的参考示例ABC"
        cells = empty_template_rows()
        found = cells[0]
        found.value = "48 V"
        found.page = "14"
        found.clause = "2.3.3.3"
        found.excerpt = "母线电压不超过 1000 V。"
        found.review_status = "已检索到"
        found.confidence = 0.95
        found.note = ""
        missed = cells[1]
        missed.value = ""
        missed.page = "9"
        missed.clause = ""
        missed.excerpt = ""
        missed.example = example
        missed.review_status = "未检索到"
        missed.note = ""
        partial = cells[2]
        partial.value = "局部量"
        partial.page = "6"
        partial.clause = "1.2"
        partial.excerpt = "原文只写了一半。"
        partial.review_status = "局部对应/需人工复核"
        partial.note = "请对照端子定义"
        partial.confidence = 0.95
        cells.append(
            ExtractedCell(
                name="当份多出来的线束要求",
                extra=True,
                value="屏蔽层单端接地",
                page="21",
                clause="4.2",
                excerpt="线束屏蔽层应单端接地。",
            )
        )

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            book = out / "spec_items.xlsx"
            write_review_workbook(
                cells, book,
                source_name="spec.docx", likely_scan=False, parser="test",
            )
            sheet_found = _sheet_row(book, found.name)
            sheet_miss = _sheet_row(book, missed.name)
            self.assertEqual(sheet_found["抽出值"], "48 V")
            self.assertEqual(sheet_found["页码"], "14")
            self.assertEqual(sheet_found["条款号"], "2.3.3.3")
            self.assertEqual(sheet_found["原文摘录"], "母线电压不超过 1000 V。")
            self.assertEqual(sheet_miss["抽出值"], "未检索到")
            self.assertIn(example, _guide_examples(book))

            items = review_sheet_items(book)
            by_name = {str(row["name"]): row for row in items if not row["extra"]}
            got = by_name[found.name]
            self.assertEqual(
                (got["value"], got["page"], got["clause"], got["excerpt"], str(got["seq"])),
                ("48 V", "14", "2.3.3.3", "母线电压不超过 1000 V。", sheet_found["需求序号"]),
            )
            self.assertEqual(got["excerpt"], sheet_found["原文摘录"])
            self.assertEqual(str(got["seq"]), sheet_found["需求序号"])
            self.assertEqual(got["status"], "已检索到")
            self.assertNotIn("example", got)
            empty = by_name[missed.name]
            self.assertEqual(empty["value"], "")
            self.assertEqual(empty["page"], "9")
            self.assertNotIn(example, json.dumps(empty, ensure_ascii=False))
            self.assertEqual(by_name[partial.name]["note"], "请对照端子定义")
            extras = [row for row in items if row["extra"]]
            self.assertEqual(len(extras), 1)
            self.assertEqual(extras[0]["name"], "当份多出来的线束要求")
            self.assertEqual(extras[0]["value"], "屏蔽层单端接地")
            self.assertEqual(extras[0]["page"], "21")
            self.assertEqual(extras[0]["excerpt"], "线束屏蔽层应单端接地。")
            self.assertTrue(all(not row["extra"] for row in items if row["name"] == found.name))

            record = {
                "id": "job-items",
                "status": "done",
                "username": "alice",
                "extract": True,
                "download": "/files/spec_items.xlsx",
                "source": "spec.docx",
            }
            (out / "jobs.jsonl").write_text(
                json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            store = JobStore(out)
            payload = store.review_items("job-items", username="alice")
            self.assertEqual(payload["items"][0]["value"], "48 V")
            self.assertNotIn(example, json.dumps(payload, ensure_ascii=False))
            history = (out / "jobs.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("母线电压", history)
            self.assertNotIn(example, history)
            with self.assertRaises(HTTPException) as raised:
                store.review_items("job-items", username="bob")
            self.assertEqual(raised.exception.status_code, 404)


def _sheet_row(path: Path, name: str) -> dict[str, str]:
    from openpyxl import load_workbook

    book = load_workbook(path, data_only=True)
    try:
        sheet = book["02_需求核对"]
        headers = [str(cell.value or "") for cell in next(sheet.iter_rows(min_row=2, max_row=2))]
        index = {text: i for i, text in enumerate(headers)}
        for raw in sheet.iter_rows(min_row=3, values_only=True):
            data = list(raw)
            if str(data[index["需求条目"]] or "") != name:
                continue
            return {
                key: "" if data[index[key]] is None else str(data[index[key]]).strip()
                for key in ("需求序号", "抽出值", "页码", "条款号", "原文摘录")
            }
    finally:
        book.close()
    raise AssertionError(name)


def _guide_examples(path: Path) -> str:
    from openpyxl import load_workbook

    book = load_workbook(path, data_only=True)
    try:
        sheet = book["05_条目说明"]
        return "\n".join(
            "" if cell is None else str(cell)
            for row in sheet.iter_rows(min_row=3, values_only=True)
            for cell in row
        )
    finally:
        book.close()


if __name__ == "__main__":
    unittest.main()
