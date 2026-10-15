from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from electrical_krow.arch_contrast import (
    COLUMNS,
    SECTION_COVER,
    SECTION_TOC,
    SHEET_MISSING,
    SHEET_NOTE,
    SHEET_ROWS,
    SHEET_TABLES,
    STATUS_PENDING,
    SourceDoc,
    Unreadable,
    boilerplate_lines,
    conditions,
    contrast_file_name,
    join_lines,
    match_heading,
    quantities,
    split_clauses,
    split_document,
    write_contrast,
)

_HEADER = "Model\nSX3id\nPart Name\nLDC\nRev No\n1.0\nPAGE\n{n}\n/8\n"
_PAGES = (
    (1, "LDC\nSourcing Request (SR)\n(LDC : Low Voltage DCDC Converter)\nLegal Disclaimer"),
    (2, _HEADER.format(n=2) + "LDC Revision history\nNo Sector Date Content Ver.\n1 ALL 2026.05.13 first version"),
    (
        3,
        _HEADER.format(n=3)
        + "< Contents >\n1. Overview\n2. System requirements\n2.1 Specification operation plan\n"
        + "2.2 Regulations / Certification\n2.2.1 Regulations\n2.3 Component configuration\n"
        + "2.4 Operating environment\n3. Parts requirement\n4.4 Submission of parts",
    ),
    (4, _HEADER.format(n=4) + "1. Overview\nThis document summarizes the requirements for the LDC supplier."),
    (
        5,
        _HEADER.format(n=5)
        + "2.1 Specification operation plan\nInformation on the specification shall be managed by HMC.\n"
        + "1) The supplier shall confirm every change.\n2) Closed-loop feedback applies within 10 ms (at 25 °C ambient, 50% load).\n"
        + "2.1.1 Durability\n•\nAll sub\n-\nparts last 15 years / 300,000 km (15 years / 300,000 km).",
    ),
    (6, _HEADER.format(n=6) + "The regulations in section 4.4 of the vehicle spec apply here as well.\n1) item one\n2) item two"),
    (
        7,
        _HEADER.format(n=7)
        + " ".join(f"{rpm} 210.00 {rpm * 0.022:.2f} 210.00 {rpm * 0.021:.2f}" for rpm in range(500, 5500, 500)),
    ),
    (8, _HEADER.format(n=8) + "4.4 Submission of parts\n1)\nAll parts submitted during development must meet the criteria.\n4) Connectors included."),
)


class ArchContrastTests(unittest.TestCase):
    def test_boilerplate_lines_drop_repeated_header(self) -> None:
        doc = SourceDoc("ldc.pdf", _PAGES)
        marks = boilerplate_lines(doc.pages)
        self.assertIn("Part Name", marks)
        self.assertIn("Rev No", marks)
        self.assertNotIn("1. Overview", marks)

    def test_match_heading_only_accepts_full_number_at_line_start(self) -> None:
        heads = [("1", "Overview"), ("4", "Parts development work"), ("4.4", "Submission of parts")]
        self.assertEqual(match_heading("4.4 Submission of parts\n1) all parts", heads), "4.4 Submission of parts")
        self.assertEqual(match_heading("section 4.4 applies", heads), "")
        self.assertEqual(match_heading("4) Connectors included", heads), "")
        self.assertEqual(match_heading("1. Overview\nThis document", heads), "1 Overview")

    def test_join_lines_repairs_hyphen_breaks(self) -> None:
        self.assertEqual(join_lines(["All sub", "-", "parts last", "15 years"]), "All sub-parts last 15 years")
        self.assertEqual(join_lines(["constant", "-", "speed (e.g."]), "constant-speed (e.g.")
        # 大写或数字开头的是子项破折号，不是连字符
        self.assertEqual(join_lines(["300,000km", "-", "15 years"]), "300,000km - 15 years")
        self.assertEqual(join_lines(["Test condition", "-", "Motor Speed : 15rpm"]), "Test condition - Motor Speed : 15rpm")

    def test_split_clauses_breaks_on_item_marks_not_hyphens(self) -> None:
        heads = [("2", "System requirements"), ("2.5", "Quality")]
        body = (
            "2.5.2 Quality requirements\nSupplier are responsible for issues.\nDurability\n•\nThe durability "
            "mentioned in laws must be guaranteed.\n※ ES/MS specifications must be met.\n1) sub\n-\nparts shall "
            "satisfy 15 years.\n2) Second item."
        )
        clauses = split_clauses(body, heads, STATUS_PENDING)
        self.assertEqual([c[1] for c in clauses], ["", "•", "※", "1)", "2)"])
        # 目录没列到的 2.5.2，上级 2.5 在目录里，也认作章节；标题本身不进原文
        self.assertTrue(all(c[0] == "2.5.2 Quality requirements" for c in clauses))
        self.assertEqual(clauses[0][2], "Supplier are responsible for issues.")
        # 短引导句「Durability」并入其后那条；「-」是连字符不是条款
        self.assertEqual(clauses[1][2], "• Durability The durability mentioned in laws must be guaranteed.")
        self.assertEqual(clauses[3][2], "1) sub-parts shall satisfy 15 years.")

    def test_split_numbers_rejoin_and_toc_is_not_a_schedule(self) -> None:
        from electrical_krow.arch_contrast import page_headings, rejoin_numbers, toc_headings

        # 文字层把章节号拆成「2」「.」「System requirements」、「3.1」「Design requirement」，拼回一行；后跟数字的刻度不拼
        self.assertEqual(
            rejoin_numbers(["2", ".", "System requirements", "2.3.", "Component configuration", "3.1", "Design requirement", "2", ".", "50k", "W"]),
            ["2. System requirements", "2.3. Component configuration", "3.1 Design requirement", "2", ".", "50k", "W"],
        )
        toc = "< Contents >\n1. Overview\n2\n.\nSystem requirements\n2.1. Specification\n2.3.\nComponent configuration\n2.4.\nOperating environment\n2.5\n.\nPerformance requirements\n3.\nParts requirement\n3.1. Design requirements"
        schedule = "② SW development process\nTcar\n1. Design Specification for HMC requirements\n2. Design Specification for controller\n3. Simulation results\nProto\n1. S/W Functional Verification Report\n2. Verification Report\n3. Inspection Items of delivery report"
        heads, toc_pages = toc_headings(((1, "cover"), (2, toc), (3, schedule)))
        self.assertEqual(toc_pages, {2})
        self.assertEqual(dict(heads)["2"], "System requirements")
        self.assertEqual(dict(heads)["2.3"], "Component configuration")
        self.assertEqual(dict(heads)["3"], "Parts requirement")
        self.assertNotIn("Design Specification for controller", dict(heads).values())
        # 正文里拆行的标题也认；2.3.1 不在目录但上级 2.3 在
        body = "2.\nSystem requirements\n2.3 Component configuration and development\n2.3.1 Component system configuration\nThe LDC shall be constructed.\n3.1\nDesign requirement\n-\nContinued"
        self.assertEqual(
            page_headings(body, heads),
            ["2 System requirements", "2.3 Component configuration", "2.3.1 Component system configuration", "3.1 Design requirements"],
        )
        clauses = split_clauses(body, heads, "")
        self.assertEqual([(c[0], c[2]) for c in clauses], [("2.3.1 Component system configuration", "The LDC shall be constructed."), ("3.1 Design requirements", "- Continued")])

    def test_hyphen_split_number_and_table_row_labels(self) -> None:
        # 「ES96200-10)」被拆成「-」「10)」：不是新条
        body = "2) ESAs requirements\n-\nInverter : ES 36500 (based on CISPR25 & ES96200\n-\n10)\n-\nLDC : ES37700 (based on CISPR25 & ES96200\n-\n10k)\n3) EMC checklist must be submitted"
        clauses = split_clauses(body, [], "")
        self.assertEqual([c[1] for c in clauses], ["2)", "3)"])
        self.assertIn("ES96200 - 10) - LDC : ES37700", clauses[0][2])
        # 表格的栏目名（Safety、Laws and Regulation）在上一句句号之后：归到下一条，不留在上一条末尾
        body = "Items\nRequest Specifications\nMarketability\n•\nMust guarantee NVH performance\n.\nLaws and\nRegulation\n•\nMust meet the laws\n.\nSafety\n•\nThe structure must guarantee safety\n.\nQuality"
        clauses = split_clauses(body, [], "")
        self.assertEqual(
            [c[2] for c in clauses],
            [
                "• Items Request Specifications Marketability Must guarantee NVH performance .",
                "• Laws and Regulation Must meet the laws .",
                "• Safety The structure must guarantee safety . Quality",
            ],
        )
        # 按词拆行时「Such」「Evaluation」也像栏目名：后面跟的不是栏目名或标记，就放回上一条，不另起一条
        body = "•\nMust meet the laws\n.\nSuch\nas\nthe\nsafety\nregulations\n.\nSafety\n•\nThe structure must be safe\n.\nEvaluation\nreport must provide\n."
        clauses = split_clauses(body, [], "")
        self.assertEqual(
            [c[2] for c in clauses],
            ["• Must meet the laws . Such as the safety regulations .", "• Safety The structure must be safe . Evaluation report must provide ."],
        )

    def test_quantities_and_conditions_are_lifted_verbatim(self) -> None:
        text = "• 99.85% reliability must be met (50% confidence level, system level and sub-parts) within 10 ms at -40 ~ 85 °C, per MS613-01 and ES91500-02 (160, 000 km/ 10 years)."
        self.assertEqual(quantities(text), "99.85%；50%；10 ms；-40 ~ 85 °C；160, 000 km；10 years")
        # 括号里只有数和单位的是数值不是条件；条件原样保留不改写
        self.assertEqual(conditions(text), "50% confidence level, system level and sub-parts")
        self.assertEqual(conditions("life of 15 years (15 years / 300,000 km)"), "")
        self.assertEqual(quantities("Rev No 001 Date 2026.06.XX Team3"), "")
        # 文字层把小数点、千分位两侧拆出空格：原样认下整个数，不只认后半截
        self.assertEqual(quantities("Must meet the 99 . 85 % reliability (Confidence level 50 % ) over 15 years / 300 , 000 km"), "99 . 85 %；50 %；15 years；300 , 000 km")

    def test_table_blocks_and_notice_lines_are_not_requirements(self) -> None:
        from electrical_krow.arch_contrast import hangul_is_minor, is_table_block, page_body

        # 坐标轴刻度、占位点、反复表头是表格块；带几个数的整句不是
        self.assertTrue(is_table_block("… … . . . 110 90 70 30 10 -10 -30 -50 -70 -90 -110 . . ."))
        self.assertTrue(is_table_block("3) 30min " + "Torque Nm Power kW " * 12))
        self.assertTrue(is_table_block("※ Coolant temp. (PE system inlet) : 65°C 转速/ rpm 120V 180V 250V 300V 350V 400V 450V 500 1000 1500 2000"))
        self.assertFalse(is_table_block("• All sub-parts last 15 years / 300,000 km (15 years / 300,000 km)."))
        self.assertFalse(is_table_block("2) Torque : Based on Motor torque, from 10Nm to Maximum torque per 10Nm interval (from -10Nm to Maximum)."))
        # 英文 SR 里按词拆成多行的韩文保密声明整行剔除；韩文为主的文件不剔
        english = (
            (1, "Speed : Based on Motor speed, 500rpm & from 1000rpm to Maximum speed per 1000rpm interval\n본\n문서는\n현대자동차\n기아의\n보호받습니다\n.\nTorque : 10Nm"),
            (2, "Need to provide Loss data for motoring & generating mode, not Efficiency values (unit : W)\n본\n문서는\n보호받습니다"),
        )
        self.assertTrue(hangul_is_minor(english))
        body = page_body(english[0][1], frozenset(), drop_hangul=True)
        self.assertEqual(body.splitlines()[1:], [".", "Torque : 10Nm"])
        self.assertNotIn("기아의", body)
        korean = ((1, "요구사항 1) 전압 800V\n2) 토크 300Nm\n본 문서는 보호받습니다"),)
        self.assertFalse(hangul_is_minor(korean))
        self.assertIn("요구사항 1) 전압 800V", page_body(korean[0][1], frozenset(), drop_hangul=False))
        # 表格块进整表附件，条目里只留索引、不取数
        pages = ((1, "1) Rated duration : 3min / 10min / 30min\n2) " + "Torque Nm Power kW " * 12 + "\n3) Coolant temp : 65°C"),)
        rows, tables = split_document(SourceDoc("perf.pdf", pages))
        self.assertEqual(len(tables), 1)
        self.assertEqual([r[6] for r in rows], ["1)", "2)", "3)"])
        self.assertIn(SHEET_TABLES, rows[1][7])
        self.assertEqual((rows[1][8], rows[1][9]), ("", ""))
        self.assertEqual(rows[0][8], "3min；10min；30min")

    def test_split_document_breaks_pages_into_clauses_and_marks_pending(self) -> None:
        rows, tables = split_document(SourceDoc("260605_LDC_SR.pdf", _PAGES))
        self.assertEqual(len(rows), 14)
        self.assertEqual(len(tables), 1)
        by_page: dict[int, list[list[object]]] = {}
        for row in rows:
            by_page.setdefault(int(row[3]), []).append(row)
        self.assertEqual(by_page[1][0][5], SECTION_COVER)
        self.assertEqual(by_page[3][0][5], SECTION_TOC)
        self.assertEqual((by_page[4][0][5], by_page[4][0][6]), ("1 Overview", ""))
        # 第 5 页：整句说明自成一条，1) 2) 各一条，2) 带数值和条件，2.1.1 子标题下的要点连字符修好
        p5 = by_page[5]
        self.assertEqual([r[6] for r in p5], ["", "1)", "2)", "•"])
        self.assertEqual(p5[0][5], "2.1 Specification operation plan")
        self.assertEqual(p5[0][7], "Information on the specification shall be managed by HMC.")
        self.assertEqual(p5[1][7], "1) The supplier shall confirm every change.")
        self.assertEqual(p5[2][8], "10 ms；25 °C；50%")
        self.assertEqual(p5[2][9], "at 25 °C ambient, 50% load")
        self.assertEqual(p5[3][5], "2.1.1 Durability")
        self.assertIn("sub-parts", p5[3][7])
        self.assertEqual(p5[3][8], "15 years；300,000 km")
        self.assertEqual(p5[3][9], "")
        self.assertEqual(p5[0][4], "5")
        # 第 6 页没有标题：章节沿用上一页末尾的 2.1.1，备注注明；「section 4.4」不算章节
        self.assertEqual([r[5] for r in by_page[6]], ["2.1.1 Durability"] * 3)
        self.assertTrue(all("章节沿用上一页" in str(r[14]) for r in by_page[6]))
        # 第 2 页在任何章节之前：章节留空，不写待确认
        self.assertEqual(by_page[2][0][5], "")
        self.assertEqual(tables[0][3], 7)
        self.assertIn(SHEET_TABLES, by_page[7][0][7])
        # 第 8 页：「1)」单独一行，正文在下一行；章节来自目录
        self.assertEqual([(r[5], r[6]) for r in by_page[8]], [("4.4 Submission of parts", "1)"), ("4.4 Submission of parts", "4)")])
        self.assertEqual(by_page[8][0][7], "1) All parts submitted during development must meet the criteria.")
        for row in rows:
            self.assertEqual(row[1], "LDC")
            self.assertEqual(row[10], STATUS_PENDING)
            self.assertEqual((row[11], row[12], row[13]), ("", "", ""))
            self.assertNotIn("Part Name", str(row[7]))
            self.assertNotIn("PAGE", str(row[7]))
            self.assertNotIn("Requirements Met", str(row[7]))

    def test_write_contrast_builds_sheets_and_lists_unreadable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "out.xlsx"
            result = write_contrast(
                [SourceDoc("260605_LDC_SR.pdf", _PAGES)],
                [Unreadable("MCU_SWSR.pdf", 99, "没有文字层，未拆条，未补写内容。")],
                dest,
            )
            self.assertEqual((result.files, result.rows, result.tables), (1, 14, 1))
            book = load_workbook(dest, data_only=True)
            try:
                self.assertEqual(book.sheetnames, [SHEET_NOTE, SHEET_ROWS, SHEET_TABLES, SHEET_MISSING])
                rows = book[SHEET_ROWS]
                self.assertEqual(tuple(cell.value for cell in rows[1]), COLUMNS)
                self.assertEqual(rows.max_row, 15)
                self.assertEqual(rows.freeze_panes, "A2")
                self.assertGreaterEqual(rows.column_dimensions["H"].width, 60)
                status_col = COLUMNS.index("状态") + 1
                statuses = {rows.cell(r, status_col).value for r in range(2, rows.max_row + 1)}
                self.assertEqual(statuses, {STATUS_PENDING})
                fit_col = COLUMNS.index("能否满足") + 1
                filled = [rows.cell(r, fit_col).value for r in range(2, rows.max_row + 1) if rows.cell(r, fit_col).value]
                self.assertEqual(filled, [])
                qty_col = COLUMNS.index("数值与单位") + 1
                self.assertIn("10 ms；25 °C；50%", [rows.cell(r, qty_col).value for r in range(2, rows.max_row + 1)])
                missing = book[SHEET_MISSING]
                self.assertEqual(missing.cell(2, 1).value, "MCU_SWSR.pdf")
                self.assertEqual(missing.cell(2, 2).value, 99)
                note = "\n".join(str(c.value or "") for row in book[SHEET_NOTE].iter_rows() for c in row)
                self.assertIn("待确认", note)
                # 给业务人员看的表，不带项目内部编号和合同用语
                for word in ("第2项", "甲方", "本期", "验收"):
                    self.assertNotIn(word, note)
            finally:
                book.close()

    def test_write_contrast_refuses_when_nothing_readable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(ValueError):
                write_contrast([], [Unreadable("BHDC.pdf", 67, "没有文字层")], Path(raw) / "x.xlsx")

    def test_contrast_file_name_is_prefixed(self) -> None:
        from datetime import datetime

        self.assertEqual(contrast_file_name(datetime(2026, 10, 15, 15, 30, 0)), "架构对照-20261015-153000.xlsx")


if __name__ == "__main__":
    unittest.main()
