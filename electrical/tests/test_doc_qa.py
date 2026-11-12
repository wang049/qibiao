"""出表前文件质检：先看当份能不能读，交叉检查不得填格。"""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from electrical.doc_kind import DocKind, classify_document
from electrical.doc_qa import inspect_document
from electrical.read_doc import LoadedDocument
from electrical.schema import STATUS_NA, empty_template_rows


DHTS_SNIPPET = """
## 第 10 页
Design Prerequisites for the XCM.
The XCM shall operate with HVDC input 220 Vdc to 460 Vdc.
P1 inverter peak current 180A. P3 inverter 1000A.
Coolant flow 12 LPM. Insulation resistance 10 MΩ.
Active discharge within 2 s. 12V supply range is given in the table.
weight of the XCM shall be less than 20.2kg.
"""

FORBIDDEN_FILL = (
    "8000小时",
    "8000 小时",
    "15年",
    "15 年",
    "13.5 V",
    "13.5V",
    "5.3.10",
    "典型值",
)


def _doc(
    markdown: str,
    *,
    likely_scan: bool = False,
    name: str = "DHTS160_DPR.docx",
    kind: DocKind | None = None,
) -> LoadedDocument:
    path = Path(name)
    return LoadedDocument(
        path=path,
        markdown=markdown,
        page_count=len(re.findall(r"## 第 \d+", markdown)),
        likely_scan=likely_scan,
        parser="DocxReader",
        ocr_pages=2 if likely_scan else 0,
        kind=kind or classify_document(path, markdown),
    )


class FileQaTests(unittest.TestCase):
    def test_empty_file_is_unreadable_and_skips_extract(self) -> None:
        report = inspect_document(_doc("\n\n"))
        self.assertEqual(report.verdict, "fail")
        self.assertTrue(report.skip_extract)
        blob = report.summary + report.file_note + report.kb_note
        for bad in FORBIDDEN_FILL:
            self.assertNotIn(bad, blob)

    def test_dhts_snippet_is_readable(self) -> None:
        report = inspect_document(_doc(DHTS_SNIPPET))
        self.assertFalse(report.skip_extract)
        self.assertEqual(report.verdict, "pass")
        self.assertEqual(report.content_findings, [])
        self.assertIn("直流高压", report.groups_seen)
        self.assertIn("交叉检查不填抽出值", report.kb_note)
        self.assertNotIn("已见主题", report.summary)
        self.assertNotIn("已见主题", report.kb_note)
        self.assertNotIn("正文已出现方法号", report.summary)
        self.assertNotIn("企标试验主题已见", report.kb_note)
        blob = report.summary + report.kb_note
        for bad in FORBIDDEN_FILL:
            self.assertNotIn(bad, blob)

    def test_ocr_garbage_pages_are_warned_with_samples(self) -> None:
        pages = "\n".join(
            f"## 第 {i} 页\nth#Hi#E&E #R #E /à 西里尔\n" for i in range(1, 8)
        )
        report = inspect_document(_doc(pages, likely_scan=True, name="scan.pdf"))
        self.assertIn("花成", report.summary)
        self.assertTrue("th#Hi" in report.summary or "#R" in report.summary or "#E" in report.summary)
        self.assertNotIn("乱码", report.summary)

    def test_markdown_headings_are_not_treated_as_unreadable(self) -> None:
        md = (
            "## 第 3 页\n### Y-电容选择\n"
            "The XCM shall operate with HVDC 400 Vdc. Insulation resistance 10 MΩ.\n"
        ) * 4
        report = inspect_document(_doc(md))
        self.assertFalse(report.skip_extract)
        self.assertNotIn("花成", report.file_note)

    def test_toc_pages_warn_without_filling(self) -> None:
        md = (
            "## 第 1 页\n目录 Contents\n引用标准 规范性引用\n修订记录 revision history\n"
            "标准清单 适用标准 引用文件\n"
        )
        report = inspect_document(_doc(md, name="toc.pdf"))
        self.assertIn(report.verdict, {"warn", "fail"})
        blob = report.summary + report.kb_note
        for bad in FORBIDDEN_FILL:
            self.assertNotIn(bad, blob)

    def test_kb_cross_check_does_not_emit_method_numbers_absent_from_file(self) -> None:
        report = inspect_document(_doc(DHTS_SNIPPET))
        blob = report.summary + report.kb_note + report.file_note
        self.assertNotIn("J7211010", blob)
        self.assertNotIn("J7110218", blob)
        self.assertNotIn("Q/JLP", blob)

    def test_matching_bilingual_numbers_are_not_a_conflict(self) -> None:
        md = DHTS_SNIPPET + """
6.17.3 Sleep current
Sleep current of the XCM shall be 100 µA.
电控休眠电流应为 100 µA。
"""
        report = inspect_document(_doc(md))
        self.assertFalse(report.skip_extract)
        kinds = {f.kind for f in report.content_findings}
        self.assertNotIn("中英冲突", kinds)

    def test_bilingual_and_template_issues_warn_without_filling_or_skipping(self) -> None:
        md = DHTS_SNIPPET + """
<<SYSTEM/COMPONENT>>
Date: 202601202
Date: 202601202
Volvo Car Corporation Subject Matter Expert
吉利主题专家

6.3.3.1 Current sensing
PEI P1: The controller shall measure the HV AC current within the range -600A to +600A.
控制器应能够测量- 180A至+180A峰值范围内消耗产生的P1逆变器高压交流电流。
PEI P3: The controller shall measure within the range -300A to +300A.
控制器应能够测量- 1000A至+1000A峰值范围内消耗产生的P3逆变器高压交流电流。

6.17.3 Sleep current
Sleep current of the XCM shall be 100 µA.
电控休眠电流应为 500 µA。

2.3.1 Weight
The weight of the non-boost XCM shall not exceed 16kg.
非升压电控重量不得超过 18.5kg。

6.2.2 Coolant circuit
The coolant circuit shall withstand ≥200 kPa.
冷却水道耐压应 ≥250 kPa。

5.2.5 Random vibration
Random vibration duration 30h per direction.
随机振动持续时间每向 20h。

6.14.5 Equipotential
The test current shall be at least 1A.
等电位试验电流应小于 1A。

6.4.2.2 Misoperation
The system shall not allow dangerous misoperation leading to unsafe behaviour.
误操作可能导致不安全行为。
"""
        report = inspect_document(_doc(md))
        self.assertFalse(report.skip_extract)
        self.assertEqual(report.verdict, "warn")
        self.assertIn("03_提取质量审查", report.summary)
        self.assertNotIn("不写入抽出值", report.summary)
        p0 = [f for f in report.content_findings if f.level == "P0"]
        p1 = [f for f in report.content_findings if f.level == "P1"]
        self.assertGreaterEqual(len(p0), 4)
        self.assertGreaterEqual(len(p1), 2)
        blob = " ".join(
            [report.summary, report.file_note, report.kb_note]
            + [f.text for f in report.content_findings]
        )
        self.assertIn("±600A", blob)
        self.assertIn("±180A", blob)
        self.assertIn("Volvo", blob)
        self.assertIn("<<SYSTEM/COMPONENT>>", blob)
        self.assertIn("202601202", blob)
        for bad in FORBIDDEN_FILL:
            self.assertNotIn(bad, blob)
        self.assertNotIn("J7110218", blob)
        amps = [f for f in report.content_findings if "±180A" in f.text]
        self.assertTrue(amps)
        self.assertEqual(amps[0].clause, "6.3.3.1")
        self.assertEqual(amps[0].page, "10")
        dates = [f for f in report.content_findings if "202601202" in f.text]
        self.assertEqual(len(dates), 1)
        self.assertEqual(dates[0].text.count("202601202"), 1)

    def test_conflict_uses_the_page_of_that_clause(self) -> None:
        from electrical.doc_content_qa import review_document_content

        md = """
## 第 32 页
5.2.5 Random vibration
The English profile holds each axis for 30h and then describes the mounting, the spectrum and the dwell in English only.

随机振动这一条按中文要求，把每个方向的持续时间、安装方式和谱型都写在本句里，数值是 20h。

## 第 44 页
6.2.3.2 Power
The English statement lists both 62.5kW and 125kW and then keeps the operating point in English for this whole line.

中文功率这一条只保留一个数，工况和说明都继续用中文来写，数值是 62.5kW。
"""
        findings = review_document_content(md)
        hours = [f for f in findings if "20h" in f.text]
        power = [f for f in findings if "125kW" in f.text]
        self.assertEqual(len(hours), 1)
        self.assertEqual(hours[0].page, "32")
        self.assertEqual(hours[0].clause, "5.2.5")
        self.assertIn("两边对不上", hours[0].text)
        self.assertEqual(len(power), 1)
        self.assertEqual(power[0].page, "44")
        self.assertEqual(power[0].clause, "6.2.3.2")

    def test_internal_logic_flags_weight_can_and_power_map(self) -> None:
        md = DHTS_SNIPPET + """
The weight of the XCM shall be less than 20.2kg.
Mass table lists 21.5kg.

MCU summary: at least 8 CAN channels.
6.2.4.3 Communication shall provide ≥10 CAN.

6.8 Buck converter Max 85kW @ 200V-400V.
Operating map 250V 325A.

Appendix: Hardware only.
BOM includes OD software white-box 白盒交付.
"""
        report = inspect_document(_doc(md))
        self.assertFalse(report.skip_extract)
        self.assertEqual(report.verdict, "warn")
        texts = " ".join(f.text for f in report.content_findings)
        self.assertIn("21.5kg", texts)
        self.assertIn("CAN", texts)
        self.assertIn("81.25kW", texts)
        self.assertIn("Hardware only", texts)
        blob = report.summary + texts
        for bad in FORBIDDEN_FILL:
            self.assertNotIn(bad, blob)

    def test_empty_table_is_flagged(self) -> None:
        md = DHTS_SNIPPET + """
| Sample | Qty |
| --- | --- |
|  |  |
|  |  |
"""
        report = inspect_document(_doc(md))
        kinds = {f.kind for f in report.content_findings}
        self.assertIn("空表", kinds)
        self.assertFalse(report.skip_extract)


class PipelineQaTests(unittest.TestCase):
    def test_unreadable_skips_extract_and_writes_empty_table(self) -> None:
        from electrical.pipeline import run

        kind = DocKind("xcm_dpr", "电控 DPR", True, "dpr", "按电控 DPR 抽取。")
        doc = _doc("", kind=kind)
        with tempfile.TemporaryDirectory() as tmp:
            incoming = Path(tmp) / "blank.docx"
            incoming.write_bytes(b"x")
            out = Path(tmp) / "out.xlsx"
            with (
                patch("electrical.pipeline.load_document", return_value=doc),
                patch("electrical.pipeline.extract_cells") as extract,
            ):
                result = run(incoming, out)
            extract.assert_not_called()
            self.assertFalse(result.extract)
            self.assertEqual(result.qa_verdict, "fail")
            self.assertTrue(out.is_file())
            self.assertTrue(all(not (cell.value or "").strip() for cell in result.cells))
            self.assertTrue(
                all((cell.review_status or "") == STATUS_NA for cell in result.cells)
            )
            blob = " ".join(
                (cell.value or "") + (cell.note or "") for cell in result.cells
            )
            for bad in FORBIDDEN_FILL:
                self.assertNotIn(bad, blob)

    def test_readable_still_extracts(self) -> None:
        from electrical.pipeline import run

        doc = _doc(DHTS_SNIPPET)
        rows = empty_template_rows()
        with tempfile.TemporaryDirectory() as tmp:
            incoming = Path(tmp) / "dhts.docx"
            incoming.write_bytes(b"x")
            out = Path(tmp) / "out.xlsx"
            with (
                patch("electrical.pipeline.load_document", return_value=doc),
                patch("electrical.pipeline.extract_cells", return_value=rows) as extract,
            ):
                result = run(incoming, out)
            extract.assert_called_once()
            self.assertTrue(result.extract)
            self.assertIn(result.qa_verdict, {"pass", "warn"})
            self.assertTrue(all(not (cell.value or "").strip() for cell in result.cells))

    def test_chunk_failures_reach_result_and_workbook_cover(self) -> None:
        from electrical.pipeline import run

        doc = _doc(DHTS_SNIPPET)
        rows = empty_template_rows()

        def fake_extract(*args, **kwargs):
            kwargs["meta"].chunk_failures = 2
            return rows

        with tempfile.TemporaryDirectory() as tmp:
            incoming = Path(tmp) / "dhts.docx"
            incoming.write_bytes(b"x")
            out = Path(tmp) / "out.xlsx"
            with (
                patch("electrical.pipeline.load_document", return_value=doc),
                patch("electrical.pipeline.extract_cells", side_effect=fake_extract),
            ):
                result = run(incoming, out)
            self.assertEqual(result.chunk_failures, 2)

            from openpyxl import load_workbook

            wb = load_workbook(out, data_only=True)
            cover = {
                str(row[0] or ""): str(row[1] or "")
                for row in wb["01_封面"].iter_rows(max_col=2, values_only=True)
            }
            self.assertIn("2 个分段识别失败", cover.get("识别完整性", ""))

    def test_chunk_error_reaches_workbook_cover(self) -> None:
        from electrical.pipeline import run

        doc = _doc(DHTS_SNIPPET)
        rows = empty_template_rows()

        def fake_extract(*args, **kwargs):
            kwargs["meta"].chunk_failures = 27
            kwargs["meta"].chunk_error = "响应格式异常: reasoning only"
            return rows

        with tempfile.TemporaryDirectory() as tmp:
            incoming = Path(tmp) / "dhts.docx"
            incoming.write_bytes(b"x")
            out = Path(tmp) / "out.xlsx"
            with (
                patch("electrical.pipeline.load_document", return_value=doc),
                patch("electrical.pipeline.extract_cells", side_effect=fake_extract),
            ):
                result = run(incoming, out)
            self.assertEqual(result.chunk_failures, 27)
            self.assertIn("reasoning only", result.chunk_error)

            from openpyxl import load_workbook

            wb = load_workbook(out, data_only=True)
            cover = {
                str(row[0] or ""): str(row[1] or "")
                for row in wb["01_封面"].iter_rows(max_col=2, values_only=True)
            }
            self.assertIn("27 个分段识别失败", cover.get("识别完整性", ""))
            self.assertIn("reasoning only", cover.get("识别完整性", ""))

    def test_content_conflicts_still_extract_and_do_not_fill(self) -> None:
        from electrical.pipeline import run

        md = DHTS_SNIPPET + """
6.3.3.1 Current sensing
PEI P1: The controller shall measure the HV AC current within the range -600A to +600A.
控制器应能够测量- 180A至+180A峰值范围内消耗产生的P1逆变器高压交流电流。
Volvo Car Corporation
"""
        doc = _doc(md)
        rows = empty_template_rows()
        with tempfile.TemporaryDirectory() as tmp:
            incoming = Path(tmp) / "dhts.docx"
            incoming.write_bytes(b"x")
            out = Path(tmp) / "out.xlsx"
            with (
                patch("electrical.pipeline.load_document", return_value=doc),
                patch("electrical.pipeline.extract_cells", return_value=rows) as extract,
            ):
                result = run(incoming, out)
            extract.assert_called_once()
            self.assertTrue(result.extract)
            self.assertEqual(result.qa_verdict, "warn")
            self.assertIn("03_提取质量审查", result.qa_summary)
            self.assertTrue(all(not (cell.value or "").strip() for cell in result.cells))
            blob = " ".join(
                (cell.value or "") + (cell.note or "") for cell in result.cells
            )
            self.assertNotIn("±600A", blob)
            for bad in FORBIDDEN_FILL:
                self.assertNotIn(bad, blob)
                self.assertNotIn(bad, result.qa_summary or "")


class ModelOnlyAblationTests(unittest.TestCase):
    """SPEC_SHEET_MODEL_ONLY=1 只走词典认条 → 分段模型，用来量新文档也会走的那条路。"""

    def _run(self, env: dict[str, str]) -> tuple[int, int]:
        from unittest.mock import patch as _patch

        import electrical.extract as ex

        calls = {"rules": 0, "chunks": 0}

        def fake_rules(text: str, family: str = "generic"):
            calls["rules"] += 1
            return []

        def fake_chunks(markdown: str, max_chunks=None, rows=None):
            calls["chunks"] += 1
            return []

        with (
            _patch.dict("os.environ", env, clear=False),
            _patch.object(ex, "_rule_cells", side_effect=fake_rules),
            _patch.object(ex, "_select_chunks", side_effect=fake_chunks),
            _patch.object(ex, "_topup_chunks", return_value=[]),
        ):
            ex.extract_cells(_doc(DHTS_SNIPPET), meta=ex.ExtractMeta())
        return calls["rules"], calls["chunks"]

    def test_default_runs_rules_then_model(self) -> None:
        rules, chunks = self._run({"SPEC_SHEET_MODEL_ONLY": "", "SPEC_SHEET_RULES_ONLY": ""})
        self.assertGreater(rules, 0)
        self.assertEqual(chunks, 1)

    def test_model_only_skips_rules_and_still_selects_chunks(self) -> None:
        rules, chunks = self._run({"SPEC_SHEET_MODEL_ONLY": "1", "SPEC_SHEET_RULES_ONLY": ""})
        self.assertEqual(rules, 0)
        self.assertEqual(chunks, 1)

    def test_model_only_wins_over_rules_only(self) -> None:
        rules, chunks = self._run({"SPEC_SHEET_MODEL_ONLY": "1", "SPEC_SHEET_RULES_ONLY": "1"})
        self.assertEqual(rules, 0)
        self.assertEqual(chunks, 1)


class SplitRetryTests(unittest.TestCase):
    """整段识别失败（超时/JSON 坏）→ 拆半重试一次，不把原文白白丢掉。"""

    LONG_PAGE = (
        "## 第 12 页\n"
        + "Vibration requirement per J030600. The XCM shall withstand random vibration.\n" * 20
        + "\n## 第 13 页\n"
        + "Storage temperature -40 to 105 ℃. Operating altitude 5000 m above sea level.\n" * 20
    )

    def _run(self, fail_when):
        from unittest.mock import patch as _patch

        import electrical.extract as ex

        seen: list[int] = []

        def fake_parse(complete, prompt, timeout, *, fallback_prompt="", fallback_timeout=40.0):
            seen.append(len(prompt))
            if fail_when(prompt):
                return {"rows": [], "_parse_failed": True}
            return {"rows": []}

        def fake_rules(text: str, family: str = "generic"):
            return []

        meta = ex.ExtractMeta()
        with (
            _patch.dict("os.environ", {"SPEC_SHEET_MODEL_ONLY": "1"}, clear=False),
            _patch.object(ex, "_rule_cells", side_effect=fake_rules),
            _patch.object(ex, "_select_chunks", return_value=[self.LONG_PAGE]),
            _patch.object(ex, "_topup_chunks", return_value=[]),
            _patch.object(ex, "_parse_model_json", side_effect=fake_parse),
        ):
            ex.extract_cells(_doc(self.LONG_PAGE), meta=meta)
        return meta, seen

    def test_failed_chunk_is_split_and_retried(self) -> None:
        full = len(self.LONG_PAGE)
        meta, seen = self._run(lambda prompt: len(prompt) > full)
        self.assertEqual(len(seen), 3, seen)
        self.assertEqual(meta.llm_calls, 3)
        self.assertEqual(meta.chunk_failures, 0)

    def test_halves_failing_too_count_as_failures_once_each(self) -> None:
        meta, seen = self._run(lambda prompt: True)
        self.assertEqual(len(seen), 3, seen)
        self.assertEqual(meta.chunk_failures, 2)

    def test_split_halves_cut_at_page_marker(self) -> None:
        import electrical.extract as ex

        halves = ex._split_chunk_halves(self.LONG_PAGE)
        self.assertEqual(len(halves), 2)
        self.assertTrue(halves[0].startswith("## 第 12 页"))
        self.assertTrue(halves[1].startswith("## 第 13 页"))
        self.assertEqual(ex._split_chunk_halves("short"), ["short"])


if __name__ == "__main__":
    unittest.main()
