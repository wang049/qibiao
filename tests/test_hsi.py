from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook, load_workbook

from electrical_krow.hsi_book import (
    COL_HUMAN,
    COL_MARK,
    COL_STATUS,
    SHEET_ACCEPT,
    SHEET_CONSTRAINT,
    SHEET_EVIDENCE,
    SHEET_HISTORY,
    SHEET_PORT,
    SHEET_REVISION,
    STATUS_CONFLICT,
    STATUS_DRAFT,
    STATUS_GAP,
    STATUS_MULTI,
    write_hsi_workbook,
)
from electrical_krow.mcu_pins import ChipPin, mcu_name, packages_in_titles, parse_pin_pages, parse_pins

_PAGE = """
Pin Definition and Functions BGA516 Package Variant Pin Configuration
Table 2-1 Port 00 Functions
Ball Symbol Ctrl. Buffer
Type
Function
M6 P00.0 I FAST /
PU1 /
VEXT /
ES
General-purpose input
GTM_TIM5_IN4_10 Mux input channel 4 of TIM module 5
P00.0 O0 General-purpose output
GTM_TOUT9 O1 GTM muxed output
— O4 Reserved
K5 P00.1 I SLOW /
PU1 /
VDDEXT /
ES
General-purpose input
CAN10_RXDA CAN receive input node 0
P00.1 O0 General-purpose output
"""

_OTHER = """
Pin Definition and Functions BGA292 Package Variant Pin Configuration
Table 2-20 Port 00 Functions
A2 P00.0 I SLOW /
PU1 /
VEXT /
ES
General-purpose input
P00.0 O0 General-purpose output
"""


def _template(path: Path, *, history: str = "模板里的旧变更") -> None:
    book = Workbook()
    cover = book.active
    cover.title = "0_Cover"
    cover["B2"] = "Date"
    cover["C2"] = "Change List"
    cover["D2"] = "Version"
    cover["E2"] = "Remarks"
    history_sheet = book.create_sheet(SHEET_HISTORY)
    history_sheet.append(["编号", "变更日期", "详细描述", "影响分析", "备注"])
    history_sheet.append([1, "20250901", history, "暂无影响", "适用于A样"])
    port = book.create_sheet(SHEET_PORT)
    port["A2"] = "TC499 Port Assignment [Main Table]"
    port["B3"] = "MCU_TC499"
    port["A4"] = "NO."
    port["B4"] = r"BGA436\Ball"
    port["C4"] = "Pin_Symbol"
    port["J4"] = "Pin Definition(Himalaya)"
    port["L4"] = "Level"
    port["M4"] = "ASIL"
    port["A5"] = 1
    port["B5"] = "AN0"
    port["C5"] = "W13"
    port["J5"] = "IA_S/M_P3"
    port["A6"] = 2
    port["B6"] = "P00.0"
    port["C6"] = "OLD"
    port["J6"] = "KEEP_ME"
    port["L6"] = "L1"
    port["M6"] = "QM"
    other = book.create_sheet("5_CAN")
    other["A1"] = "模板CAN"
    book.save(path)
    book.close()


def _pin(symbol: str, ball: str, function: str, mux: str = "", direction: str = "Input/Output") -> ChipPin:
    return ChipPin(
        "BGA516",
        ball,
        symbol,
        direction,
        "FAST / PU1 / VEXT / ES",
        function,
        mux,
        "14",
        f"{ball} {symbol} I FAST / {function}",
    )


def _constraint_rows(sheet) -> dict[str, list[tuple]]:
    found: dict[str, list[tuple]] = {}
    for row in sheet.iter_rows(min_row=2, values_only=True):
        symbol = row[0]
        if not symbol:
            continue
        found.setdefault(str(symbol), []).append(tuple(row))
    return found


class PinParseTests(unittest.TestCase):
    def test_mcu_name_from_filename(self) -> None:
        self.assertEqual(mcu_name("infineon-tc38x-datasheet-en.pdf"), "TC38x")
        self.assertEqual(mcu_name("Infineon-TC39x-DataSheet-v01_02-EN.pdf"), "TC39x")
        self.assertEqual(mcu_name("infineon-sak-tc499pp-20mf400ms-ab-datasheet-en.pdf"), "TC499")
        self.assertEqual(mcu_name("Infineon-SAK-TC377TP-96F300S-DataSheet-v01_02-EN.pdf"), "TC377")
        self.assertEqual(mcu_name("Infineon-TC36x-DataSheet-v01_01-EN.pdf"), "TC36x")
        self.assertEqual(mcu_name("NXP_S32K344_Datasheet_Rev4.pdf"), "S32K344")
        self.assertEqual(mcu_name("Renesas_RH850_U2A_Datasheet.pdf"), "RH850-U2A")
        self.assertEqual(mcu_name("SemiDrive_E3640_Datasheet_V1.0.pdf"), "E3640")
        self.assertEqual(
            mcu_name("mcu_datasheet_v1.0.pdf", [(1, "NXP S32K144 Data Sheet")]),
            "S32K144",
        )
        self.assertEqual(mcu_name("ZX900M_Datasheet_V1.2_EN.pdf"), "ZX900M")

    def test_package_titles_skip_outline_and_keep_order(self) -> None:
        titles = (
            "2.1 LFBGA-516 Package Variant Pin Configuration",
            "2.2 LFBGA-292 Package Variant Pin Configuration",
            "2.3 LFBGA-292 ADAS Package Variant Pin Configuration",
            "3.34 Package Outline",
            "3.2 BGA436_STD package variant pin configuration",
            "3.2.1 BGA436_STD port 00",
            "2.4 PG-LQFP-176 Package Variant Pin Configuration",
            "2.5 TQFP-144 Pin Assignment",
        )
        self.assertEqual(
            packages_in_titles(titles),
            ("LFBGA516", "LFBGA292", "BGA436", "LQFP176", "TQFP144"),
        )

    def test_two_packages_stay_separate(self) -> None:
        pages = [(14, _PAGE), (180, _OTHER)]
        self.assertEqual(parse_pin_pages(pages), ("BGA516", "BGA292"))
        wide = parse_pins(pages, "BGA516")
        small = parse_pins(pages, "BGA292")
        self.assertEqual([pin.symbol for pin in wide], ["P00.0", "P00.1"])
        self.assertEqual(wide[0].ball, "M6")
        self.assertEqual(wide[0].direction, "Input/Output")
        self.assertIn("FAST", wide[0].buffer)
        self.assertIn("General-purpose input", wide[0].function)
        self.assertIn("GTM_TOUT9", wide[0].mux)
        self.assertEqual(wide[0].page, "14")
        self.assertIn("M6 P00.0", wide[0].excerpt)
        self.assertEqual(small[0].ball, "A2")
        self.assertNotEqual(small[0].ball, wide[0].ball)

    def test_analog_supply_stays_out_of_the_function(self) -> None:
        page = """
3.2.24 BGA436_STD port 40
W13 AN0 I D / HighZ /
VDDM
Analog Input 0
ADC_TMADC0CH0 Analog Input for TMADC0 Channel 0
"""
        pins = parse_pins([(246, page)], "BGA436")
        self.assertEqual(len(pins), 1)
        self.assertEqual(pins[0].function, "Analog Input 0")
        self.assertIn("VDDM", pins[0].buffer)
        self.assertNotIn("VDDM", pins[0].function)

    def test_split_header_keeps_the_next_pin(self) -> None:
        page = """
3.2.24 BGA436_STD port 40
U1 AN66 I D / HighZ /
VDDM
Analog Input 66
ADC_DSADC2PC Analog Input for DSADC2 Positive Input C
T1 AN67 /
P41.0
I S / PU1 /
VDDM
Analog Input 67
General-purpose input
ADC_DSADC2NC Analog Input for DSADC2 Negative Input C
"""
        pins = parse_pins([(254, page)], "BGA436")
        by_symbol = {pin.symbol: pin for pin in pins}
        self.assertEqual(set(by_symbol), {"AN66", "AN67"})
        self.assertEqual(by_symbol["AN66"].ball, "U1")
        self.assertEqual(by_symbol["AN66"].function, "Analog Input 66")
        self.assertNotIn("AN67", by_symbol["AN66"].excerpt)
        self.assertEqual(by_symbol["AN67"].ball, "T1")
        self.assertEqual(by_symbol["AN67"].function, "Analog Input 67")
        self.assertEqual(by_symbol["AN67"].direction, "Input")
        self.assertIn("P41.0", by_symbol["AN67"].mux)
        self.assertIn("VDDM", by_symbol["AN67"].buffer)
        self.assertIn("PU1", by_symbol["AN67"].buffer)

    def test_slash_buffer_line_is_not_the_function(self) -> None:
        page = """
Pin Definition and Functions BGA292 Package Variant Pin Configuration
TC38x AD/AE-Step
B12 P13.0 I LVDS_TX
/ FAST /
PU1 /
VEXT /
ES6
General-purpose input
GTM_TIM3_IN5_3 Mux input channel 5 of TIM module 3
P13.0 O0 General-purpose output
D12 P14.9 I LVDS_R
X / FAST /
PU1 /
VEXT /
ES
General-purpose input
P14.9 O0 General-purpose output
Y16 P33.13 I FAST /
PU1 /
VEVRSB
/ ES5
General-purpose input
GTM_TOUT9 O1 GTM muxed output
TC38x AD/AE-Step
CAN10_TXD O7 CAN transmit output node 0
P33.13 O0 General-purpose output
"""
        pins = {pin.symbol: pin for pin in parse_pins([(201, page)], "BGA292")}
        self.assertEqual(set(pins), {"P13.0", "P14.9", "P33.13"})
        self.assertEqual(pins["P13.0"].function, "General-purpose input")
        self.assertIn("LVDS_TX", pins["P13.0"].buffer)
        self.assertIn("FAST", pins["P13.0"].buffer)
        self.assertIn("ES6", pins["P13.0"].buffer)
        self.assertNotIn("FAST", pins["P13.0"].function)
        self.assertIn("GTM_TIM3_IN5_3", pins["P13.0"].mux)
        self.assertNotIn("AD/AE-Step", pins["P13.0"].mux)
        self.assertNotIn("AD/AE-Step", pins["P13.0"].excerpt)
        self.assertEqual(pins["P14.9"].function, "General-purpose input")
        self.assertIn("LVDS_R", pins["P14.9"].buffer)
        self.assertIn("X", pins["P14.9"].buffer.split(" / "))
        self.assertIn("FAST", pins["P14.9"].buffer)
        self.assertEqual(pins["P33.13"].function, "General-purpose input")
        self.assertIn("VEVRSB", pins["P33.13"].buffer)
        self.assertIn("ES5", pins["P33.13"].buffer)
        self.assertIn("CAN10_TXD", pins["P33.13"].mux)
        self.assertNotIn("AD/AE-Step", pins["P33.13"].mux)
        self.assertNotIn("AD/AE-Step", pins["P33.13"].excerpt)

    def test_lqfp_numeric_pins_and_system_io_and_inline_alias(self) -> None:
        page = """
Pin Definition and Functions PG-LQFP-176 Package Variant Pin Configuration
1 PTA0 I FAST /
PU1 /
VDDEXT
General-purpose input
PTA0 O0 General-purpose output
12 AN17/P40.10 I S / HighZ /
VDDM
Analog Input 17
EVADC_G2CH1 Analog input channel 1
144 ESR0 I/O FAST /
OD /
VDDEXT
ESR0 Port Pin input
PMS_ESR0WKP I ESR0 pin input
Table 2-24 Supply
176 VDD I — Digital Core Power Supply
"""
        self.assertEqual(parse_pin_pages([(10, page)]), ("LQFP176",))
        pins = {pin.symbol: pin for pin in parse_pins([(10, page)], "LQFP176")}
        self.assertEqual(set(pins), {"PTA0", "AN17", "ESR0"})
        self.assertEqual(pins["PTA0"].ball, "1")
        self.assertEqual(pins["PTA0"].direction, "Input/Output")
        self.assertEqual(pins["AN17"].ball, "12")
        self.assertIn("P40.10", pins["AN17"].mux)
        self.assertEqual(pins["ESR0"].ball, "144")
        self.assertEqual(pins["ESR0"].direction, "Input/Output")
        self.assertNotIn("Digital Core Power Supply", pins["ESR0"].mux)


class HsiBookTests(unittest.TestCase):
    def test_first_issue_drops_template_history_and_unmatched_names(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            template = root / "template.xlsx"
            dest = root / "out.xlsx"
            _template(template)
            result = write_hsi_workbook(
                template,
                dest,
                mcu="TC38x",
                package="BGA516",
                pins=(
                    _pin("P00.0", "M6", "General-purpose input", "GTM_TOUT9"),
                    _pin("P00.1", "K5", "General-purpose input"),
                ),
            )
            self.assertEqual(result.version, "TC38x-BGA516-1")
            self.assertEqual(result.changes, 0)
            book = load_workbook(dest, data_only=True)
            try:
                history = [row[2] for row in book[SHEET_HISTORY].iter_rows(values_only=True)]
                self.assertEqual(history, ["详细描述"])
                port = book[SHEET_PORT]
                self.assertEqual(port["A2"].value, "TC38x Port Assignment [Main Table]")
                self.assertEqual(port["B5"].value, "P00.0")
                self.assertEqual(port["C5"].value, "M6")
                self.assertEqual(port["J5"].value, "KEEP_ME")
                self.assertEqual(port["L5"].value, "L1")
                self.assertEqual(port["M5"].value, "QM")
                self.assertEqual(port.cell(5, COL_STATUS).value, STATUS_DRAFT)
                self.assertNotEqual(port.cell(5, COL_STATUS).value, "已确认")
                self.assertEqual(port.cell(6, COL_STATUS).value, STATUS_GAP)
                self.assertIsNone(port["J6"].value)
                self.assertIn("吉利模板没有该引脚符号", port.cell(6, COL_MARK).value)
                symbols = [port.cell(row, 2).value for row in range(5, 8)]
                self.assertNotIn("AN0", symbols)
                self.assertNotIn("IA_S/M_P3", [port.cell(row, 10).value for row in range(5, 8)])
                evidence = book[SHEET_EVIDENCE]
                self.assertEqual(evidence["A2"].value, "P00.0")
                self.assertEqual(evidence["G2"].value, "14")
                self.assertIn("M6 P00.0", evidence["H2"].value)
                constraints = _constraint_rows(book[SHEET_CONSTRAINT])
                self.assertEqual(constraints["P00.0"][0][1], "KEEP_ME")
                self.assertEqual(constraints["P00.0"][0][11], "吉利模板")
                self.assertEqual(constraints["P00.0"][0][12], STATUS_DRAFT)
                self.assertEqual(constraints["P00.1"][0][12], STATUS_GAP)
                self.assertEqual(constraints["AN0"][0][1], "IA_S/M_P3")
                self.assertEqual(constraints["AN0"][0][12], STATUS_GAP)
                self.assertIn("当份手册未出现该引脚符号", constraints["AN0"][0][13])
                self.assertEqual(book[SHEET_REVISION].max_row, 1)
                self.assertIn("不计算匹配率", book[SHEET_ACCEPT]["A1"].value)
                self.assertIsNone(book[SHEET_ACCEPT]["B3"].value)
                self.assertEqual(book["5_CAN"]["A1"].value, "模板CAN")
                self.assertEqual(book["0_Cover"]["D3"].value, "TC38x-BGA516-1")
                self.assertEqual(book.active.title, SHEET_PORT)
            finally:
                book.close()

    def test_second_issue_records_only_the_difference(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            template = root / "template.xlsx"
            first = root / "v1.xlsx"
            second = root / "v2.xlsx"
            _template(template)
            pins = (_pin("P00.0", "M6", "General-purpose input"),)
            write_hsi_workbook(template, first, mcu="TC38x", package="BGA516", pins=pins)
            edited = load_workbook(first)
            edited[SHEET_PORT]["J5"] = "OLD_NAME"
            edited[SHEET_PORT]["L5"] = "L9"
            edited[SHEET_PORT].cell(5, COL_HUMAN, "现场已改")
            edited[SHEET_REVISION]["A2"] = "P00.0"
            edited[SHEET_REVISION]["B2"] = "端口名改为现场名称"
            edited[SHEET_ACCEPT]["A3"] = "P00.0"
            edited[SHEET_ACCEPT]["B3"] = "实测一致"
            edited.save(first)
            edited.close()
            changed = (_pin("P00.0", "M7", "General-purpose input"),)
            result = write_hsi_workbook(
                template,
                second,
                mcu="TC38x",
                package="BGA516",
                pins=changed,
                previous=first,
            )
            self.assertEqual(result.version, "TC38x-BGA516-2")
            self.assertEqual(result.changes, 1)
            book = load_workbook(second, data_only=True)
            try:
                detail = book[SHEET_HISTORY].cell(2, 3).value
                self.assertIn("球号由M6变更为M7", detail)
                self.assertNotIn("模板里的旧变更", detail)
                self.assertEqual(book[SHEET_HISTORY].cell(2, 4).value, "需人工确认")
                self.assertEqual(book[SHEET_PORT]["J5"].value, "KEEP_ME")
                self.assertEqual(book[SHEET_PORT]["L5"].value, "L1")
                self.assertNotEqual(book[SHEET_PORT]["J5"].value, "OLD_NAME")
                self.assertEqual(book[SHEET_PORT].cell(5, COL_HUMAN).value, "现场已改")
                self.assertEqual(book[SHEET_REVISION]["B2"].value, "端口名改为现场名称")
                self.assertEqual(book[SHEET_ACCEPT]["B3"].value, "实测一致")
                self.assertNotIn("%", str(book[SHEET_ACCEPT]["B3"].value))
            finally:
                book.close()

    def test_multiple_names_are_not_reduced_to_one(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            template = root / "template.xlsx"
            dest = root / "out.xlsx"
            _template(template)
            book = load_workbook(template)
            book[SHEET_PORT]["B7"] = "P00.0"
            book[SHEET_PORT]["J7"] = "OTHER_NAME"
            book[SHEET_PORT]["L7"] = "L2"
            book.save(template)
            book.close()
            write_hsi_workbook(
                template,
                dest,
                mcu="TC38x",
                package="BGA516",
                pins=(_pin("P00.0", "M6", "General-purpose input"),),
            )
            book = load_workbook(dest, data_only=True)
            try:
                port = book[SHEET_PORT]
                self.assertIsNone(port["J5"].value)
                self.assertEqual(port.cell(5, COL_STATUS).value, STATUS_MULTI)
                self.assertIn("KEEP_ME", port.cell(5, COL_MARK).value)
                self.assertIn("OTHER_NAME", port.cell(5, COL_MARK).value)
                names = [row[1] for row in _constraint_rows(book[SHEET_CONSTRAINT])["P00.0"]]
                self.assertEqual(names, ["KEEP_ME", "OTHER_NAME"])
            finally:
                book.close()

    def test_opposite_direction_is_marked_and_not_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            template = root / "template.xlsx"
            dest = root / "out.xlsx"
            _template(template)
            book = load_workbook(template)
            book[SHEET_PORT]["H6"] = "Output"
            book.save(template)
            book.close()
            write_hsi_workbook(
                template,
                dest,
                mcu="TC38x",
                package="BGA516",
                pins=(_pin("P00.0", "M6", "General-purpose input", direction="Input"),),
            )
            book = load_workbook(dest, data_only=True)
            try:
                port = book[SHEET_PORT]
                self.assertEqual(port["H5"].value, "Input")
                self.assertEqual(port["J5"].value, "KEEP_ME")
                self.assertEqual(port.cell(5, COL_STATUS).value, STATUS_CONFLICT)
                self.assertNotEqual(port.cell(5, COL_STATUS).value, "已确认")
                self.assertIn("手册方向为 Input", port.cell(5, COL_MARK).value)
                self.assertIn("吉利模板方向为 Output", port.cell(5, COL_MARK).value)
            finally:
                book.close()

    def test_same_port_name_on_two_pins_is_multiple_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            template = root / "template.xlsx"
            dest = root / "out.xlsx"
            _template(template)
            book = load_workbook(template)
            book[SHEET_PORT]["B7"] = "P00.1"
            book[SHEET_PORT]["J7"] = "KEEP_ME"
            book.save(template)
            book.close()
            write_hsi_workbook(
                template,
                dest,
                mcu="TC38x",
                package="BGA516",
                pins=(
                    _pin("P00.0", "M6", "General-purpose input"),
                    _pin("P00.1", "K5", "General-purpose input"),
                ),
            )
            book = load_workbook(dest, data_only=True)
            try:
                port = book[SHEET_PORT]
                self.assertEqual(port["J5"].value, "KEEP_ME")
                self.assertEqual(port["J6"].value, "KEEP_ME")
                self.assertEqual(port.cell(5, COL_STATUS).value, STATUS_MULTI)
                self.assertEqual(port.cell(6, COL_STATUS).value, STATUS_MULTI)
                self.assertIn("P00.1", port.cell(5, COL_MARK).value)
                self.assertIn("P00.0", port.cell(6, COL_MARK).value)
            finally:
                book.close()

    def test_unconnected_name_is_not_treated_as_multiple_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            template = root / "template.xlsx"
            dest = root / "out.xlsx"
            _template(template)
            book = load_workbook(template)
            book[SHEET_PORT]["J6"] = "NC"
            book[SHEET_PORT]["B7"] = "P00.1"
            book[SHEET_PORT]["J7"] = "NC"
            book.save(template)
            book.close()
            write_hsi_workbook(
                template,
                dest,
                mcu="TC38x",
                package="BGA516",
                pins=(
                    _pin("P00.0", "M6", "General-purpose input"),
                    _pin("P00.1", "K5", "General-purpose input"),
                ),
            )
            book = load_workbook(dest, data_only=True)
            try:
                port = book[SHEET_PORT]
                self.assertEqual(port.cell(5, COL_STATUS).value, STATUS_DRAFT)
                self.assertEqual(port.cell(6, COL_STATUS).value, STATUS_DRAFT)
            finally:
                book.close()

    def test_generated_sheets_are_wide_enough_to_read(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            template = root / "template.xlsx"
            dest = root / "out.xlsx"
            _template(template)
            prepared = load_workbook(template)
            prepared[SHEET_PORT]["K6"] = "三相电流采样输入，需对照手册确认电平与复位状态后再使用"
            prepared.save(template)
            prepared.close()
            write_hsi_workbook(
                template,
                dest,
                mcu="TC38x",
                package="BGA516",
                pins=(_pin("P00.0", "M6", "General-purpose input"),),
            )
            book = load_workbook(dest)
            try:
                sheet = book[SHEET_CONSTRAINT]
                self.assertGreaterEqual(sheet.column_dimensions["A"].width, 12)
                self.assertGreaterEqual(sheet.column_dimensions["G"].width, 14)
                self.assertGreaterEqual(sheet.column_dimensions["H"].width, 16)
                self.assertEqual(sheet.column_dimensions["C"].width, 40)
                self.assertLessEqual(sheet.column_dimensions["N"].width, 40)
                self.assertTrue(sheet["C2"].alignment.wrap_text)
                self.assertGreater(sheet.row_dimensions[2].height, 15)
                self.assertEqual(sheet.freeze_panes, "A2")
                evidence = book[SHEET_EVIDENCE]
                self.assertGreaterEqual(evidence.column_dimensions["A"].width, 12)
                self.assertLessEqual(evidence.column_dimensions["H"].width, 40)
                accept = book[SHEET_ACCEPT]
                self.assertIn("不计算匹配率", accept["A1"].value)
                self.assertTrue(accept["A1"].alignment.wrap_text)
                self.assertEqual(accept.freeze_panes, "A3")
            finally:
                book.close()

    def test_combined_alias_symbol_matches_pin_and_mux(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            template = root / "template.xlsx"
            dest = root / "out.xlsx"
            _template(template)
            book = load_workbook(template)
            book[SHEET_PORT]["B7"] = "AN17/P40_10"
            book[SHEET_PORT]["C7"] = "W8"
            book[SHEET_PORT]["H7"] = "Input"
            book[SHEET_PORT]["I7"] = "Analog"
            book[SHEET_PORT]["J7"] = "ISS_S/M_SIG"
            book[SHEET_PORT]["K7"] = "轴速故障识别"
            book.save(template)
            book.close()
            write_hsi_workbook(
                template,
                dest,
                mcu="TC499",
                package="BGA436",
                pins=(
                    _pin(
                        "AN17",
                        "W8",
                        "Analog Input 17",
                        "P40.10 General-purpose input\nADC_TMADC1CH5 Analog Input",
                        direction="Input",
                    ),
                ),
            )
            out = load_workbook(dest, data_only=True)
            try:
                port = out[SHEET_PORT]
                self.assertEqual(port["B5"].value, "AN17")
                self.assertEqual(port["J5"].value, "ISS_S/M_SIG")
                self.assertEqual(port.cell(5, COL_STATUS).value, STATUS_DRAFT)
                self.assertIn("AN17/P40_10", port.cell(5, COL_MARK).value)
                constraints = _constraint_rows(out[SHEET_CONSTRAINT])
                self.assertEqual(constraints["AN17/P40_10"][0][12], STATUS_DRAFT)
            finally:
                out.close()

    def test_peripheral_mux_conflict_and_level_column_inversion_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            template = root / "template.xlsx"
            dest = root / "out.xlsx"
            _template(template)
            book = load_workbook(template)
            # P00.0 template requires CAN TXD, but datasheet pin has only GTM mux (no CAN)
            book[SHEET_PORT]["H6"] = "Output"
            book[SHEET_PORT]["I6"] = "CAN"
            book[SHEET_PORT]["J6"] = "CAN1N0-TXD-Chassis3"
            # P00.1 template puts "High" inside the "Low or falling" column (col 17 / Q)
            book[SHEET_PORT]["B7"] = "P00.1"
            book[SHEET_PORT]["H7"] = "Input"
            book[SHEET_PORT]["I7"] = "PWM"
            book[SHEET_PORT]["J7"] = "GL_A1_MON"
            book[SHEET_PORT]["Q7"] = "High"
            book.save(template)
            book.close()
            res = write_hsi_workbook(
                template,
                dest,
                mcu="TC38x",
                package="BGA516",
                pins=(
                    _pin("P00.0", "M6", "General-purpose input", "GTM_TOUT9 O1 GTM muxed output"),
                    _pin("P00.1", "K5", "General-purpose input", "GTM_TIM5_IN4 Mux input"),
                ),
            )
            self.assertEqual(res.conflicts, 2)
            out = load_workbook(dest, data_only=True)
            try:
                port = out[SHEET_PORT]
                self.assertEqual(port.cell(5, COL_STATUS).value, STATUS_CONFLICT)
                self.assertIn("无 CAN 复用功能", port.cell(5, COL_MARK).value)
                self.assertEqual(port.cell(6, COL_STATUS).value, STATUS_CONFLICT)
                self.assertIn("低电平或下降沿", port.cell(6, COL_MARK).value)
            finally:
                out.close()

    def test_cross_subsheet_inconsistency_and_llm_ask_review(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            template = root / "template.xlsx"
            dest = root / "out.xlsx"
            _template(template)
            book = load_workbook(template)
            book[SHEET_PORT]["H5"] = "Input"
            book[SHEET_PORT]["I5"] = "Analog"
            book[SHEET_PORT]["J5"] = "Oil_M_TEMP"
            book[SHEET_PORT]["K5"] = "油温检测"
            adc = book.create_sheet("3_ADC Table")
            adc.cell(5, 5, "AN0")
            adc.cell(5, 6, "Y9")
            adc.cell(5, 7, "TEM_S/M_OIL")
            adc.cell(5, 8, "油温检测")
            book.save(template)
            book.close()

            seen_messages: list[list[dict[str, str]]] = []

            def fake_ask(messages: list[dict[str, str]]) -> str:
                seen_messages.append(messages)
                return '[{"symbol": "AN0", "level": "conflict", "reason": "主表端口名 Oil_M_TEMP 与 ADC 子表信号名 TEM_S/M_OIL 及球号不一致"}]'

            res = write_hsi_workbook(
                template,
                dest,
                mcu="TC499",
                package="BGA436",
                pins=(
                    _pin("AN0", "W13", "Analog Input 0", "ADC_TMADC0CH0", direction="Input"),
                ),
                ask=fake_ask,
            )
            self.assertTrue(res.model_used)
            self.assertEqual(res.conflicts, 1)
            self.assertEqual(len(seen_messages), 1)
            out = load_workbook(dest, data_only=True)
            try:
                port = out[SHEET_PORT]
                self.assertEqual(port.cell(5, COL_STATUS).value, STATUS_CONFLICT)
                mark = str(port.cell(5, COL_MARK).value or "")
                self.assertIn("3_ADC Table", mark)
                self.assertIn("TEM_S/M_OIL", mark)
                self.assertIn("【工程质检】", mark)
            finally:
                out.close()

