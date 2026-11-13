from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook, load_workbook

from electrical_krow.enterprise_test import (
    LINKED,
    PENDING,
    SHEET_COMPARE,
    SHEET_INTAKE,
    SHEET_LIST,
    Clock,
    build_enterprise_test,
    clock_started,
    extract_from_pages,
    week_due,
)


def _sheet(path: Path, name: str) -> list[tuple]:
    book = load_workbook(path, data_only=True)
    try:
        return [tuple(row) for row in book[name].iter_rows(values_only=True)]
    finally:
        book.close()


def _intake(path: Path) -> dict[str, str]:
    rows = _sheet(path, SHEET_INTAKE)[1:]
    return {str(label): "" if value is None else str(value) for label, value in rows}


class EnterpriseTestTests(unittest.TestCase):
    def test_clock_stays_off_until_three_fields_exist(self) -> None:
        self.assertFalse(clock_started(Clock("2026-11-02", "自然日", "")))
        self.assertFalse(clock_started(Clock("2026-11-02", "", "A")))
        self.assertFalse(clock_started(Clock("", "工作日", "A")))
        self.assertFalse(clock_started(Clock("11月2日", "自然日", "A")))
        self.assertTrue(clock_started(Clock("2026-11-02", "自然日", "A")))
        self.assertIsNone(week_due(Clock("2026-11-02", "自然日", "")))

    def test_week_due_counts_seven_calendar_or_working_days(self) -> None:
        self.assertEqual(week_due(Clock("2026-11-02", "自然日", "A")).isoformat(), "2026-11-09")
        self.assertEqual(week_due(Clock("2026-11-02", "工作日", "A")).isoformat(), "2026-11-10")
        self.assertEqual(week_due(Clock("2026-11-07", "工作日", "A")).isoformat(), "2026-11-17")

    def test_pages_keep_excerpt_and_skip_plain_clauses(self) -> None:
        items = extract_from_pages(
            [("12", "6.2 绝缘电阻试验\n3.1 驱动电机控制器\n6.3 耐电压测试")],
            document="企标.pdf",
        )
        self.assertEqual(
            [(item.clause_id, item.name, item.page, item.excerpt) for item in items],
            [
                ("6.2", "绝缘电阻试验", "12", "6.2 绝缘电阻试验"),
                ("6.3", "耐电压测试", "12", "6.3 耐电压测试"),
            ],
        )

    def test_linked_items_enter_the_list_and_pending_stay_on_compare(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            standard = folder / "企标.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.append(["条款号", "测试项", "页码", "原文摘录"])
            sheet.append(["6.2", "绝缘电阻试验", "12", "6.2 绝缘电阻试验"])
            sheet.append(["6.4", "湿热试验", "", ""])
            book.save(standard)
            book.close()
            existing = folder / "既有.txt"
            existing.write_text("绝缘电阻试验\n盐雾试验\n", encoding="utf-8")
            dest = folder / "out.xlsx"
            result = build_enterprise_test(
                standard,
                dest,
                existing=existing,
                supplier="供应商甲",
                clock=Clock(),
            )
            self.assertFalse(result.clock_started)
            self.assertEqual(result.listed, 1)
            self.assertEqual(result.pending, 2)
            intake = _intake(dest)
            self.assertEqual(intake["一周时钟"], "未起算")
            self.assertEqual(intake["清单结构到期日"], "")
            self.assertEqual(intake["指定供应商"], "供应商甲")
            self.assertEqual(intake["测试用例规则"], "未提供")
            self.assertEqual(intake["测试报告阶段模板"], "未提供")
            cases = _sheet(dest, "测试用例")
            self.assertEqual(cases[1][0], "6.2")
            self.assertEqual(cases[1][6], "用例初稿")
            self.assertEqual(cases[1][8], None)
            self.assertEqual(len(cases), 2)
            listed = _sheet(dest, SHEET_LIST)
            self.assertEqual(listed[1][0], "6.2")
            self.assertEqual(listed[1][4], "12")
            self.assertEqual(listed[1][6], LINKED)
            self.assertEqual(len(listed), 2)
            compared = _sheet(dest, SHEET_COMPARE)
            by_existing = {row[4]: row for row in compared[1:]}
            self.assertEqual(by_existing["绝缘电阻试验"][5], "对应")
            self.assertEqual(by_existing["盐雾试验"][6], PENDING)
            humid = [row for row in compared[1:] if row[0] == "6.4"][0]
            self.assertEqual(humid[6], PENDING)

    def test_started_clock_writes_due_and_version(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            standard = folder / "std.txt"
            standard.write_text("6.2 绝缘电阻试验\n", encoding="utf-8")
            dest = folder / "out.xlsx"
            result = build_enterprise_test(
                standard,
                dest,
                clock=Clock("2026-11-02", "自然日", "V3"),
            )
            self.assertTrue(result.clock_started)
            self.assertEqual(result.due, "2026-11-09")
            self.assertEqual(result.listed, 0)
            intake = _intake(dest)
            self.assertEqual(intake["一周时钟"], "已起算")
            self.assertEqual(intake["资料版本"], "V3")
            self.assertEqual(len(_sheet(dest, SHEET_LIST)), 1)

    def test_human_note_is_kept(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            standard = folder / "企标.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.append(["条款号", "测试项", "页码", "原文摘录"])
            sheet.append(["6.2", "绝缘电阻试验", "12", "原文"])
            book.save(standard)
            book.close()
            dest = folder / "out.xlsx"
            build_enterprise_test(standard, dest, clock=Clock())
            saved = load_workbook(dest)
            saved[SHEET_LIST]["H2"] = "改为抽检"
            saved.save(dest)
            saved.close()
            build_enterprise_test(standard, dest, clock=Clock())
            self.assertEqual(_sheet(dest, SHEET_LIST)[1][7], "改为抽检")

    def test_fixed_rule_fills_case_and_other_item_stays_draft(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            standard = folder / "企标.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.append(["条款号", "测试项", "页码", "原文摘录"])
            sheet.append(["6.2", "绝缘电阻试验", "12", "6.2 绝缘电阻试验"])
            sheet.append(["6.3", "耐电压测试", "13", "6.3 耐电压测试"])
            book.save(standard)
            book.close()
            rules = folder / "规则.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.append(["条款号", "测试项", "规则版本", "规则状态", "测试目的", "测试步骤", "判定准则"])
            sheet.append(["6.2", "绝缘电阻试验", "R1", "固定规则", "测绝缘", "施加电压", "不击穿"])
            sheet.append(["6.3", "耐电压测试", "R1", "初稿", "不要用", "不要抄", "不要抄"])
            book.save(rules)
            book.close()
            dest = folder / "企标测试清单-20261110-120000.xlsx"
            result = build_enterprise_test(standard, dest, rules=rules, clock=Clock())
            self.assertEqual((result.cases, result.ruled, result.drafts), (2, 1, 1))
            self.assertIsNone(result.report_path)
            rows = {row[0]: row for row in _sheet(dest, "测试用例")[1:]}
            self.assertEqual(rows["6.2"][6], "按规则生成")
            self.assertEqual(rows["6.2"][8], "施加电压")
            self.assertEqual(rows["6.2"][5], "R1")
            self.assertEqual(rows["6.3"][6], "用例初稿")
            self.assertIsNone(rows["6.3"][8])
            self.assertEqual(_intake(dest)["规则版本"], "R1")
            self.assertEqual(_sheet(dest, "填报记录")[2][2], "未提供阶段模板，未另作格式")

    def test_template_fills_known_fields_and_keeps_unknown_column(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            standard = folder / "std.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.append(["条款号", "测试项", "页码", "原文摘录"])
            sheet.append(["6.2", "绝缘电阻试验", "12", "原文"])
            book.save(standard)
            book.close()
            template = folder / "报告.xlsx"
            book = Workbook()
            sheet = book.active
            sheet["A1"] = "供应商"
            sheet["B1"] = "{{供应商}}"
            sheet["A3"] = "条款号"
            sheet["B3"] = "测试项"
            sheet["C3"] = "试验电压"
            sheet["A4"] = "样例"
            book.save(template)
            book.close()
            dest = folder / "企标测试清单-20261110-120000.xlsx"
            result = build_enterprise_test(
                standard,
                dest,
                report_template=template,
                supplier="供应商甲",
                clock=Clock(),
            )
            self.assertEqual(result.report_status, "已按模板填报")
            assert result.report_path is not None
            filled = load_workbook(result.report_path, data_only=True)
            try:
                report = filled.active
                self.assertEqual(report["B1"].value, "供应商甲")
                self.assertEqual(report["A4"].value, "样例")
                self.assertEqual(report["A5"].value, "6.2")
                self.assertEqual(report["B5"].value, "绝缘电阻试验")
                self.assertIsNone(report["C5"].value)
            finally:
                filled.close()

    def test_docx_template_replaces_placeholder_and_appends_case(self) -> None:
        from docx import Document

        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            book = Workbook()
            sheet = book.active
            sheet.append(["条款号", "测试项", "页码", "原文摘录"])
            sheet.append(["6.2", "绝缘电阻试验", "12", "原文"])
            book.save(folder / "std.xlsx")
            book.close()
            template = folder / "方案.docx"
            document = Document()
            document.add_paragraph("供应商：{{供应商}}")
            table = document.add_table(rows=1, cols=2)
            table.rows[0].cells[0].text = "条款号"
            table.rows[0].cells[1].text = "测试项"
            document.save(template)
            dest = folder / "企标测试清单-20261110-120000.xlsx"
            result = build_enterprise_test(
                folder / "std.xlsx",
                dest,
                plan_template=template,
                supplier="供应商甲",
                clock=Clock(),
            )
            assert result.plan_path is not None
            filled = Document(str(result.plan_path))
            self.assertEqual(filled.paragraphs[0].text, "供应商：供应商甲")
            self.assertEqual(filled.tables[0].rows[1].cells[0].text, "6.2")
            self.assertEqual(filled.tables[0].rows[1].cells[1].text, "绝缘电阻试验")


if __name__ == "__main__":
    unittest.main()
