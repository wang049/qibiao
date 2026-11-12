"""核对表版式：分组、页码清洗、重出不丢抽出值。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from electrical.extract import _normalize_page
from electrical.schema import ExtractedCell, item_group, load_template_fields, review_item_no
from electrical.write_excel import load_review_cells, write_review_workbook


class GroupTests(unittest.TestCase):
    def test_all_template_items_grouped(self) -> None:
        unknown = [
            f"{spec.seq} {spec.name}"
            for spec in load_template_fields()
            if item_group(spec.name, spec.seq) == "其他"
        ]
        self.assertEqual(unknown, [])

    def test_p1_p3_split(self) -> None:
        self.assertEqual(item_group("P1峰值功率", 28), "P1")
        self.assertEqual(item_group("P3峰值功率", 45), "P3")


class PageNormalizeTests(unittest.TestCase):
    def test_section_uses_markdown_page(self) -> None:
        chunk = "## 第 90 页\nThe XCM shall have functionality"
        self.assertEqual(_normalize_page("节84", chunk), "90")
        self.assertEqual(_normalize_page("6.5.11.1", chunk), "90")
        self.assertEqual(_normalize_page("第 23 页", chunk), "23")
        self.assertEqual(_normalize_page("95", chunk), "95")


class WorkbookTests(unittest.TestCase):
    def test_rewrite_keeps_values_and_adds_review_columns(self) -> None:
        rows = [
            ExtractedCell(
                seq=1,
                name="设计范围是否包含OD本体物理集成",
                value="是（重量目标含OD模块）",
                page="17",
                clause="2.3.3.3",
                excerpt="weight of the XCM shall be less than 20.2kg",
                confidence=0.82,
                example="是",
            ),
            ExtractedCell(
                seq=2,
                name="设计范围是否包含OD上移功能",
                example="是",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "核对表.xlsx"
            write_review_workbook(
                rows,
                path,
                source_name="DHTS160_DPR.docx",
                likely_scan=False,
                parser="DocxReader",
                kind_label="电控 DPR",
                extract=True,
            )
            from openpyxl import load_workbook

            wb = load_workbook(path)
            self.assertEqual(wb.sheetnames, ["说明", "电控设计需求", "清单外需求", "清单口径"])
            ws = wb["电控设计需求"]
            headers = [c.value for c in ws[2]]
            self.assertIn("人工填写", headers)
            self.assertIn("条款号", headers)
            self.assertIn("分组", headers)
            self.assertNotIn("参考示例（非本份抽出）", headers)
            self.assertEqual(ws["A3"].value, "已检索到")
            self.assertEqual(ws["A4"].value, "未检索到")
            self.assertEqual(ws["B3"].value, "设计范围")
            self.assertEqual(ws["G3"].value, "2.3.3.3")
            self.assertEqual(ws["E3"].fill.fgColor.rgb[-6:].upper(), "D6EAF8")
            self.assertEqual(ws["E4"].fill.fgColor.rgb[-6:].upper(), "FFF3CD")
            self.assertEqual(ws["E4"].value, "未检索到")
            loaded, meta = load_review_cells(path)
            self.assertEqual(meta["源文件"], "DHTS160_DPR.docx")
            self.assertIn("知识库版本", meta)
            self.assertNotIn("知识库口径", meta)
            self.assertEqual(loaded[0].value, "是（重量目标含OD模块）")
            self.assertEqual(loaded[0].clause, "2.3.3.3")
            self.assertEqual(loaded[1].value, "")
            self.assertEqual(loaded[0].review_status, "已检索到")
            self.assertEqual(loaded[1].review_status, "未检索到")
            cover_text = "\n".join(
                " ".join("" if c.value is None else str(c.value) for c in row)
                for row in wb["说明"].iter_rows()
            )
            self.assertIn("已检索到", cover_text)
            self.assertIn("知识库版本", cover_text)
            self.assertIn("用法", cover_text)
            for hidden in (
                "解析器",
                "疑似扫描件",
                "识别模型",
                "覆盖预期",
                "检索结果标准",
                "分流说明",
                "deepseek",
                "标准答案",
                "Word / WPS",
                "建议人工过目",
                "clause_lexicon",
                ".yaml",
                "published/",
                "知识库口径",
                "不提供取值",
                "知识库交叉",
                "知识库闭环",
                "页码列",
                "质检口径",
                "不写入抽出值",
                "文件质检",
                "质检说明",
                "内容审查",
                "未给出（方法见备注）",
                "未检索到（方法见备注）",
            ):
                self.assertNotIn(hidden, cover_text)

    def test_review_item_no_is_1_to_116(self) -> None:
        fields = load_template_fields()
        self.assertEqual(len(fields), 116)
        self.assertEqual(review_item_no(1), 1)
        self.assertEqual(review_item_no(17), 17)
        self.assertEqual(review_item_no(20), 18)
        self.assertEqual(review_item_no(28), 24)
        self.assertEqual(review_item_no(72), 68)
        self.assertEqual(review_item_no(120), 116)
        self.assertEqual(
            [review_item_no(spec.seq) for spec in fields],
            list(range(1, 117)),
        )

    def test_workbook_writes_contiguous_review_numbers(self) -> None:
        fields = load_template_fields()
        left, right = fields[16], fields[17]
        self.assertEqual(left.seq, 17)
        self.assertEqual(right.seq, 20)
        rows = [
            ExtractedCell(seq=left.seq, name=left.name, value="Y+", confidence=0.9),
            ExtractedCell(seq=right.seq, name=right.name, value="6~16V", confidence=0.9),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "核对表.xlsx"
            write_review_workbook(
                rows,
                path,
                source_name="demo.docx",
                likely_scan=False,
                parser="DocxReader",
            )
            from openpyxl import load_workbook

            wb = load_workbook(path)
            ws = wb["电控设计需求"]
            self.assertEqual(ws["C3"].value, 17)
            self.assertEqual(ws["C4"].value, 18)
            self.assertEqual(wb["清单口径"]["A3"].value, 17)
            self.assertEqual(wb["清单口径"]["A4"].value, 18)
            loaded, _ = load_review_cells(path)
            self.assertEqual(loaded[0].seq, 17)
            self.assertEqual(loaded[1].seq, 20)

    def test_std_ref_miss_displays_unretrieved(self) -> None:
        rows = [
            ExtractedCell(
                seq=72,
                name="最大散热能力",
                note="企标方法对照：当份 DPR 未给出该指标；Q/JLP 030602-07-2026A 7.3 → Q/JLP 030600-11。",
                review_status="未检索到",
            )
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "核对表.xlsx"
            write_review_workbook(
                rows,
                path,
                source_name="DHTS160_DPR.docx",
                likely_scan=False,
                parser="DocxReader",
                kind_label="电控 DPR",
                extract=True,
            )
            from openpyxl import load_workbook

            wb = load_workbook(path)
            ws = wb["电控设计需求"]
            self.assertEqual(ws["A3"].value, "未检索到")
            self.assertEqual(ws["E3"].value, "未检索到")
            self.assertEqual(ws["E3"].fill.fgColor.rgb[-6:].upper(), "FFF3CD")
            self.assertNotIn("参考", ws["E3"].value or "")
            self.assertIn("企标方法对照", ws["J3"].value or "")
            self.assertEqual(ws["C3"].value, 68)
            cover_text = "\n".join(
                " ".join("" if c.value is None else str(c.value) for c in row)
                for row in wb["说明"].iter_rows()
            )
            self.assertNotIn("未给出（方法见备注）", cover_text)
            self.assertNotIn("未检索到（方法见备注）", cover_text)
            self.assertNotIn("抽出值写参考标准", cover_text)
            self.assertNotIn("不提供取值", cover_text)
            self.assertNotIn("知识库闭环", cover_text)
            loaded, _ = load_review_cells(path)
            self.assertEqual(loaded[0].seq, 72)

    def test_review_note_written(self) -> None:
        rows = [
            ExtractedCell(
                seq=31,
                name="P1峰值扭矩/时间/对应转速范围",
                note="冷启动曲线有 80Nm@3000rpm，不是峰值包络。",
            )
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "核对表.xlsx"
            write_review_workbook(
                rows,
                path,
                source_name="demo.docx",
                likely_scan=False,
                parser="DocxReader",
            )
            loaded, _ = load_review_cells(path)
            self.assertEqual(loaded[0].note, "冷启动曲线有 80Nm@3000rpm，不是峰值包络。")
            self.assertEqual(loaded[0].value, "")
            self.assertEqual(loaded[0].review_status, "局部对应/需人工复核")
            from openpyxl import load_workbook

            wb2 = load_workbook(path)
            self.assertEqual(wb2["电控设计需求"]["A3"].value, "局部对应/需人工复核")
            self.assertEqual(wb2["电控设计需求"]["E3"].value, "局部对应/需人工复核")

    def test_formula_note_written_to_review_column(self) -> None:
        rows = [
            ExtractedCell(
                seq=13,
                name="高压安全-绝缘电阻",
                value="10 MΩ",
                page="78",
                clause="2.3.3.3",
                excerpt="Insulation test voltage 1000 VDC, leakage current 0.1 mA.",
                confidence=0.72,
                note="由物理公式计算：R=U/I（代入 1000 VDC、0.1 mA）",
                review_status="局部对应/需人工复核",
            )
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "核对表.xlsx"
            write_review_workbook(
                rows,
                path,
                source_name="demo.docx",
                likely_scan=False,
                parser="DocxReader",
            )
            loaded, _ = load_review_cells(path)
            self.assertEqual(loaded[0].value, "10 MΩ")
            self.assertIn("R=U/I", loaded[0].note)
            self.assertIn("代入", loaded[0].note)
            self.assertEqual(loaded[0].review_status, "局部对应/需人工复核")
            from openpyxl import load_workbook

            wb = load_workbook(path)
            ws = wb["电控设计需求"]
            headers = [c.value for c in ws[2]]
            note_col = headers.index("复核备注") + 1
            self.assertEqual(
                ws.cell(3, note_col).value,
                "由物理公式计算：R=U/I（代入 1000 VDC、0.1 mA）",
            )
            self.assertEqual(ws["E3"].value, "10 MΩ")
            self.assertIsNotNone(ws["E3"].comment)
            self.assertIn("R=U/I", ws["E3"].comment.text)

    def test_long_excerpt_gets_tall_row(self) -> None:
        long = "主动短路期间，P1电磁最大允许稳态电流为250Arms有效值。" * 8
        rows = [
            ExtractedCell(
                seq=42,
                name="P1逆变器交流主动短路电流",
                value=long,
                excerpt=long,
                confidence=0.85,
            )
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "核对表.xlsx"
            write_review_workbook(
                rows,
                path,
                source_name="demo.docx",
                likely_scan=False,
                parser="DocxReader",
            )
            from openpyxl import load_workbook

            wb = load_workbook(path)
            height = wb["电控设计需求"].row_dimensions[3].height
            self.assertGreaterEqual(height, 80)

    def test_cover_records_knowledge_version(self) -> None:
        rows = [
            ExtractedCell(
                seq=1,
                name="设计范围是否包含OD本体物理集成",
                value="是",
                confidence=0.9,
            )
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "核对表.xlsx"
            write_review_workbook(
                rows,
                path,
                source_name="demo.docx",
                likely_scan=False,
                parser="DocxReader",
                knowledge_version="2026-09-03.4",
            )
            _, meta = load_review_cells(path)
            self.assertEqual(meta["知识库版本"], "2026-09-03.4")
            self.assertNotIn("知识库口径", meta)

    def test_cover_records_file_qa_without_fill_values(self) -> None:
        from electrical.doc_qa import DocQaReport

        rows = [
            ExtractedCell(
                seq=1,
                name="设计范围是否包含OD本体物理集成",
                value="是",
                confidence=0.9,
            )
        ]
        qa = DocQaReport(
            verdict="warn",
            skip_extract=False,
            summary="需注意。部分页扫描识别花成「th#Hi#E&E」这类字。交叉检查不填抽出值。",
            file_note="部分页扫描识别花成「th#Hi#E&E」这类字。",
            kb_note="交叉检查不填抽出值。",
            progress_message="文件质检：需注意。",
            groups_seen=("直流高压", "冷却"),
            groups_missing=("低压",),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "核对表.xlsx"
            write_review_workbook(
                rows,
                path,
                source_name="demo.docx",
                likely_scan=True,
                parser="DocxReader",
                qa=qa,
            )
            _, meta = load_review_cells(path)
            self.assertNotIn("文件质检", meta)
            self.assertNotIn("质检说明", meta)
            self.assertNotIn("内容审查", meta)
            self.assertNotIn("知识库交叉", meta)
            blob = " ".join(meta.values())
            self.assertNotIn("8000", blob)
            self.assertNotIn("13.5", blob)
            self.assertNotIn(".yaml", blob)
            self.assertNotIn("th#Hi#E&E", blob)
            self.assertNotIn("不写入抽出值", blob)

    def test_cover_writes_content_review_sheet_without_fill_values(self) -> None:
        from electrical.doc_content_qa import ContentFinding
        from electrical.doc_qa import DocQaReport

        rows = [
            ExtractedCell(
                seq=1,
                name="设计范围是否包含OD本体物理集成",
                value="是",
                confidence=0.9,
            )
        ]
        qa = DocQaReport(
            verdict="warn",
            skip_extract=False,
            summary="需注意。中英冲突 1 条。详见核对表「文件审查」页。不写入抽出值。",
            file_note="中英冲突 1 条。详见核对表「文件审查」页。不写入抽出值。",
            kb_note="交叉检查不填抽出值。",
            progress_message="文件质检：需注意。",
            content_findings=[
                ContentFinding(
                    "P0",
                    "中英冲突",
                    "P1 交流电流量程中英不一致：中文 ±180A，英文 ±600A。",
                )
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "核对表.xlsx"
            write_review_workbook(
                rows,
                path,
                source_name="demo.docx",
                likely_scan=False,
                parser="DocxReader",
                qa=qa,
            )
            from openpyxl import load_workbook

            wb = load_workbook(path)
            self.assertIn("文件审查", wb.sheetnames)
            self.assertEqual(
                wb.sheetnames[:2],
                ["说明", "文件审查"],
            )
            review_text = "\n".join(
                " ".join("" if c.value is None else str(c.value) for c in row)
                for row in wb["文件审查"].iter_rows()
            )
            self.assertIn("P0", review_text)
            self.assertIn("±180A", review_text)
            self.assertNotIn("不写入抽出值", review_text)
            self.assertNotIn("8000", review_text)
            _, meta = load_review_cells(path)
            self.assertNotIn("内容审查", meta)
            self.assertNotIn("文件质检", meta)
            self.assertNotIn("质检说明", meta)
            self.assertNotIn("知识库交叉", meta)
            blob = " ".join(meta.values())
            self.assertNotIn("不写入抽出值", blob)
            self.assertNotIn("8000", blob)
            self.assertNotIn("±180A", blob)

    def test_off_list_sheet_keeps_template_coverage(self) -> None:
        rows = [
            ExtractedCell(
                seq=1,
                name="设计范围是否包含OD本体物理集成",
                value="是（重量目标含OD模块）",
                page="17",
                excerpt="weight of the XCM shall be less than 20.2kg",
                confidence=0.9,
            ),
            ExtractedCell(seq=2, name="设计范围是否包含OD上移功能"),
            ExtractedCell(
                extra=True,
                name="规格书标题",
                value="DHTS160 DPR",
                page="1",
                excerpt="DHTS160 DPR",
                confidence=0.9,
            ),
            ExtractedCell(
                extra=True,
                name="生产追溯码",
                value="生产追溯码应打印在壳体右侧。",
                page="88",
                clause="9.2.1",
                excerpt="生产追溯码应打印在壳体右侧。",
                confidence=0.78,
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "核对表.xlsx"
            write_review_workbook(
                rows,
                path,
                source_name="DHTS160_DPR.docx",
                likely_scan=False,
                parser="DocxReader",
                kind_label="电控 DPR",
                extract=True,
            )
            from openpyxl import load_workbook

            wb = load_workbook(path)
            self.assertIn("清单外需求", wb.sheetnames)
            main = wb["电控设计需求"]
            names = [row[3].value for row in main.iter_rows(min_row=3, max_col=4)]
            self.assertIn("设计范围是否包含OD本体物理集成", names)
            self.assertNotIn("生产追溯码", names)
            self.assertNotIn("规格书标题", names)
            extra = wb["清单外需求"]
            self.assertEqual([c.value for c in extra[2]], ["名称", "抽出值", "页码", "条款号", "原文摘录"])
            self.assertEqual(extra["A3"].value, "生产追溯码")
            self.assertEqual(extra["B3"].value, "生产追溯码应打印在壳体右侧。")
            self.assertEqual(extra["C3"].value, "88")
            self.assertEqual(extra["D3"].value, "9.2.1")
            extra_names = [row[0].value for row in extra.iter_rows(min_row=3, max_col=1)]
            self.assertNotIn("规格书标题", extra_names)
            cover = "\n".join(
                " ".join("" if c.value is None else str(c.value) for c in row)
                for row in wb["说明"].iter_rows()
            )
            self.assertIn("清单条目", cover)
            self.assertIn("清单外需求", cover)
            self.assertRegex(cover, r"已检索到\s+1")
            self.assertRegex(cover, r"未检索到\s+1")
            self.assertRegex(cover, r"清单外需求\s+1")


if __name__ == "__main__":
    unittest.main()
