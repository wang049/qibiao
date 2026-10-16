from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from electrical_krow.arch_contrast import (
    COLUMNS,
    SECTION_COVER,
    SECTION_TOC,
    REQ_COLUMNS,
    SHEET_ATTACH,
    SHEET_NOTE,
    SHEET_REQS,
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
        # 每个数前带原文里紧挨着的几个字：从最近的句读起、右对齐截到 5 个词；这段之前就开了的括号，右括号及前面的不算
        self.assertEqual(
            quantities(text),
            "99.85%；reliability must be met (50%；within 10 ms；at -40 ~ 85 °C；per MS613-01 and ES91500-02 (160, 000 km / 10 years",
        )
        # 括号里只有数和单位的是数值不是条件；条件原样保留不改写
        self.assertEqual(conditions(text), "50% confidence level, system level and sub-parts")
        self.assertEqual(conditions("life of 15 years (15 years / 300,000 km)"), "")
        self.assertEqual(quantities("Rev No 001 Date 2026.06.XX Team3"), "")
        # 文字层把小数点、千分位两侧拆出空格：原样认下整个数，不只认后半截
        self.assertEqual(
            quantities("Must meet the 99 . 85 % reliability (Confidence level 50 % ) over 15 years / 300 , 000 km"),
            "Must meet the 99 . 85 %；reliability (Confidence level 50 %)；over 15 years / 300 , 000 km",
        )
        # 一条里多个数：各带各的引导词；「etc.」「spec.」不当句读切断；数后的「↑」和合上的右括号一起留；条款标记不算引导词
        self.assertEqual(
            quantities(
                "3) Voltage/current sensor Design Contents Specification HW spec. (error) Voltage ( AC,Link,DC , etc.) 3% "
                "Current 5% Final spec. (include Calibration) Voltage 1% Output Current 2% (400W ↑ )"
            ),
            "Voltage ( AC,Link,DC , etc.) 3%；Current 5%；(include Calibration) Voltage 1%；Output Current 2%；(400W ↑)",
        )
        self.assertEqual(quantities("1. 26 kW TBD"), "26 kW")
        # 两头都带单位的范围并成一条；「-」不当范围连接；并成范围后重复出现的整句不再列；「@」「=」保留
        self.assertEqual(
            quantities("CISPR 25 2021 150kHz ~ 108MHz, E field 150 kHz to 30MHz; E field 150 kHz to 30MHz. Io= 180A - 91% ↑ @ 10V ↑, x 180A = 2.30kW"),
            "CISPR 25 2021 150kHz ~ 108MHz；E field 150 kHz to 30MHz；Io= 180A；- 91% ↑；@ 10V ↑；x 180A；= 2.30kW",
        )
        # 中文按字截；「以上」「以下」「max」是数的一部分
        self.assertEqual(
            quantities("工作电压范围 250 V 以上，环境温度 -40 ℃ 以下时降额。输出电流 5 A max"),
            "工作电压范围 250 V 以上；环境温度 -40 ℃ 以下；输出电流 5 A max",
        )

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
        # 表格块整块保留在对应条目中、不取数
        pages = ((1, "1) Rated duration : 3min / 10min / 30min\n2) " + "Torque Nm Power kW " * 12 + "\n3) Coolant temp : 65°C"),)
        rows, tables = split_document(SourceDoc("perf.pdf", pages))
        self.assertEqual(len(tables), 1)
        self.assertEqual([r[6] for r in rows], ["1)", "2)", "3)"])
        self.assertIn("本页表格块", rows[1][8])
        self.assertEqual((rows[1][9], rows[1][10]), ("", ""))
        self.assertEqual(rows[0][9], "3min / 10min / 30min")

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
        self.assertEqual(p5[0][8], "Information on the specification shall be managed by HMC.")
        self.assertEqual(p5[1][8], "1) The supplier shall confirm every change.")
        self.assertEqual(p5[2][9], "Closed-loop feedback applies within 10 ms；(at 25 °C；ambient, 50%")
        self.assertEqual(p5[2][10], "at 25 °C ambient, 50% load")
        self.assertEqual(p5[3][5], "2.1.1 Durability")
        self.assertIn("sub-parts", p5[3][8])
        self.assertEqual(p5[3][9], "All sub-parts last 15 years / 300,000 km")  # 「/」连的成对量算一组；括号里重复的同一组数不再列
        self.assertEqual(p5[3][10], "")
        self.assertEqual(p5[0][4], "5")
        # 第 6 页没有标题：章节沿用上一页末尾的 2.1.1，备注注明；「section 4.4」不算章节
        self.assertEqual([r[5] for r in by_page[6]], ["2.1.1 Durability"] * 3)
        self.assertTrue(all("章节沿用上一页" in str(r[15]) for r in by_page[6]))
        # 第 2 页在任何章节之前：章节留空，不写待确认
        self.assertEqual(by_page[2][0][5], "")
        self.assertEqual(tables[0][3], 7)
        self.assertIn("本页为数值表", by_page[7][0][8])
        # 第 8 页：「1)」单独一行，正文在下一行；章节来自目录
        self.assertEqual([(r[5], r[6]) for r in by_page[8]], [("4.4 Submission of parts", "1)"), ("4.4 Submission of parts", "4)")])
        self.assertEqual(by_page[8][0][8], "1) All parts submitted during development must meet the criteria.")
        for row in rows:
            self.assertEqual(row[1], "LDC")
            self.assertEqual(row[11], STATUS_PENDING)
            self.assertEqual((row[12], row[13], row[14]), ("", "", ""))
            self.assertNotIn("Part Name", str(row[8]))
            self.assertNotIn("PAGE", str(row[8]))
            self.assertNotIn("Requirements Met", str(row[8]))

    def test_tables_read_by_grid_become_key_value_rows(self) -> None:
        from electrical_krow.arch_contrast import is_grid, strip_table_lines, table_entries

        # 控制要求表：Category 纵向合并沿用上一行；Requirement 是值，Remark 是条件
        grid = [
            ["Catego ry", "Item", "Requirement", "Remark"],
            ["Output voltage control", "Output voltage command range", "7V ~ 15.1V", "-"],
            ["", "Rate limit of output voltage command", "50V/s (Up/Down)", "-"],
            ["", "Output voltage ripple", "1.0 V ↓ (@Output current >10A)", "Based on oscilloscope"],
            ["Output current limit control", "Current ripple", "5 A ↓ pk_to_pk", ""],
        ]
        entries = table_entries(grid)
        self.assertEqual(
            [(e.item, e.value, e.remark) for e in entries],
            [
                ("Output voltage control / Output voltage command range", "7V ~ 15.1V", "-"),
                ("Output voltage control / Rate limit of output voltage command", "50V/s (Up/Down)", "-"),
                ("Output voltage control / Output voltage ripple", "1.0 V ↓ (@Output current >10A)", "Based on oscilloscope"),
                ("Output current limit control / Current ripple", "5 A ↓ pk_to_pk", ""),
            ],
        )
        self.assertEqual(entries[0].text, "Catego ry：Output voltage control | Item：Output voltage command range | Requirement：7V ~ 15.1V | Remark：-")
        # 横向合并的表头（Classification 跨三列）后面的空列也是项目栏；值格没单位时补单位栏；上一级换了，下一级不沿用
        grid2 = [
            ["Classification", "", "", "Unit", "Specification"],
            ["Environment", "Temperature (oper)", "Min/Max", "°C", "-40 / 105"],
            ["", "Humidity", "Max", "%", "90"],
            ["Input", "Voltage", "", "Vin", "110~310V"],
        ]
        self.assertEqual(
            [(e.item, e.value) for e in table_entries(grid2)],
            [("Environment / Temperature (oper) / Min/Max", "-40 / 105 °C"), ("Environment / Humidity / Max", "90 %"), ("Input / Voltage", "110~310V")],
        )
        # 「Contents | Specification」两组都像值栏时，最左那组当项目栏
        grid3 = [["Contents", "", "Specification"], ["LDC", "HW spec. (error) Voltage", "3%"], ["", "Current", "5%"]]
        self.assertEqual([(e.item, e.value) for e in table_entries(grid3)], [("LDC / HW spec. (error) Voltage", "3%"), ("LDC / Current", "5%")])
        # 「Category | Contents | Target」：两组要求栏时最右是值，Contents 归项目；认不出角色的栏带表头进条件列
        grid4 = [
            ["CATEGORY", "CONTENTS", "TARGET"],
            ["MECHANCAL", "MODAL", "> 300Hz @1ST MODE"],
            ["", "SHOCK - Bump", "Width 20G / 10G / 5G Time 11msec"],
        ]
        self.assertEqual(
            [(e.item, e.value) for e in table_entries(grid4)],
            [("MECHANCAL / MODAL", "> 300Hz @1ST MODE"), ("MECHANCAL / SHOCK - Bump", "Width 20G / 10G / 5G Time 11msec")],
        )
        grid5 = [
            ["Test items", "Notes", "Settings for evaluation", "Requirements"],
            ["RE (Radiated Emission)", "CISPR 25 Ed.5 : 2021", "150kHz~5.925GHz (ALSE)", ""],
        ]
        self.assertEqual(
            [(e.item, e.value, e.remark) for e in table_entries(grid5)],
            [("RE (Radiated Emission)", "", "CISPR 25 Ed.5 : 2021 Settings for evaluation：150kHz~5.925GHz (ALSE)")],
        )
        # 认不出项目／要求表头的表不拆；单行页眉表、一半以上行只有一格的碎块不算表
        self.assertEqual(table_entries([["Major Classification", "Sub Classification", "PROJECT", "Notes"], ["PE", "LDC 2.5kW", "V", ""]]), [])
        self.assertFalse(is_grid([["Model SX3id", "Part Name LDC", "PAGE 7/51"]]))
        self.assertFalse(is_grid([["After the limitation", "", ""], ["", "the time for", ""], ["return to", "", ""]]))
        self.assertTrue(is_grid(grid))
        # 表格的字从页面文字里去掉：文字层把「Category」拆成「Categor」「y」也能认；短行只在挨着表格行时一起去
        body = "3.3 Control Requirements\n2\n) \nLDC _continued\nCategor\ny\nItem\nRequirement\nRemark\nOutput voltage control\nOutput voltage command range\n7V ~ 15.1V\n-\n※ Tests use the vehicle battery."
        self.assertEqual(strip_table_lines(body, [grid]), "3.3 Control Requirements\n2\n) \nLDC _continued\n※ Tests use the vehicle battery.")
        # 整份拆条：表格行带「项目」，值进「数值与单位」，条件进「适用条件」，正文条目不再含表格文字
        doc = SourceDoc("ldc.pdf", _PAGES, {5: [grid]})
        rows, tables = split_document(doc)
        p5 = [r for r in rows if r[3] == 5]
        table_rows = [r for r in p5 if r[7]]
        self.assertEqual(len(table_rows), 4)
        self.assertEqual((table_rows[0][7], table_rows[0][9], table_rows[0][10]), ("Output voltage control / Output voltage command range", "7V ~ 15.1V", "-"))
        self.assertEqual(table_rows[0][5], "2.1.1 Durability")  # 表格挂在本页末尾所在的章节下
        self.assertEqual(table_rows[0][15], "表格行")
        self.assertTrue(all(r[11] == STATUS_PENDING for r in table_rows))
        self.assertFalse([t for t in tables if t[3] == 5])  # 拆成行的表不再整表进附件
        self.assertEqual([r[8] for r in p5 if not r[7]][:2], ["Information on the specification shall be managed by HMC.", "1) The supplier shall confirm every change."])

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
                # 只有两张：说明、需求清单（主表，整表和图表按页码并入需求清单）
                self.assertEqual(book.sheetnames, [SHEET_NOTE, SHEET_REQS])
                self.assertFalse(result.model_used)
                self.assertGreaterEqual(result.params, 1)
                rows = book[SHEET_REQS]
                self.assertEqual(tuple(cell.value for cell in rows[1]), REQ_COLUMNS)
                self.assertLess(rows.max_row - 1, result.rows)  # 封面、目录行不进需求清单
                self.assertEqual(rows.freeze_panes, "A2")
                status_col = REQ_COLUMNS.index("Currently status\n状态") + 1
                statuses = {rows.cell(r, status_col).value for r in range(2, rows.max_row + 1)}
                self.assertEqual(statuses, {STATUS_PENDING})
                for name in ("Priority\n优先级", "Comments\n意见", "From whom\n提出人", "HMC feedback\n客户反馈"):
                    col = REQ_COLUMNS.index(name) + 1
                    self.assertEqual([rows.cell(r, col).value for r in range(2, rows.max_row + 1) if rows.cell(r, col).value], [], name)
                qty_col = REQ_COLUMNS.index("数值与单位") + 1
                self.assertIn("Closed-loop feedback applies within 10 ms；(at 25 °C；ambient, 50%", [rows.cell(r, qty_col).value for r in range(2, rows.max_row + 1)])
                excerpt_col = REQ_COLUMNS.index("原文摘录") + 1
                self.assertTrue(any(str(rows.cell(r, excerpt_col).value or "").startswith("本页为数值表") for r in range(2, rows.max_row + 1)))
                note = "\n".join(str(c.value or "") for row in book[SHEET_NOTE].iter_rows() for c in row)
                self.assertIn("待确认", note)
                self.assertIn("MCU_SWSR.pdf（99 页）：没有文字层", note)  # 读不开的文件写在说明里，不另起一张表
                # 给业务人员看的表，不带项目内部编号和合同用语
                for word in ("第2项", "甲方", "本期", "验收"):
                    self.assertNotIn(word, note)
            finally:
                book.close()

    def test_row_height_follows_wrapped_text(self) -> None:
        from electrical_krow.arch_contrast import _lines_needed

        self.assertEqual(_lines_needed("短", 40), 1)
        self.assertEqual(_lines_needed("第 16 页「Reliability / 可靠度」；第 26 页「Reliability / 可靠度」；第 29 页「Durability / 可靠度」", 40), 3)
        self.assertEqual(_lines_needed("a\nb\nc", 40), 3)
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "out.xlsx"
            write_contrast([SourceDoc("260605_LDC_SR.pdf", _PAGES)], [], dest)
            book = load_workbook(dest)
            try:
                rows = book[SHEET_REQS]
                heights = [rows.row_dimensions[r].height for r in range(2, rows.max_row + 1)]
                self.assertTrue(all(h >= 30 for h in heights))
                self.assertGreater(max(heights), 30)  # 长原文的行比默认高，折行的字不被截掉
            finally:
                book.close()

    def test_write_contrast_refuses_when_nothing_readable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(ValueError):
                write_contrast([], [Unreadable("BHDC.pdf", 67, "没有文字层")], Path(raw) / "x.xlsx")

    def test_contrast_file_name_is_prefixed(self) -> None:
        from datetime import datetime

        self.assertEqual(contrast_file_name(datetime(2026, 10, 15, 15, 30, 0)), "架构对照-20261015-153000.xlsx")

    def test_write_contrast_formats_bilingual_excerpt_with_rule_and_model(self) -> None:
        import json

        with tempfile.TemporaryDirectory() as raw:
            dest_rule = Path(raw) / "rule.xlsx"
            write_contrast([SourceDoc("260605_LDC_SR.pdf", _PAGES)], [], dest_rule)
            book = load_workbook(dest_rule, data_only=True)
            try:
                rows = book[SHEET_REQS]
                excerpt_col = REQ_COLUMNS.index("原文摘录") + 1
                excerpts = [str(rows.cell(r, excerpt_col).value or "") for r in range(2, rows.max_row + 1)]
                clause_row = next(e for e in excerpts if "The supplier shall confirm every change." in e)
                self.assertIn(" / ", clause_row)
                self.assertIn("供应商应确认", clause_row)
            finally:
                book.close()

            def fake_ask(messages: list[dict[str, str]]) -> str:
                sys_text = messages[0].get("content", "") if messages else ""
                user_text = messages[-1].get("content", "") if messages else ""
                if "直译为简练、规范的中文工程表述" in sys_text:
                    out = []
                    for ln in user_text.splitlines():
                        if ln.startswith("序号 ") and "：" in ln:
                            seq = int(ln[3 : ln.index("：")])
                            out.append({"序号": seq, "译文": f"模型中文直译（序号{seq}）"})
                    return json.dumps(out, ensure_ascii=False)
                return "[]"

            dest_llm = Path(raw) / "llm.xlsx"
            res_llm = write_contrast([SourceDoc("260605_LDC_SR.pdf", _PAGES)], [], dest_llm, ask=fake_ask)
            self.assertTrue(res_llm.model_used)
            book = load_workbook(dest_llm, data_only=True)
            try:
                rows = book[SHEET_REQS]
                excerpt_col = REQ_COLUMNS.index("原文摘录") + 1
                excerpts = [str(rows.cell(r, excerpt_col).value or "") for r in range(2, rows.max_row + 1)]
                clause_row = next(e for e in excerpts if "The supplier shall confirm every change." in e)
                self.assertIn("The supplier shall confirm every change. / 模型中文直译", clause_row)
            finally:
                book.close()

    def test_split_document_preserves_post_toc_pages_when_first_heading_is_vector(self) -> None:
        pages = (
            (1, "PE System\nSourcing Request (SR)"),
            (2, _HEADER.format(n=2) + "Revision history\n1 ALL 2026.07.03 initial"),
            (
                3,
                _HEADER.format(n=3)
                + "< Contents >\n1. Overview\n2. System requirements\n2.1 Specification operation plan\n"
                + "2.2 Regulations\n2.3 Component configuration\n3. Parts requirement",
            ),
            # 第 4~5 页在目录之后，但页首标题「1. Overview」在 PDF 中被转曲未进文字层
            (4, _HEADER.format(n=4) + "1) Qualification Life : 15 years - 300,000 km.\n2) Warranty : 10 years - 160,000 km."),
            (5, _HEADER.format(n=5) + "3) All sub-parts shall satisfy automotive grade criteria."),
        )
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "pe.xlsx"
            res = write_contrast([SourceDoc("260703_PE_SR.pdf", pages)], [], dest)
            self.assertEqual(res.reqs, 3)
            book = load_workbook(dest, data_only=True)
            try:
                rows = book[SHEET_REQS]
                sec_col = REQ_COLUMNS.index("Base on SR\n章节") + 1
                self.assertEqual(rows.cell(2, sec_col).value, "1 Overview")
            finally:
                book.close()

    def test_non_english_languages_are_translated_to_chinese_in_same_cell(self) -> None:
        from electrical_krow.arch_translate import needs_translation, rule_translate_text

        # 纯韩文（含 PDF 拆字空格）、纯日文、纯德文、纯俄文均应判定为需要翻译并译成中文
        kr_spaced = "1) 구 분 : 시 험 시 간 3,000 시간, 인 가 가 능 최 대 전 압 950 V, 오 일 온 도 105 °C"
        jp_clause = "2) 動作電圧範囲：9 ~ 16 V、インバータ最大出力 160 kW、絶縁抵抗 100 MΩ 以上"
        de_clause = "3) Betriebsspannungsbereich: 9 ~ 16 V, Isolationswiderstand mindestens 100 MΩ"
        ru_clause = "4) Рабочее напряжение: 9 ~ 16 V, инвертор температура -40 ~ 105 °C"

        for clause in (kr_spaced, jp_clause, de_clause, ru_clause):
            self.assertTrue(needs_translation(clause), f"Expected needs_translation=True for: {clause}")
            zh = rule_translate_text(clause)
            self.assertTrue(any("\u4e00" <= c <= "\u9fff" for c in zh), f"Expected Chinese in: {zh}")

        self.assertIn("试验时间", rule_translate_text(kr_spaced))
        self.assertIn("可施加最大电压", rule_translate_text(kr_spaced))
        self.assertIn("工作电压范围", rule_translate_text(jp_clause))
        self.assertIn("逆变器", rule_translate_text(jp_clause))
        self.assertIn("工作电压范围", rule_translate_text(de_clause))
        self.assertIn("绝缘电阻", rule_translate_text(de_clause))
        self.assertIn("工作电压", rule_translate_text(ru_clause))

        # 韩文表头表格与英文文档中夹带的韩文技术要求均应保留并附中文译文
        pages = (
            (1, "PE System\nSourcing Request (SR)"),
            (2, _HEADER.format(n=2) + "Revision history\n1 ALL 2026.07.03 initial"),
            (
                3,
                _HEADER.format(n=3)
                + "< Contents >\n1. Overview\n2. System requirements\n2.1 Specification operation plan\n"
                + "2.2 Regulations\n2.3 Component configuration\n3. Parts requirement",
            ),
            (
                4,
                _HEADER.format(n=4)
                + "1. Overview\n"
                + "1) 통합형 PE(모터/감속기/인버터) 승인도 EMC 해석 및 검증 항목\n"
                + "2) Betriebsspannung: 9 ~ 16 V, Prüfbedingung gemäß LV124.",
            ),
        )
        kr_table = {
            4: [
                [
                    ["구분", "요구사항", "단위", "비고"],
                    ["작동 전압 범위", "9 ~ 16", "V", "연속 작동"],
                ]
            ]
        }
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "multilang.xlsx"
            res = write_contrast([SourceDoc("multilang_SR.pdf", pages, tables=kr_table)], [], dest)
            self.assertGreaterEqual(res.reqs, 3)
            book = load_workbook(dest, data_only=True)
            try:
                rows = book[SHEET_REQS]
                excerpt_col = REQ_COLUMNS.index("原文摘录") + 1
                excerpts = [str(rows.cell(r, excerpt_col).value or "") for r in range(2, rows.max_row + 1)]
                kr_table_row = next(e for e in excerpts if "작동 전압 범위" in e)
                self.assertIn(" / ", kr_table_row)
                self.assertIn("工作电压范围", kr_table_row)
                kr_clause_row = next(e for e in excerpts if "통합형 PE" in e)
                self.assertIn(" / ", kr_clause_row)
                self.assertIn("电机/减速器/逆变器", kr_clause_row)
                de_clause_row = next(e for e in excerpts if "Betriebsspannung" in e)
                self.assertIn(" / ", de_clause_row)
                self.assertIn("工作电压", de_clause_row)
            finally:
                book.close()


if __name__ == "__main__":
    unittest.main()
