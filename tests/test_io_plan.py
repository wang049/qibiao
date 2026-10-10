from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from electrical_krow.io_plan import (
    HEADERS,
    JOB_STEPS,
    SHEET_TABLE,
    ManualPin,
    write_io_sheet,
)


def _rows(path: Path) -> list[tuple]:
    workbook = load_workbook(path, data_only=True)
    try:
        sheet = workbook[SHEET_TABLE]
        return [tuple(row) for row in sheet.iter_rows(values_only=True)]
    finally:
        workbook.close()


class IoPlanTests(unittest.TestCase):
    def test_blank_sheet_has_steps_and_no_pins(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "io.xlsx"
            write_io_sheet(path)
            workbook = load_workbook(path, data_only=True)
            try:
                note = [cell.value for cell in workbook["说明"]["B"]]
            finally:
                workbook.close()
            self.assertEqual(note[1:5], list(JOB_STEPS))
            self.assertIn("端口名留空", "".join(str(item) for item in note if item))
            rows = _rows(path)
            self.assertEqual(rows, [HEADERS])

    def test_manual_row_keeps_excerpt_and_drops_port_name(self) -> None:
        pin = ManualPin(
            pin="P14.2",
            function="CAN0_TX",
            page="120",
            excerpt="P14.2 CAN0_TX",
            mux="CAN",
            constraint="5 V",
            port_name="不应写入",
        )
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "io.xlsx"
            write_io_sheet(path, [pin])
            header, data = _rows(path)
            self.assertEqual(header, HEADERS)
            self.assertEqual(
                data,
                ("P14.2", "CAN0_TX", "CAN", "5 V", "120", "P14.2 CAN0_TX", None, None),
            )

    def test_confirmed_rule_may_carry_given_port_name(self) -> None:
        pin = ManualPin(
            pin="P14.2",
            function="CAN0_TX",
            page="120",
            excerpt="P14.2 CAN0_TX",
            port_name="IO_CAN0_TX",
        )
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "io.xlsx"
            write_io_sheet(path, [pin], naming_confirmed=True)
            self.assertEqual(_rows(path)[1][6], "IO_CAN0_TX")

    def test_human_column_is_kept(self) -> None:
        pin = ManualPin(
            pin="P14.2",
            function="CAN0_TX",
            page="120",
            excerpt="P14.2 CAN0_TX",
            mux="CAN",
        )
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "io.xlsx"
            write_io_sheet(path, [pin])
            workbook = load_workbook(path)
            workbook[SHEET_TABLE]["H2"] = "工程师改为 CAN_TX"
            workbook.save(path)
            workbook.close()
            write_io_sheet(
                path,
                [ManualPin(
                    pin="P14.2",
                    function="CAN0_TX",
                    page="120",
                    excerpt="P14.2 CAN0_TX",
                    mux="被规则改写",
                )],
            )
            data = _rows(path)[1]
            self.assertEqual(data[2], "被规则改写")
            self.assertEqual(data[7], "工程师改为 CAN_TX")

    def test_row_without_excerpt_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "io.xlsx"
            with self.assertRaises(ValueError):
                write_io_sheet(
                    path,
                    [ManualPin(pin="1", function="TX", page="1", excerpt="")],
                )
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
