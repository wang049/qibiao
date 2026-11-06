from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from electrical_krow.arch_contrast import (
    SHEET_NOTE,
    SHEET_REQS,
    SourceDoc,
    Unreadable,
    split_document,
    write_contrast,
)
from electrical_krow.arch_params import collect_params
from electrical_krow.arch_qa import check_arch_quality


class ArchQualityCheckTests(unittest.TestCase):
    def test_unreadable_only_files_are_blocked_with_qa_reason(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw) / "out.xlsx"
            with self.assertRaises(ValueError) as ctx:
                write_contrast(
                    [],
                    [Unreadable("scan.pdf", 8, "全本无文字层，疑似扫描件。")],
                    out,
                )
            self.assertIn("文件内容质检未通过", str(ctx.exception))
            self.assertIn("scan.pdf", str(ctx.exception))

    def test_detects_bilingual_number_and_semantic_conflicts(self) -> None:
        doc = SourceDoc(
            "ldc_bilingual.pdf",
            (
                (
                    1,
                    "1) Maximum Output Power: 1.9 kW / 最大输出功率：2.2 kW\n"
                    "2) Efficiency shall be at least 95% / 额定效率不超过 95%\n"
                    "3) Overvoltage protection shall not lead to an unsafe state / 过压保护可能导致不安全状态",
                ),
            ),
        )
        rows, _ = split_document(doc)
        for idx, row in enumerate(rows, start=1):
            row[0] = idx
        params = collect_params(rows, None)
        report = check_arch_quality([doc], [], rows, params)
        self.assertEqual(report.verdict, "warn")
        self.assertGreaterEqual(report.bilingual_conflicts, 3)
        self.assertIn(1, report.flagged_seqs)
        self.assertIn(2, report.flagged_seqs)
        self.assertIn(3, report.flagged_seqs)
        self.assertIn("中英数值不一致", report.row_notes[1])
        self.assertIn("中英方向相反", report.row_notes[2])
        self.assertIn("中英语义相反", report.row_notes[3])

    def test_detects_power_formula_and_weight_limit_and_tbd(self) -> None:
        doc = SourceDoc(
            "ldc_logic.pdf",
            (
                (
                    1,
                    "1) Output Power: Max. 2.5 kW (@Vo=15.1 V, Io=124 A)\n"
                    "2) Total weight shall not exceed 1.7 kg\n"
                    "3) Mechanical Housing Weight: 2.3 kg\n"
                    "4) Sleep current: <<TBD>>",
                ),
            ),
        )
        rows, _ = split_document(doc)
        for idx, row in enumerate(rows, start=1):
            row[0] = idx
        params = collect_params(rows, None)
        report = check_arch_quality([doc], [], rows, params)
        self.assertGreaterEqual(report.logic_conflicts, 2)
        self.assertEqual(report.tbd_count, 1)
        self.assertIn("功率与电压电流不一致", report.row_notes[1])
        self.assertIn("重量超出同文件限值", report.row_notes[3])
        self.assertIn("TBD/TBC", report.row_notes[4])

    def test_write_contrast_writes_qa_to_note_and_reqs(self) -> None:
        doc = SourceDoc(
            "ldc_qa.pdf",
            (
                (
                    1,
                    "1) Maximum Output Power: 1.9 kW / 最大输出功率：2.2 kW\n"
                    "2) Sleep current: TBD",
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw) / "arch_qa.xlsx"
            seen_stages: list[str] = []

            def on_progress(percent, stage, detail=""):
                seen_stages.append(stage)

            res = write_contrast([doc], [], out, on_progress=on_progress)
            self.assertGreaterEqual(res.bilingual_conflicts, 1)
            self.assertEqual(res.tbd_count, 1)
            self.assertGreaterEqual(res.conflicts, 1)

            wb = load_workbook(out)
            note_ws = wb[SHEET_NOTE]
            note_map = {
                str(r[0] or ""): str(r[1] or "")
                for r in note_ws.iter_rows(min_row=2, values_only=True)
            }
            self.assertIn("文件内容质检", note_map)
            self.assertIn("中英数值不一致", note_map["文件内容质检"])
            self.assertIn("待定项", note_map["文件内容质检"])
            self.assertIn("需求清单第 2 行", note_map["文件内容质检"])
            self.assertIn("需求清单第 3 行", note_map["文件内容质检"])

            req_ws = wb[SHEET_REQS]
            headers = [str(c.value or "") for c in req_ws[1]]
            remark_idx = next(i for i, h in enumerate(headers, start=1) if "备注" in h)
            self.assertIn("中英数值不一致", str(req_ws.cell(2, remark_idx).value or ""))
            self.assertIn("TBD/TBC", str(req_ws.cell(3, remark_idx).value or ""))
            self.assertNotIn("须向客户确认", str(req_ws.cell(3, remark_idx).value or ""))
            self.assertNotIn("须向客户确认", note_map["文件内容质检"])
            self.assertIn("check", seen_stages)
            self.assertIn("save", seen_stages)
            # 冲突行与 TBD 行在「需求清单」均整行标红（FCE4E4）
            self.assertTrue(str(req_ws.cell(2, 1).fill.fgColor.rgb).endswith("FCE4E4"))
            self.assertTrue(str(req_ws.cell(3, 1).fill.fgColor.rgb).endswith("FCE4E4"))
            wb.close()

    def test_detects_cross_table_vo_range_and_shock_g_and_dual_max_output(self) -> None:
        doc = SourceDoc(
            "ldc_spec.pdf",
            (
                (13, "2.4 Operating environment\nEnvironment"),
                (29, "3.2 Hardware requirements\nHardware"),
                (32, "3.3 Control requirements\nControl"),
            ),
            tables={
                13: [[
                    ["Classification", "Unit", "Specifications"],
                    ["Vibration /Mech.shock", "G", "• QC/T895 / Over 40G"],
                ]],
                29: [[
                    ["Classification", "Unit", "Specification"],
                    ["Output / Max. output", "-", "• 2.5kW, Iout=180A (@Vo=13.9V) • Max. output = 15.1V x 180A = 2.72kW"],
                    ["Output / Voltage", "V", "• Nominal: 13.9V • Overall performance range: 7V~15.1V • Operation range: 7~16V"],
                ]],
                32: [[
                    ["Category", "Item", "Requirement", "Remark"],
                    ["Output voltage control", "Output voltage command range", "7V ~ 15.1V", "-"],
                    ["Output voltage control", "Line regulation", "8V < Vo < 24V & No undervoltage", "Slew rate 40V/ms"],
                    ["MECHANCAL", "SHOCK - Sinusoidal half wave", "Width 40G / 20G / 10G Time 11msec", "-"],
                ]],
            },
        )
        rows, _ = split_document(doc)
        for idx, row in enumerate(rows, start=1):
            row[0] = idx
        params = collect_params(rows, None)
        report = check_arch_quality([doc], [], rows, params)
        self.assertGreaterEqual(report.logic_conflicts, 1)
        self.assertGreaterEqual(report.param_conflicts, 1)
        all_notes = "\n".join(report.row_notes.values())
        self.assertIn("同条最大输出功率口径不一", all_notes)
        self.assertIn("输出电压范围前后不一致", all_notes)
        self.assertNotIn("机械冲击加速度前后不一致", all_notes)

    def test_same_mechanical_shock_with_two_g_values_still_conflicts(self) -> None:
        doc = SourceDoc(
            "ldc_shock.pdf",
            ((1, "3. Environment\nEnvironment"),),
            tables={
                1: [[
                    ["Item", "Requirement"],
                    ["Mechanical shock", "50G"],
                    ["Mechanical shock", "40G"],
                ]],
            },
        )
        rows, _ = split_document(doc)
        for idx, row in enumerate(rows, start=1):
            row[0] = idx
        report = check_arch_quality([doc], [], rows, collect_params(rows, None))
        self.assertIn("机械冲击加速度前后不一致", "\n".join(report.row_notes.values()))

    def test_tbd_footnote_inside_a_condition_list_does_not_paint_the_block(self) -> None:
        from electrical_krow.arch_figures import Figure

        transcript = "\n".join([
            "1. P1 Motor NVH TEST condition",
            "① Bench test sweep rate : Run up/down speed 200rpm/s under, engine min rpm~ rated rpm",
            "② Load condition : Every 10Nm step up to 100Nm",
            "*TBD : To be determined after T-car vehicle evaluation",
        ])
        figure = Figure(1, (20, 40, 400, 300), "", b"", "矢量图", transcript, ())
        rows, _tables = split_document(SourceDoc("nvh.pdf", ((1, "1. Overview\n"),), figures={1: [figure]}))
        block = next(row for row in rows if "200rpm/s" in str(row[8]) and "TBD" in str(row[8]))
        block[0] = 1
        report = check_arch_quality([SourceDoc("nvh.pdf", ((1, transcript),))], [], rows, collect_params(rows, None))
        self.assertEqual(report.tbd_count, 1)
        self.assertIn("TBD/TBC", report.row_notes[1])
        self.assertNotIn(1, report.flagged_seqs)


if __name__ == "__main__":
    unittest.main()
