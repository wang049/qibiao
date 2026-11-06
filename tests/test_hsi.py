from __future__ import annotations

import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Border, PatternFill, Side

_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)

_GEELY_TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "electrical_krow"
    / "templates"
    / "PCM-HSI-吉利模板-V1.0-20251024.xlsx"
)


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
    build_hsi,
    write_hsi_workbook,
)
from electrical_krow.mcu_pins import (
    ChipPin,
    mcu_name,
    packages_in_titles,
    parse_pin_pages,
    parse_pins,
    pin_class,
    pin_supply_kind,
)

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
        self.assertIn("VDD", pins)
        self.assertEqual(pins["VDD"].ball, "176")
        self.assertEqual(pins["VDD"].function, "Digital Core Power Supply")
        self.assertEqual(pin_supply_kind("VDD"), "电源")
        self.assertEqual(pins["PTA0"].ball, "1")
        self.assertEqual(pins["PTA0"].direction, "Input/Output")
        self.assertEqual(pins["AN17"].ball, "12")
        self.assertIn("P40.10", pins["AN17"].mux)
        self.assertEqual(pins["ESR0"].ball, "144")
        self.assertEqual(pins["ESR0"].direction, "Input/Output")
        self.assertNotIn("Digital Core Power Supply", pins["ESR0"].mux)

    def test_supply_balls_sharing_one_symbol_are_all_kept(self) -> None:
        page = """
Ball Symbol Ctrl.
3.2.24 BGA436_STD system
Table 30 Supply functions
K12, K13,
K14, K15
VSS I — Digital Ground
A2, AA22 VDDEXT I — External Power Supply
AC10 VAGND1 I — Negative Analog Reference Voltage 1
"""
        pins = parse_pins([(258, page)], "BGA436")
        balls = {pin.ball: pin.symbol for pin in pins}
        self.assertEqual(
            balls,
            {
                "K12": "VSS",
                "K13": "VSS",
                "K14": "VSS",
                "K15": "VSS",
                "A2": "VDDEXT",
                "AA22": "VDDEXT",
                "AC10": "VAGND1",
            },
        )
        self.assertEqual(pin_supply_kind("VSS"), "地")
        self.assertEqual(pin_supply_kind("VAGND1"), "地")
        self.assertEqual(pin_supply_kind("VDDEXT"), "电源")

    def test_read_pdf_pages_reports_each_page(self) -> None:
        from pypdf import PdfWriter

        from electrical_krow.mcu_pins import read_pdf_pages

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "manual.pdf"
            writer = PdfWriter()
            for _ in range(3):
                writer.add_blank_page(width=200, height=200)
            with path.open("wb") as handle:
                writer.write(handle)
            seen: list[tuple[int, int]] = []
            pages = read_pdf_pages(path, on_progress=lambda done, total: seen.append((done, total)))
        self.assertEqual(len(pages), 3)
        self.assertEqual(seen, [(0, 3), (1, 3), (2, 3), (3, 3)])


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
                self.assertIsNone(port["L5"].value)
                self.assertIsNone(port["M5"].value)
                self.assertEqual(port.cell(5, COL_STATUS).value, STATUS_DRAFT)
                self.assertNotEqual(port.cell(5, COL_STATUS).value, "已确认")
                self.assertNotIn("模板有端口名 KEEP_ME", str(port.cell(5, COL_MARK).value or ""))
                self.assertEqual(port.cell(6, COL_STATUS).value, STATUS_GAP)
                self.assertIsNone(port["J6"].value)
                self.assertIn("模板没有该引脚符号", port.cell(6, COL_MARK).value)
                symbols = [port.cell(row, 2).value for row in range(5, 8)]
                self.assertNotIn("AN0", symbols)
                self.assertNotIn("IA_S/M_P3", [port.cell(row, 10).value for row in range(5, 8)])
                evidence = book[SHEET_EVIDENCE]
                self.assertEqual(evidence["A2"].value, "P00.0")
                self.assertEqual(evidence["G2"].value, "14")
                self.assertIn("M6 P00.0", evidence["H2"].value)
                constraints = _constraint_rows(book[SHEET_CONSTRAINT])
                self.assertEqual(constraints["P00.0"][0][1], "KEEP_ME")
                self.assertEqual(constraints["P00.0"][0][11], "HSI模板")
                self.assertEqual(constraints["P00.0"][0][12], STATUS_DRAFT)
                self.assertEqual(constraints["P00.1"][0][12], STATUS_GAP)
                self.assertEqual(constraints["AN0"][0][1], "IA_S/M_P3")
                self.assertEqual(constraints["AN0"][0][12], STATUS_GAP)
                self.assertIn("当份手册未出现该引脚符号", constraints["AN0"][0][13])
                self.assertEqual(book[SHEET_REVISION].max_row, 1)
                self.assertEqual(book[SHEET_ACCEPT]["A1"].value, "引脚符号")
                self.assertNotIn("书面确认", str(book[SHEET_ACCEPT]["A1"].value or ""))
                self.assertIsNone(book[SHEET_ACCEPT]["B2"].value)
                self.assertNotIn("5_CAN", book.sheetnames)
                self.assertIn(SHEET_EVIDENCE, book.sheetnames)
                self.assertIn(SHEET_CONSTRAINT, book.sheetnames)
                self.assertIn(SHEET_REVISION, book.sheetnames)
                self.assertIn(SHEET_ACCEPT, book.sheetnames)
                self.assertEqual(book["0_Cover"]["D3"].value, "TC38x-BGA516-1")
                self.assertEqual(book.active.title, SHEET_PORT)
            finally:
                book.close()

    def test_cover_remarks_wrap_inside_the_change_block(self) -> None:
        from openpyxl.styles import Border, Side

        from electrical_krow.hsi_book import _COVER_REMARK, _write_cover

        book = Workbook()
        sheet = book.active
        sheet["D2"] = "Version"
        sheet["E2"] = "Remarks"
        thin = Border(
            left=Side(style="thin"),
            right=Side(style="thin"),
            top=Side(style="thin"),
            bottom=Side(style="thin"),
        )
        for row in range(3, 6):
            sheet.cell(row, 5).border = thin
        _write_cover(sheet, "20261021", "首次按手册生成端口表", "TC38x-BGA516-1", _COVER_REMARK)
        self.assertTrue(sheet["E3"].alignment.wrap_text)
        self.assertIn("E3:E5", [str(item) for item in sheet.merged_cells.ranges])
        self.assertLessEqual(len(_COVER_REMARK), 60)
        book.close()

    def test_cover_toc_lists_the_same_sheets_as_the_tabs(self) -> None:
        from electrical_krow.hsi_book import _drop_unused_template_sheets, _sync_cover_toc, _toc_items

        book = load_workbook(_GEELY_TEMPLATE)
        try:
            for title in (SHEET_EVIDENCE, SHEET_CONSTRAINT, SHEET_REVISION, SHEET_ACCEPT):
                if title not in book.sheetnames:
                    book.create_sheet(title)
            _drop_unused_template_sheets(book)
            _sync_cover_toc(book["0_Cover"], book.sheetnames)
            cover = book["0_Cover"]
            listed = []
            for row in range(13, 80):
                number = cover.cell(row, 2).value
                if not isinstance(number, int):
                    break
                listed.append(cover.cell(row, 3).value)
            self.assertEqual(listed, _toc_items(book.sheetnames))
            self.assertIn("ADC Table（模板对照）", listed)
            self.assertIn("SPI总线（模板对照）", listed)
            self.assertNotIn("TLF4D985", listed)
            self.assertNotIn("OD_LED", listed)
            self.assertNotIn("4_TLF4D985", book.sheetnames)
            self.assertNotIn("34_OD_LED", book.sheetnames)
            self.assertIn("3_ADC Table", book.sheetnames)
            self.assertIn("3-SPI总线", book.sheetnames)
            self.assertEqual(listed[:4], ["Chang History", "Port Assignment", "ADC Table（模板对照）", "SPI总线（模板对照）"])
            self.assertEqual(listed[-4:], [SHEET_EVIDENCE, SHEET_CONSTRAINT, SHEET_REVISION, SHEET_ACCEPT])
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
                self.assertIsNone(book[SHEET_PORT]["J5"].value)
                self.assertIsNone(book[SHEET_PORT]["L5"].value)
                self.assertEqual(book[SHEET_PORT].cell(5, COL_HUMAN).value, "现场已改")
                self.assertEqual(book[SHEET_REVISION]["B2"].value, "端口名改为现场名称")
                self.assertEqual(book[SHEET_ACCEPT]["B3"].value, "实测一致")
                self.assertNotIn("%", str(book[SHEET_ACCEPT]["B3"].value))
                self.assertNotIn("书面确认", str(book["0_Cover"]["E3"].value or ""))
                self.assertNotIn("只保留已有内容", str(book["0_Cover"]["E3"].value or ""))
            finally:
                book.close()

    def test_old_accept_banner_is_not_copied_forward(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            template = root / "template.xlsx"
            first = root / "v1.xlsx"
            second = root / "v2.xlsx"
            _template(template)
            pins = (_pin("P00.0", "M6", "General-purpose input"),)
            write_hsi_workbook(template, first, mcu="TC38x", package="BGA516", pins=pins)
            edited = load_workbook(first)
            edited[SHEET_ACCEPT]["A1"] = (
                "本表只保留已填写的实测值。生成时不计算匹配率、安全率；"
                "技术协议未规定这两项的数值阈值，口径须书面确认。"
            )
            edited[SHEET_ACCEPT]["A2"] = "引脚符号"
            edited[SHEET_ACCEPT]["B2"] = "匹配实测"
            edited[SHEET_ACCEPT]["A3"] = "P00.0"
            edited[SHEET_ACCEPT]["B3"] = "实测一致"
            edited.save(first)
            edited.close()
            write_hsi_workbook(
                template,
                second,
                mcu="TC38x",
                package="BGA516",
                pins=pins,
                previous=first,
            )
            book = load_workbook(second, data_only=True)
            try:
                accept = book[SHEET_ACCEPT]
                self.assertEqual(accept["A1"].value, "引脚符号")
                self.assertEqual(accept["B2"].value, "实测一致")
                for row in accept.iter_rows(values_only=True):
                    self.assertNotIn("书面确认", str(row[0] or ""))
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
                self.assertIn("模板方向为 Output", port.cell(5, COL_MARK).value)
                self.assertNotIn("模板有端口名 KEEP_ME", str(port.cell(5, COL_MARK).value or ""))
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
                self.assertEqual(accept["A1"].value, "引脚符号")
                self.assertNotIn("书面确认", str(accept["A1"].value or ""))
                self.assertEqual(accept.freeze_panes, "A2")
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
                self.assertNotIn("模板有端口名 ISS_S/M_SIG", str(port.cell(5, COL_MARK).value or ""))
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

    def test_supply_stuck_to_a_function_name_goes_back_to_the_buffer(self) -> None:
        page = """
3.2 BGA436_STD port 15
B22 P15.12 I FAST /
PU1 /
General-purpose input
GTM_TIM2_IN3_6 VDDEXTH
S /
ES6
Mux input channel 3 of TIM module 2
GTM_TOUT244 O1 GTM muxed output
— O4 Reserved
— O5 Reserved
QSPI5_SLSO1 O2 Master slave select output
"""
        pins = parse_pins([(30, page)], "BGA436")
        self.assertEqual(len(pins), 1)
        pin = pins[0]
        self.assertEqual(pin.function, "General-purpose input")
        self.assertIn("VDDEXTH", pin.buffer)
        self.assertIn("ES6", pin.buffer)
        self.assertNotIn("VDDEXTH", pin.mux)
        self.assertIn("GTM_TIM2_IN3_6 Mux input channel 3 of TIM module 2", pin.mux)
        self.assertIn("QSPI5_SLSO1", pin.mux)

    def test_excerpt_drops_reserved_and_port_sheet_can_be_filtered(self) -> None:
        page = """
3.2 BGA436_STD port 15
B22 P15.12 I FAST /
PU1 /
General-purpose input
GTM_TIM2_IN3_6 VDDEXTH
Mux input channel 3 of TIM module 2
— O4 Reserved
— O12 Reserved
QSPI5_SLSO1 O2 Master slave select output
"""
        pins = parse_pins([(30, page)], "BGA436")
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            template = root / "template.xlsx"
            dest = root / "out.xlsx"
            _template(template)
            book = load_workbook(template)
            book[SHEET_PORT]["C1"] = "返回首页"
            book.save(template)
            book.close()
            write_hsi_workbook(
                template,
                dest,
                mcu="TC499",
                package="BGA436",
                pins=pins,
            )
            out = load_workbook(dest)
            try:
                port = out[SHEET_PORT]
                mux = str(port.cell(5, 14).value or "")
                excerpt = str(port.cell(5, 21).value or "")
                self.assertNotIn("Reserved", mux)
                self.assertNotIn("Reserved", excerpt)
                self.assertNotIn("VDDEXTH", mux)
                self.assertNotIn("VDDEXTH", excerpt)
                self.assertEqual(port.cell(5, 6).value, "VDDEXTH")
                self.assertIn("QSPI5_SLSO1", mux)
                self.assertIn("GTM_TIM2_IN3_6", mux)
                self.assertIn("\n", mux)
                self.assertTrue(port.cell(5, 14).alignment.wrap_text)
                self.assertTrue(port.cell(5, 21).alignment.wrap_text)
                self.assertGreaterEqual(port.column_dimensions["N"].width, 48)
                self.assertGreaterEqual(port.column_dimensions["U"].width, 48)
                self.assertEqual(port.auto_filter.ref, "A4:X5")
                link = port["C1"].hyperlink
                self.assertIsNotNone(link)
                self.assertIn("0_Cover", link.location or "")
                self.assertFalse(link.target)
                evidence = out[SHEET_EVIDENCE]
                self.assertNotIn("Reserved", str(evidence["F2"].value or ""))
                self.assertNotIn("Reserved", str(evidence["H2"].value or ""))
            finally:
                out.close()

    def test_llm_conflict_that_denies_the_manual_mux_is_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            template = root / "template.xlsx"
            dest = root / "out.xlsx"
            _template(template)
            book = load_workbook(template)
            port = book[SHEET_PORT]
            port["H6"] = "Input"
            port["I6"] = "SPI"
            port["J6"] = "SCLK_M"
            port["B7"] = "P00.1"
            port["H7"] = "Input"
            port["I7"] = "SPI"
            port["J7"] = "CLK_ONLY"
            book.save(template)
            book.close()
            seen: list[str] = []

            def fake_ask(messages: list[dict[str, str]]) -> str:
                seen.append(messages[-1]["content"])
                return (
                    '[{"symbol":"P00.0","level":"conflict","reason":"手册mux无CAN13_RXDC接收能力，仅支持CAN13_RXDC"},'
                    '{"symbol":"P00.0","level":"conflict","reason":"手册mux仅列GTM输入，无SPI主发能力"},'
                    '{"symbol":"P00.0","level":"conflict","reason":"手册mux无输出能力"},'
                    '{"symbol":"P00.1","level":"conflict","reason":"手册mux无SPI主发能力，仅有GTM输入"}]'
                )

            padding = "；".join(f"GTM_TIM0_IN{i} Mux input channel {i}" for i in range(40))
            res = write_hsi_workbook(
                template,
                dest,
                mcu="TC499",
                package="BGA436",
                pins=(
                    _pin(
                        "P00.0",
                        "N7",
                        "General-purpose input",
                        padding + "；QSPI3_SLSO6 Master slave select output；CAN13_RXDC CAN receive input node 3",
                    ),
                    _pin("P00.1", "N5", "General-purpose input", "GTM_TIM0_IN4 Mux input channel 4"),
                ),
                ask=fake_ask,
            )
            self.assertEqual(res.conflicts, 1)
            self.assertTrue(seen)
            self.assertIn("QSPI3_SLSO6", seen[0])
            out = load_workbook(dest, data_only=True)
            try:
                sheet = out[SHEET_PORT]
                denied = str(sheet.cell(5, COL_MARK).value or "")
                self.assertNotIn("【工程质检】", denied)
                self.assertNotIn("无CAN13_RXDC", denied)
                self.assertNotIn("无输出能力", denied)
                self.assertEqual(sheet.cell(5, COL_STATUS).value, STATUS_DRAFT)
                kept = str(sheet.cell(6, COL_MARK).value or "")
                self.assertIn("【工程质检】", kept)
                self.assertIn("无SPI主发", kept)
                self.assertEqual(sheet.cell(6, COL_STATUS).value, STATUS_CONFLICT)
            finally:
                out.close()

    def test_llm_pin_qa_progress_keeps_moving_when_a_batch_fails(self) -> None:
        from electrical_krow.hsi_qa import run_llm_pin_qa

        pins = [_pin(f"P{i}.0", "A1", "in") for i in range(21)]
        candidates = [(pin, "Input", "GPIO", ("N",), []) for pin in pins]
        seen: list[tuple[int, int]] = []
        calls = {"n": 0}

        def ask(messages: list[dict[str, str]]) -> str:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("down")
            return "[]"

        run_llm_pin_qa(candidates, ask, on_progress=lambda done, total: seen.append((done, total)))
        self.assertEqual(seen, [(0, 21), (20, 21), (21, 21)])

    def test_build_hsi_progress_stages_stay_in_order(self) -> None:
        from unittest.mock import patch

        events: list[tuple[int, str]] = []

        def on_progress(percent: int, stage: str, detail: str = "") -> None:
            events.append((percent, stage))

        def fake_read(path: Path, on_progress=None):
            if on_progress is not None:
                on_progress(0, 2)
                on_progress(2, 2)
            return [(1, "x"), (2, "y")]

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            template = root / "template.xlsx"
            dest = root / "out.xlsx"
            _template(template)
            with (
                patch("electrical_krow.hsi_book.read_pdf_pages", side_effect=fake_read),
                patch("electrical_krow.hsi_book.parse_pin_pages", return_value=("BGA516",)),
                patch("electrical_krow.hsi_book.parse_pins", return_value=(_pin("P00.0", "A1", "GPIO"),)),
            ):
                build_hsi(template, root / "tc38x.pdf", dest, package="BGA516", on_progress=on_progress)
        stages = [stage for _, stage in events]
        percents = [percent for percent, _ in events]
        self.assertEqual(percents, sorted(percents))
        self.assertLess(stages.index("read"), stages.index("pins"))
        self.assertLess(stages.index("pins"), stages.index("check"))
        self.assertLess(stages.index("check"), stages.index("write"))
        self.assertEqual(stages[-1], "write")
        self.assertLess(percents[-1], 100)

    def test_history_row_height_follows_the_new_sentence(self) -> None:
        from electrical_krow.hsi_book import _write_history

        book = load_workbook(_GEELY_TEMPLATE)
        try:
            sheet = book[SHEET_HISTORY]
            self.assertGreater(sheet.row_dimensions[12].height, 300)
            _write_history(
                sheet,
                "20261023",
                [
                    ("AN15", "AN15：球号由W8变更为T6"),
                    ("AN16", "AN16：球号由AB8变更为W5"),
                ],
            )
            self.assertNotIn(2, sheet.row_dimensions)
            self.assertNotIn(3, sheet.row_dimensions)
            self.assertNotIn(12, sheet.row_dimensions)
            self.assertEqual(sheet.cell(2, 3).value, "AN15：球号由W8变更为T6")
            long = "AN0：" + "；".join(f"复用由通道{i}变更为通道{i + 1}" for i in range(8))
            _write_history(sheet, "20261023", [("AN0", long)])
            height = sheet.row_dimensions[2].height
            self.assertGreater(height, 30)
            self.assertLess(height, 80)
        finally:
            book.close()

    def test_p1_pwm_must_share_one_atom_and_complementary_bridge(self) -> None:
        from electrical_krow.hsi_qa import allocation_notes

        book = Workbook()
        sheet = book.active
        sheet.title = "2_Port Assignment"
        for index, (symbol, name) in enumerate(
            (("P02.1", "PWM_AH_P1"), ("P02.4", "PWM_AL_P1")),
            start=5,
        ):
            sheet.cell(index, 2, symbol)
            sheet.cell(index, 10, name)
        bad = allocation_notes(
            book,
            (
                _pin("P02.1", "F5", "PWM", "GTM0_ATOM1_CH1 CDTM1 DTM4_1", direction="Output"),
                _pin("P02.4", "G4", "PWM", "GTM0_ATOM2_CH3 CDTM1 DTM4_2", direction="Output"),
            ),
        )
        text = " ".join(bad["P02.1"])
        self.assertIn("同一个 ATOM", text)
        self.assertIn("同一 ATOM 通道", text)
        self.assertIn("互补", text)
        good = allocation_notes(
            book,
            (
                _pin("P02.1", "F5", "PWM", "GTM0_ATOM1_CH1→CDTM1 DTM4_1", direction="Output"),
                _pin("P02.4", "G4", "PWM", "GTM0_ATOM1_CH1→CDTM1 DTM4_1N", direction="Output"),
            ),
        )
        self.assertEqual(good, {})
        silent = allocation_notes(
            book,
            (
                _pin("P02.1", "F5", "PWM", "GTM_TOUT17", direction="Output"),
                _pin("P02.4", "G4", "PWM", "GTM_TOUT18", direction="Output"),
            ),
        )
        self.assertEqual(silent, {})

    def test_phase_currents_must_share_a_channel_across_groups(self) -> None:
        from electrical_krow.hsi_book import DEFAULT_HSI_TEMPLATE
        from electrical_krow.hsi_qa import allocation_notes

        real = load_workbook(DEFAULT_HSI_TEMPLATE, data_only=True)
        try:
            notes = allocation_notes(real, ())
        finally:
            real.close()
        self.assertFalse(any("三相电流" in item for items in notes.values() for item in items))

        book = Workbook()
        sheet = book.active
        sheet.title = "3_ADC Table"
        rows = (
            ("Gr2", "Ch1", "P00.11", "IA_S/M_P1"),
            (None, "Ch2", "AN29", "IB_S/M_P1"),
            ("Gr2", "Ch1", "P31.1", "IC_S/M_P1"),
        )
        for index, (group, channel, symbol, signal) in enumerate(rows, start=5):
            sheet.cell(index, 2, group)
            sheet.cell(index, 3, channel)
            sheet.cell(index, 5, symbol)
            sheet.cell(index, 7, signal)
            sheet.cell(index, 8, "P1三相电流检测")
        flagged = allocation_notes(book, ())
        text = " ".join(flagged["P00.11"])
        self.assertIn("同一 channel", text)
        self.assertIn("不同 group", text)

    def test_gm_pwm_is_read_from_the_pin_definition_column(self) -> None:
        from electrical_krow.hsi_qa import allocation_notes

        book = Workbook()
        sheet = book.active
        sheet.title = "2_Port Assignment "
        sheet.cell(3, 9, "Direction")
        sheet.cell(3, 10, "Function")
        sheet.cell(3, 12, "Pin Definition")
        sheet.cell(4, 2, "P02.1")
        sheet.cell(4, 12, "PWM_M_AH_GM")
        sheet.cell(5, 2, "P02.4")
        sheet.cell(5, 12, "PWM_M_AL_GM")
        bad = allocation_notes(
            book,
            (
                _pin("P02.1", "F5", "PWM", "GTM0_ATOM1_CH1 CDTM1 DTM4_1", direction="Output"),
                _pin("P02.4", "G4", "PWM", "GTM0_ATOM2_CH3 CDTM1 DTM4_2", direction="Output"),
            ),
        )
        self.assertIn("同一个 ATOM", " ".join(bad["P02.1"]))

    def test_dhte_adc_header_reads_symbol_beside_signal_name(self) -> None:
        from electrical_krow.hsi_qa import allocation_notes

        book = Workbook()
        sheet = book.active
        sheet.title = "3_ADC Table"
        sheet.cell(4, 2, "Gr")
        sheet.cell(4, 3, "channel")
        sheet.cell(4, 6, "Signal name")
        rows = (
            ("Gr0", "Ch0", "AN0", "IA_S/M_TM"),
            ("Gr0", "Ch1", "AN4", "IB_S/M_TM"),
            ("Gr1", "Ch0", "AN8", "IC_S/M_TM"),
        )
        for index, (group, channel, symbol, signal) in enumerate(rows, start=5):
            sheet.cell(index, 2, group)
            sheet.cell(index, 3, channel)
            sheet.cell(index, 4, symbol)
            sheet.cell(index, 6, signal)
            sheet.cell(index, 7, "TM三相电流检测")
        sheet.cell(8, 2, "Gr5")
        sheet.cell(8, 3, "Ch0")
        sheet.cell(8, 4, "AN5")
        sheet.cell(8, 6, "IA_S/M_TMBU")
        sheet.cell(8, 7, "TM备份电流")
        flagged = allocation_notes(book, ())
        text = " ".join(flagged["AN0"])
        self.assertIn("同一 channel", text)
        self.assertIn("TM", text)
        self.assertNotIn("AN5", flagged)

    def test_ball_and_symbol_follow_the_column_headers(self) -> None:
        from electrical_krow.hsi_book import _PortRow, _write_ports

        book = Workbook()
        port = book.active
        port.title = "2_Port Assignment "
        port.cell(3, 2, r"BGA436\Ball")
        port.cell(3, 3, "Pin_Symbol")
        port.cell(3, 9, "Direction")
        port.cell(3, 10, "Function")
        port.cell(2, 12, "Superevo pin Definition")
        port.cell(3, 12, "Pin Definition")
        row = _PortRow("P00.0", "M6", "", "", "", "", "Input", "", "", "", (), ())
        _write_ports(
            port,
            "TC499",
            "BGA436",
            [(row, STATUS_DRAFT, "")],
            (_pin("P00.0", "M6", "Port", direction="Input"),),
            {},
        )
        self.assertEqual(port.cell(3, 2).value, r"BGA436\Ball")
        self.assertEqual(port.cell(3, 3).value, "Pin_Symbol")
        self.assertEqual(port.cell(4, 2).value, "M6")
        self.assertEqual(port.cell(4, 3).value, "P00.0")
        self.assertIsNone(port.cell(2, 12).value)
        self.assertEqual(port.cell(3, 12).value, "Pin Definition")
        port.cell(1, 1, "TC499 Port Assignment [Main Table]")
        port.cell(2, 2, "MCU_TC499")
        port.cell(3, 2, r"BGA436\Ball")
        _write_ports(
            port,
            "TC38x",
            "BGA516",
            [(row, STATUS_DRAFT, "")],
            (_pin("P00.0", "M6", "Port", direction="Input"),),
            {},
        )
        self.assertEqual(port.cell(1, 1).value, "TC38x Port Assignment [Main Table]")
        self.assertEqual(port.cell(2, 2).value, "MCU_TC38x")
        self.assertEqual(port.cell(3, 2).value, r"BGA516\Ball")
        self.assertEqual(port.cell(4, 2).value, "M6")
        self.assertEqual(port.cell(4, 3).value, "P00.0")
        adc = book.create_sheet("3_ADC Table")
        adc.cell(2, 2, "MCU_TC499")
        from electrical_krow.hsi_book import _stamp_adc_mcu

        _stamp_adc_mcu(book, "TC38x")
        self.assertEqual(adc.cell(2, 2).value, "MCU_TC38x")

    def test_function_column_uses_template_category(self) -> None:
        from electrical_krow.hsi_book import _PortRow, _template_function, _write_ports

        analog = _PortRow("AN0", "W13", "", "", "", "", "Input", "Analog", "", "", ("IA",), ())
        pwm = _PortRow("P02.1", "F5", "", "", "", "", "Output", "PWM", "", "", ("PWM",), ())
        split = [
            _PortRow("P00.0", "M6", "", "", "", "", "Input", "PWM", "", "", ("A",), ()),
            _PortRow("P00.0", "M6", "", "", "", "", "Input", "Digital", "", "", ("B",), ()),
        ]
        self.assertEqual(_template_function([analog]), "Analog")
        self.assertEqual(_template_function([pwm]), "PWM")
        self.assertEqual(_template_function(split), "")
        book = Workbook()
        port = book.active
        port.title = "2_Port Assignment "
        port.cell(3, 2, r"BGA436\Ball")
        port.cell(3, 3, "Pin_Symbol")
        port.cell(3, 9, "Direction")
        port.cell(3, 10, "Function")
        drafted = _PortRow("AN0", "W13", "", "", "", "", "Input", "Analog Input 0", "", "", ("IA",), ())
        _write_ports(
            port,
            "TC38x",
            "BGA516",
            [(drafted, STATUS_DRAFT, "")],
            (_pin("AN0", "W13", "Analog Input 0", "ADC_TMADC2CH0", direction="Input"),),
            {},
            {"AN0": "Analog"},
        )
        self.assertEqual(port.cell(4, 9).value, "Input")
        self.assertEqual(port.cell(4, 10).value, "Analog")

    def test_dhte400_keeps_atom_port_name_cover_and_history(self) -> None:
        from electrical_krow.hsi_book import DEFAULT_HSI_TEMPLATE, _port_rows

        book = load_workbook(DEFAULT_HSI_TEMPLATE, data_only=True)
        try:
            rows = {row.symbol: row for row in _port_rows(book)}
        finally:
            book.close()
        an0 = rows["AN0"]
        self.assertEqual(an0.ball, "W13")
        self.assertEqual(an0.direction, "Input")
        self.assertEqual(an0.function, "Analog")
        self.assertEqual(an0.project[0], "IA_S/M_TM")
        pwm = rows["P02.1"]
        self.assertEqual(pwm.project[0], "PWM_M_AH_GM")
        self.assertEqual(pwm.direction, "Output")
        self.assertEqual(pwm.function, "PWM")
        self.assertIn("ATOM1", str(pwm.kept[0]))

        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "out.xlsx"
            write_hsi_workbook(
                DEFAULT_HSI_TEMPLATE,
                dest,
                mcu="TC499",
                package="BGA436",
                pins=(
                    _pin("AN0", "W13", "General-purpose input", direction="Input"),
                    _pin("P02.1", "F5", "PWM", "GTM0_ATOM1_CH1 CDTM1 DTM4_1", direction="Output"),
                ),
            )
            out = load_workbook(dest, data_only=True)
            try:
                self.assertIn("0_硬件版本识别", out.sheetnames)
                self.assertIn("26_PSS", out.sheetnames)
                self.assertTrue(any(name.strip().endswith("SPI总线") for name in out.sheetnames))
                cover = out["Cover"]
                self.assertEqual(cover.cell(2, 4).value, "殷桂来")
                self.assertIn("原理图", str(cover.cell(4, 5).value))
                history = out["1_Chang History"]
                self.assertEqual(history.cell(5, 2).value, "v1.3")
                self.assertEqual(history.max_row, 5)
                port = out[[name for name in out.sheetnames if name.startswith("2_Port")][0]]
                self.assertEqual(port.cell(3, 9).value, "Direction")
                self.assertEqual(port.cell(3, 12).value, "Pin Definition")
                located = {
                    port.cell(row, 3).value: row
                    for row in range(4, 8)
                    if port.cell(row, 3).value
                }
                analog = located["AN0"]
                self.assertEqual(port.cell(analog, 2).value, "W13")
                self.assertEqual(port.cell(analog, 3).value, "AN0")
                mark = str(port.cell(analog, COL_MARK).value)
                self.assertEqual(port.cell(analog, 9).value, "Input")
                self.assertEqual(port.cell(analog, 10).value, "Analog")
                self.assertEqual(port.cell(analog, 12).value, "IA_S/M_TM")
                self.assertIn("分配待人工确认", mark)
                self.assertNotIn("模板有端口名 IA_S/M_TM", mark)
                drive = located["P02.1"]
                self.assertEqual(port.cell(drive, 2).value, "F5")
                self.assertEqual(port.cell(drive, 3).value, "P02.1")
                self.assertIsNone(port.cell(drive, 7).value)
                self.assertIsNone(port.cell(drive, 8).value)
                self.assertEqual(port.cell(drive, 9).value, "Output")
                self.assertEqual(port.cell(drive, 10).value, "PWM")
                self.assertIsNone(port.cell(drive, 11).value)
                self.assertEqual(port.cell(drive, 12).value, "PWM_M_AH_GM")
                self.assertTrue(port.column_dimensions["K"].hidden)
                self.assertIn("ATOM1", str(port.cell(drive, 19).value))
                self.assertIn("分配待人工确认", str(port.cell(drive, COL_MARK).value))
                self.assertNotIn("模板有端口名 PWM_M_AH_GM", str(port.cell(drive, COL_MARK).value))
                adc = out["3_ADC Table"]
                self.assertIn("Pin Function", str(adc.cell(4, 7).value))
                self.assertEqual(adc.cell(4, 4).value, "PIN")
                self.assertEqual(adc.cell(5, 5).value, "W13")
                self.assertIsNone(adc.cell(5, 6).value)
                self.assertIsNone(adc.cell(6, 4).value)
                adc_pin = adc.cell(5, 4).hyperlink
                self.assertIsNotNone(adc_pin)
                self.assertIn("PORT", adc_pin.location)
                analog_link = port.cell(analog, 3).hyperlink
                self.assertIsNotNone(analog_link)
                self.assertIn("ADC", analog_link.location)
                self.assertEqual(port.cell(analog, 12).hyperlink.location, analog_link.location)
                self.assertEqual(port.cell(analog, 12).hyperlink.tooltip, f"第5行 {port.cell(analog, 12).value}")
                self.assertIsNone(port.cell(analog, 13).hyperlink)
                spi = out[[name for name in out.sheetnames if "SPI" in name][0]]
                self.assertEqual(spi.cell(3, 2).value, "PIN")
                self.assertIsNone(spi.cell(4, 2).value)
                self.assertIsNone(spi.cell(4, 7).value)
                dead = out["7_Dead Time"]
                self.assertEqual(str(dead.cell(3, 1).value).strip(), "Version")
                self.assertEqual(dead.cell(7, 9).value, "死区时间")
                self.assertIsNone(dead.cell(4, 1).value)
                self.assertIsNone(dead.cell(7, 10).value)
                self.assertIsNone(out["8_LPS_SIG"].cell(3, 2).value)
                self.assertEqual(out["8_LPS_SIG"].cell(2, 2).value, "Signal Name")
                self.assertIsNone(out["6_CAN"].cell(1, 3).value)
                self.assertIsNone(out["10_Gate Signal Logic"].cell(5, 1).value)
                self.assertEqual(out["10_Gate Signal Logic"].cell(8, 1).value, "信号")
                self.assertIsNone(out["11_Eddy Sense&Diag"].cell(4, 2).value)
                self.assertEqual(out["11_Eddy Sense&Diag"].cell(6, 2).value, "输入Vin")
                self.assertIsNone(out["22_3041寄存器配置表"].cell(8, 2).value)
                self.assertEqual(out["22_3041寄存器配置表"].cell(7, 2).value, "Name")
                self.assertIsNone(out["21_硬件功能安全"].cell(2, 2).value)
                hw = out["0_硬件版本识别"]
                self.assertEqual(hw.cell(2, 1).value, "配置项")
                self.assertEqual(hw.cell(2, 3).value, "GPIO配置")
                self.assertIsNone(hw.cell(3, 1).value)
                self.assertIsNone(hw.cell(3, 3).value)
                self.assertIsNone(hw.cell(4, 2).value)
                self.assertIsNone(hw.cell(8, 2).value)
                spi = out[[name for name in out.sheetnames if "SPI" in name][0]]
                self.assertFalse(any(str(merged) == "G4:G8" for merged in spi.merged_cells.ranges))
                self.assertIsNone(spi.cell(4, 7).border.left)
                self.assertIsNotNone(spi.cell(3, 2).border.left.style)
                pmic = out["5_PMIC-TLF4D985"]
                self.assertFalse(any(str(merged) == "B3:B6" for merged in pmic.merged_cells.ranges))
                self.assertIsNotNone(pmic.cell(2, 2).border.left.style)
                self.assertFalse(any(str(merged) == "C2:F28" for merged in out["6_CAN"].merged_cells.ranges))
                self.assertIsNone(out["13_HVDC Overvoltage & Diag"].cell(4, 1).value)
                self.assertIn("采样电路", str(out["13_HVDC Overvoltage & Diag"].cell(1, 1).value))
                self.assertIsNone(out["15_SiC Temp"].cell(4, 2).value)
                self.assertIn("IGBT", str(out["15_SiC Temp"].cell(3, 2).value))
                self.assertIsNone(out["19_单片机温度"].cell(4, 2).value)
                self.assertIn("MCU_OilTemp", str(out["17_变速器油温"].cell(1, 1).value))
                self.assertFalse(any(adc.cell(row, 7).value for row in range(5, (adc.max_row or 4) + 1)))
                self.assertFalse(any(adc.cell(row, 8).value for row in range(5, (adc.max_row or 4) + 1)))
                self.assertIn("18_热泵温度传感器", out.sheetnames)
                self.assertIsNone(out["18_热泵温度传感器"].cell(147, 3).value)
                self.assertEqual(out["17_变速器油温"]._images, [])
                self.assertEqual(out["18_热泵温度传感器"]._images, [])
                self.assertEqual(list(out["22_3041寄存器配置表"].conditional_formatting), [])
                with zipfile.ZipFile(dest) as package:
                    self.assertFalse(any(name.startswith("xl/media/") for name in package.namelist()))
                self.assertTrue(adc.column_dimensions["Z"].hidden)
                self.assertTrue(adc.column_dimensions["AD"].hidden)
                self.assertFalse(adc.column_dimensions["AA"].hidden)
            finally:
                out.close()

    def test_adc_drops_template_circuit_constants(self) -> None:
        from electrical_krow.hsi_book import _fill_adc_from_manual

        book = Workbook()
        adc = book.active
        adc.title = "3_ADC Table"
        adc.cell(4, 3, "channel")
        adc.cell(4, 5, "Ball#")
        adc.cell(4, 27, "C1(nF)")
        adc.cell(4, 28, "R2 (kΩ)")
        adc.cell(4, 29, "C2(nF)")
        adc.cell(4, 31, "τ(us)")
        adc.cell(5, 27, 3.3)
        adc.cell(5, 28, 0.1)
        adc.cell(5, 29, 0.22)
        adc.cell(5, 31, "1. 电路滤波延迟4us； 2. 霍尔芯片延迟：3us;")
        adc.cell(5, 27).border = Border(right=Side(style="thin"), bottom=Side(style="thin"))
        adc.cell(7, 31, "=Z7*AA7")
        _fill_adc_from_manual(book, (_pin("AN0", "W13", "Analog input", "ADC_TMADC2CH0"),))
        self.assertEqual(adc.cell(4, 27).value, "C1(nF)")
        self.assertEqual(adc.cell(4, 31).value, "τ(us)")
        self.assertIsNone(adc.cell(5, 27).value)
        self.assertIsNone(adc.cell(5, 27).border.right)
        self.assertIsNone(adc.cell(5, 28).value)
        self.assertIsNone(adc.cell(5, 29).value)
        self.assertIsNone(adc.cell(5, 31).value)
        self.assertIsNone(adc.cell(7, 31).value)
        self.assertEqual(adc.cell(5, 5).value, "W13")

    def test_adc_drops_template_group_allocation(self) -> None:
        from electrical_krow.hsi_book import _fill_adc_from_manual

        book = Workbook()
        adc = book.active
        adc.title = "3_ADC Table"
        adc.cell(4, 2, "Gr")
        adc.cell(4, 3, "channel")
        adc.cell(4, 5, "Ball#")
        adc.cell(4, 6, "Signal name")
        adc.cell(5, 2, "Gr0")
        adc.cell(5, 3, "Ch0")
        adc.cell(5, 6, "IA_S/M_TM")
        adc.cell(129, 1, "Group")
        adc.cell(129, 2, "CH0")
        adc.cell(130, 1, "Gr0")
        adc.cell(130, 2, "IA_S/M_TM")
        adc.cell(140, 2, "GM current sense")
        adc.cell(142, 4, "不可用通道，已被其它PIN占用此通道")
        _fill_adc_from_manual(book, (_pin("AN0", "W13", "Analog input", "ADC_TMADC2CH0"),))
        self.assertEqual(adc.cell(4, 2).value, "Gr")
        self.assertEqual(adc.cell(4, 3).value, "channel")
        self.assertEqual(adc.cell(4, 6).value, "Signal name")
        self.assertEqual(adc.cell(5, 2).value, "TMADC2")
        self.assertIn("ADC_TMADC2CH0", str(adc.cell(5, 3).value))
        self.assertIsNone(adc.cell(5, 6).value)
        self.assertIsNone(adc.cell(129, 1).value)
        self.assertIsNone(adc.cell(129, 2).value)
        self.assertIsNone(adc.cell(130, 1).value)
        self.assertIsNone(adc.cell(130, 2).value)
        self.assertIsNone(adc.cell(140, 2).value)
        self.assertIsNone(adc.cell(142, 4).value)
        self.assertEqual(adc.cell(5, 5).value, "W13")

    def test_adc_group_stays_empty_when_converters_differ(self) -> None:
        from electrical_krow.hsi_book import _fill_adc_from_manual

        book = Workbook()
        adc = book.active
        adc.title = "3_ADC Table"
        adc.cell(4, 2, "Gr")
        adc.cell(4, 3, "channel")
        adc.cell(4, 5, "Ball#")
        _fill_adc_from_manual(
            book,
            (
                _pin("AN0", "W13", "Analog input", "ADC_TMADC2CH11"),
                _pin("AN1", "W12", "Analog input", "ADC_TMADC2CH10\nADC_DSADC5PA"),
                _pin("P00.1", "M7", "Analog input", "EVADC_G9CH11\nEDSADC_EDS5NA"),
                _pin("P00.2", "N6", "Analog input", "EVADC_G10CH0\nEVADC_G0CH4"),
                _pin("AN8", "AA18", "Analog input", "EVADC_G10CH8"),
            ),
        )
        by_ball = {adc.cell(row, 5).value: row for row in range(5, 10)}
        self.assertEqual([adc.cell(row, 5).value for row in range(5, 10)], ["M7", "AA18", "W12", "W13", "N6"])
        self.assertEqual(adc.cell(by_ball["W12"], 2).value, "TMADC2")
        self.assertIsNone(adc.cell(by_ball["W13"], 2).value)
        self.assertIn("ADC_DSADC5PA", str(adc.cell(by_ball["W12"], 3).value))
        self.assertEqual(adc.cell(by_ball["M7"], 2).value, "G9")
        self.assertEqual(adc.cell(by_ball["AA18"], 2).value, "G10")
        self.assertIsNone(adc.cell(by_ball["N6"], 2).value)
        merged = {str(item) for item in adc.merged_cells.ranges}
        self.assertIn("B7:B8", merged)
        self.assertEqual(adc.cell(by_ball["W12"], 2).fill.fgColor.rgb, "00BDD7EE")
        self.assertEqual(adc.cell(by_ball["M7"], 2).fill.fgColor.rgb, "00BDD7EE")
        self.assertEqual(adc.cell(by_ball["W12"], 2).alignment.horizontal, "center")
        self.assertEqual(adc.cell(by_ball["M7"], 2).border.bottom.style, "thin")
        self.assertEqual(adc.cell(by_ball["W12"], 2).border.top.style, "thin")
        self.assertEqual(adc.cell(by_ball["W13"], 2).border.bottom.style, "thin")
        self.assertIsNone(adc.cell(by_ball["M7"], 3).fill.patternType)
        self.assertIsNone(adc.cell(by_ball["N6"], 2).fill.patternType)

    def test_adc_row_height_follows_channel_lines(self) -> None:
        from electrical_krow.hsi_book import _fill_adc_from_manual, _link_detail_sheets

        book = Workbook()
        adc = book.active
        adc.title = "3_ADC Table"
        adc.cell(4, 3, "channel")
        adc.cell(4, 5, "Ball#")
        adc.cell(4, 6, "Signal name")
        adc.row_dimensions[5].height = 52
        adc.row_dimensions[6].height = 14.5
        adc.row_dimensions[20].height = 80
        adc.column_dimensions["F"].width = 18
        _fill_adc_from_manual(
            book,
            (
                _pin("AN0", "W13", "Analog input", "ADC_TMADC2CH0 Analog input"),
                _pin(
                    "AN1",
                    "W12",
                    "Analog input",
                    "ADC_TMADC2CH1 Analog\nADC_DSADC1NA Analog\nADC_FCC1 Analog",
                ),
            ),
        )
        one = adc.row_dimensions[5].height
        three = adc.row_dimensions[6].height
        self.assertGreater(one, 18)
        self.assertLess(one, 30)
        self.assertGreater(three, one)
        self.assertLess(three, 70)
        self.assertNotIn(20, adc.row_dimensions)
        channel = adc.cell(6, 3)
        self.assertEqual(channel.alignment.horizontal, "left")
        self.assertEqual(channel.alignment.vertical, "center")
        self.assertTrue(channel.alignment.wrap_text)
        self.assertEqual(adc.cell(5, 4).alignment.vertical, "center")
        port = book.create_sheet("2_Port Assignment ")
        port.cell(3, 9, "Direction")
        port.cell(3, 10, "Function")
        port.cell(3, 12, "Pin Definition")
        port.cell(4, 2, "AN0")
        port.cell(4, 12, "NC(只能配置成DSADC7，但已被占用)")
        _link_detail_sheets(book)
        self.assertGreater(adc.row_dimensions[5].height, one)
        self.assertTrue(adc.cell(5, 6).alignment.wrap_text)

    def test_header_band_drops_template_values_on_other_sheets(self) -> None:
        from electrical_krow.hsi_book import DEFAULT_HSI_TEMPLATE, _strip_header_examples

        book = load_workbook(DEFAULT_HSI_TEMPLATE)
        try:
            for name in (
                "16_EM Temp",
                "18_热泵温度传感器",
                "25_锁切一体控制",
                "7_Dead Time",
                "8_LPS_SIG",
                "9_ISS",
                "17_变速器油温",
            ):
                _strip_header_examples(book[name])
            em = book["16_EM Temp"]
            self.assertEqual(em.cell(2, 2).value, "Motor")
            self.assertIsNone(em.cell(4, 4).value)
            self.assertIsNone(em.cell(7, 3).value)
            heat = book["18_热泵温度传感器"]
            self.assertIn("热泵水温", str(heat.cell(2, 1).value))
            self.assertIsNone(heat.cell(1, 18).value)
            self.assertIn("Signal", str(heat.cell(3, 21).value))
            self.assertIsNone(heat.cell(4, 38).value)
            self.assertIsNone(heat.cell(5, 44).value)
            self.assertIsNone(heat.cell(8, 1).value)
            lock = book["25_锁切一体控制"]
            self.assertEqual(lock.cell(2, 25).value, "Remarks")
            self.assertIsNone(lock.cell(3, 25).value)
            self.assertIsNone(lock.cell(6, 25).value)
            dead = book["7_Dead Time"]
            self.assertEqual(dead.cell(7, 9).value, "死区时间")
            self.assertEqual(dead.cell(7, 11).value, "μs")
            self.assertIsNone(dead.cell(7, 27).value)
            self.assertIsNone(book["8_LPS_SIG"].cell(6, 1).value)
            self.assertIsNone(book["8_LPS_SIG"].cell(7, 1).value)
            self.assertEqual(book["8_LPS_SIG"].cell(2, 2).value, "Signal Name")
            self.assertIsNone(book["9_ISS"].cell(8, 1).value)
            oil = book["17_变速器油温"]
            self.assertIn("MCU_OilTemp", str(oil.cell(1, 1).value))
            self.assertIsNone(oil.cell(5, 1).value)
            self.assertIsNone(oil.cell(6, 2).value)
        finally:
            book.close()

    def test_spi_rows_follow_manual_qspi_pins(self) -> None:
        from electrical_krow.hsi_book import _fill_spi_from_manual, _link_detail_sheets

        book = Workbook()
        book.active.title = "Cover"
        port = book.create_sheet("2_Port Assignment ")
        port.cell(3, 9, "Direction")
        port.cell(3, 10, "Function")
        port.cell(3, 12, "Pin Definition")
        port.cell(4, 2, "P00.8")
        port.cell(5, 2, "P00.1")
        spi = book.create_sheet("4-SPI总线")
        spi.cell(2, 1, "1. CAN模块 SPI总线")
        spi.cell(2, 7, "SPI CLK波特率配置需求")
        spi.cell(3, 2, "PIN")
        spi.cell(3, 3, "PIN Fuction")
        spi.cell(3, 4, "I/O")
        spi.cell(3, 5, "Net Name")
        spi.cell(3, 6, "Fuction Des")
        _fill_spi_from_manual(
            book,
            (
                _pin(
                    "P00.8",
                    "N7",
                    "SPI select",
                    "QSPI3_SLSO4 Master slave select output\nCAN10_TXD CAN transmit",
                    direction="Input/Output",
                ),
                _pin("P00.1", "K5", "CAN", "CAN10_RXDA CAN receive input", direction="Input"),
                _pin(
                    "P01.5",
                    "N6",
                    "SPI data",
                    "QSPI3_MRSTC Master SPI data input\nQSPI3_MRST Slave SPI data output",
                    direction="Input/Output",
                ),
            ),
        )
        _link_detail_sheets(book)
        self.assertIsNone(spi.cell(2, 1).value)
        self.assertEqual(spi.cell(2, 7).value, "SPI CLK波特率配置需求")
        self.assertEqual(spi.cell(4, 1).value, 1)
        self.assertEqual(spi.cell(4, 1).alignment.horizontal, "center")
        self.assertEqual(spi.cell(4, 3).value, "QSPI3_SLSO4")
        self.assertEqual(spi.cell(4, 4).value, "Output")
        self.assertEqual(spi.cell(5, 3).value, "QSPI3_MRSTC\nQSPI3_MRST")
        self.assertEqual(spi.cell(5, 4).value, "Input\nOutput")
        self.assertEqual(spi.cell(5, 2).value, "P01.5")
        self.assertIsNone(spi.cell(6, 2).value)
        self.assertIsNone(spi.cell(4, 5).value)
        self.assertIn("L4", str(spi.cell(4, 6).value))
        self.assertIsNone(spi.cell(4, 7).value)
        self.assertIn("SPI", port.cell(4, 2).hyperlink.location)
        self.assertIsNone(port.cell(5, 2).hyperlink)

    def test_can_rows_follow_manual_tx_rx(self) -> None:
        from electrical_krow.hsi_book import _fill_can_from_manual, _link_detail_sheets

        book = Workbook()
        book.active.title = "Cover"
        port = book.create_sheet("2_Port Assignment ")
        port.cell(3, 9, "Direction")
        port.cell(3, 10, "Function")
        port.cell(3, 12, "Pin Definition")
        port.cell(4, 2, "P14.0")
        port.cell(4, 12, "CANTX_M/T-DB")
        can = book.create_sheet("6_CAN")
        can.merge_cells("C2:F28")
        can.cell(1, 1, "1")
        can.cell(1, 2, "概要")
        can.cell(1, 3, "TLE9255W高速CAN")
        can.cell(2, 2, "框图")
        can.cell(39, 2, "P14.0")
        can.cell(39, 5, "CANTX_M/T-DB")
        can.cell(39, 6, "XCP CAN(调试)")
        _fill_can_from_manual(
            book,
            (
                _pin(
                    "P14.0",
                    "A1",
                    "CAN",
                    "CAN10_TXD CAN transmit output\nCAN10_RXDA CAN receive input",
                    direction="Input/Output",
                ),
                _pin(
                    "P14.1",
                    "A2",
                    "CAN",
                    "CAN10_RXDA CAN receive input",
                    direction="Input/Output",
                ),
                _pin("P00.8", "N7", "SPI", "QSPI3_SLSO4 Master slave select output", direction="Output"),
            ),
        )
        self.assertIsNone(can.cell(1, 2).value)
        self.assertIsNone(can.cell(1, 3).value)
        self.assertEqual(can.cell(1, 1).value, "CAN TXD/RXD")
        self.assertGreaterEqual(can.column_dimensions["C"].width, 18)
        self.assertTrue(any(str(merged) == "A1:F1" for merged in can.merged_cells.ranges))
        self.assertEqual(can.cell(2, 2).value, "PIN")
        self.assertEqual(can.cell(2, 3).value, "PIN Fuction")
        self.assertEqual(can.cell(2, 4).value, "I/O")
        self.assertEqual(can.cell(3, 1).value, 1)
        self.assertEqual(can.cell(3, 2).value, "P14.0")
        self.assertEqual(can.cell(3, 3).value, "CAN10_TXD\nCAN10_RXDA")
        self.assertEqual(can.cell(3, 4).value, "Output\nInput")
        self.assertIsNone(can.cell(3, 5).value)
        self.assertIsNone(can.cell(3, 6).value)
        self.assertEqual(can.cell(4, 2).value, "P14.1")
        self.assertEqual(can.cell(4, 3).value, "CAN10_RXDA")
        self.assertEqual(can.cell(4, 4).value, "Input")
        self.assertIsNone(can.cell(5, 2).value)
        self.assertFalse(any(str(merged) == "C2:F28" for merged in can.merged_cells.ranges))
        self.assertNotIn("XCP", " ".join(str(can.cell(row, col).value or "") for row in range(1, 6) for col in range(1, 7)))
        self.assertNotIn("动力CAN", " ".join(str(can.cell(row, col).value or "") for row in range(1, 6) for col in range(1, 7)))
        _link_detail_sheets(book)
        self.assertIn("B4", str(can.cell(3, 2).value))
        self.assertIn("L4", str(can.cell(3, 6).value))
        link = port.cell(4, 2).hyperlink
        self.assertIsNotNone(link)
        self.assertIn("6_CAN", book.defined_names[link.location].attr_text)

    def test_port_names_link_to_adc_and_spi(self) -> None:
        from electrical_krow.hsi_book import _hide_adc_spare_columns, _link_detail_sheets

        book = Workbook()
        book.active.title = "Cover"
        port = book.create_sheet("2_Port Assignment ")
        port.cell(3, 9, "Direction")
        port.cell(3, 10, "Function")
        port.cell(3, 11, "星驱原理图网络")
        port.cell(3, 12, "Pin Definition")
        port.cell(4, 2, "AN0")
        port.cell(4, 12, "IA_S/M_TM")
        port.cell(5, 2, "P00.8")
        port.cell(5, 11, "CSN3_M/T_SPI3")
        port.cell(5, 12, "QSPI3")
        adc = book.create_sheet("3_ADC Table")
        adc.cell(4, 6, "Signal name")
        adc.cell(4, 26, "R1 (kΩ)")
        adc.cell(4, 27, "C1(nF)")
        adc.cell(4, 30, "R3 (kΩ)")
        adc.cell(5, 6, "IA_S/M_TM")
        spi = book.create_sheet("4-SPI总线")
        spi.cell(3, 2, "PIN")
        spi.cell(3, 5, "Net Name")
        spi.cell(4, 2, "P00.8")
        spi.cell(4, 5, "CSN3_M/T_SPI3")
        _link_detail_sheets(book)
        _hide_adc_spare_columns(book)
        name_link = port.cell(4, 12).hyperlink
        pin_link = port.cell(5, 2).hyperlink
        net_link = port.cell(5, 11).hyperlink
        self.assertEqual(name_link.location, "HSI_ADC_5")
        self.assertEqual(name_link.tooltip, "第5行 IA_S/M_TM")
        self.assertFalse(name_link.target)
        self.assertIn("3_ADC Table", book.defined_names["HSI_ADC_5"].attr_text)
        self.assertIn("$5:$5", book.defined_names["HSI_ADC_5"].attr_text)
        self.assertEqual(pin_link.location, "HSI_SPI_4")
        self.assertEqual(pin_link.tooltip, "第4行 P00.8")
        self.assertEqual(port.cell(5, 12).value, "QSPI3")
        self.assertEqual(port.cell(5, 12).hyperlink.location, pin_link.location)
        self.assertEqual(port.cell(5, 12).hyperlink.tooltip, "第4行 QSPI3")
        self.assertIsNone(port.cell(5, 13).hyperlink)
        self.assertFalse(pin_link.target)
        self.assertEqual(net_link.location, "HSI_SPI_4")
        self.assertIn("$4:$4", book.defined_names["HSI_SPI_4"].attr_text)
        self.assertFalse(net_link.target)
        back = adc.cell(5, 6).hyperlink
        self.assertEqual(back.location, "HSI_PORT_4")
        self.assertEqual(back.tooltip, "第4行 IA_S/M_TM")
        self.assertIn("2_Port Assignment", book.defined_names["HSI_PORT_4"].attr_text)
        self.assertIn("$4:$4", book.defined_names["HSI_PORT_4"].attr_text)
        self.assertFalse(back.target)
        self.assertTrue(str(adc.cell(5, 6).value).startswith("="))
        self.assertIn("2_Port Assignment", str(adc.cell(5, 6).value))
        self.assertTrue(adc.column_dimensions["Z"].hidden)
        self.assertTrue(adc.column_dimensions["AD"].hidden)
        self.assertFalse(adc.column_dimensions["AA"].hidden)

    def test_one_port_name_links_every_matching_row(self) -> None:
        from electrical_krow.hsi_book import _link_detail_sheets

        book = Workbook()
        book.active.title = "Cover"
        port = book.create_sheet("2_Port Assignment ")
        port.cell(3, 9, "Direction")
        port.cell(3, 10, "Function")
        port.cell(3, 12, "Pin Definition")
        port.cell(4, 2, "AN0")
        port.cell(4, 12, "IA_S/M_TM")
        adc = book.create_sheet("3_ADC Table")
        adc.cell(4, 6, "Signal name")
        adc.cell(5, 6, "IA_S/M_TM")
        adc.cell(8, 6, "IA_S/M_TM")
        pmic = book.create_sheet("5_PMIC")
        pmic.cell(2, 3, "Signal name")
        pmic.cell(3, 3, "IA_S/M_TM")
        heat = book.create_sheet("18_热泵温度传感器")
        heat.cell(2, 3, "Signal name")
        heat.cell(147, 3, "IA_S/M_TM")
        _link_detail_sheets(book)
        name = port.cell(4, 12)
        self.assertEqual(name.value, "IA_S/M_TM")
        self.assertIn("跳转索引", name.hyperlink.location)
        self.assertEqual(port.cell(4, 2).value, "AN0")
        self.assertIsNone(port.cell(4, 2).hyperlink)
        self.assertIsNone(port.cell(5, 2).value)
        self.assertIsNone(port.cell(4, 25).value)
        self.assertEqual(list(port.data_validations.dataValidation), [])
        self.assertIn("跳转索引", book.sheetnames)
        index = book["跳转索引"]
        listed = {
            index.cell(row, 1).value: index.cell(row, 1).hyperlink.location
            for row in range(4, 12)
            if index.cell(row, 1).hyperlink is not None
        }
        self.assertEqual(listed["18_热泵温度传感器 第147行"], "HSI_S5_147")
        self.assertEqual(listed["5_PMIC 第3行"], "HSI_S4_3")
        self.assertTrue(any("IA_S/M_TM" in str(title) for title in listed))
        anchor = book.defined_names["HSI_ADC_5"].attr_text
        self.assertIn("3_ADC Table", anchor)
        self.assertIn("$5:$5", anchor)
        heat_anchor = book.defined_names["HSI_S5_147"].attr_text
        self.assertIn("18_热泵温度传感器", heat_anchor)
        self.assertIn("$147:$147", heat_anchor)
        self.assertFalse(str(heat_anchor).startswith("="))
        self.assertEqual(adc.cell(8, 6).hyperlink.location, "HSI_PORT_4")
        self.assertEqual(heat.cell(147, 3).hyperlink.location, "HSI_PORT_4")
        self.assertEqual(pmic.cell(3, 3).hyperlink.location, "HSI_PORT_4")
        self.assertIn("L4", str(adc.cell(8, 6).value))
        self.assertIn("L4", str(heat.cell(147, 3).value))
        self.assertIn("L4", str(pmic.cell(3, 3).value))

    def test_pin_definition_follows_symbol_when_name_has_no_row(self) -> None:
        from electrical_krow.hsi_book import _link_detail_sheets

        book = Workbook()
        book.active.title = "Cover"
        port = book.create_sheet("2_Port Assignment ")
        port.cell(3, 9, "Direction")
        port.cell(3, 10, "Function")
        port.cell(3, 12, "Pin Definition")
        port.cell(3, 13, "Pin Definition")
        port.cell(4, 2, "P00.8")
        port.cell(4, 12, "FLTB_M_H_GM")
        port.cell(4, 13, "GM驱动芯片故障")
        port.cell(5, 2, "P02.1")
        port.cell(5, 12, "DO_ASC_PRI_H_P1")
        port.cell(5, 13, "GM 门驱使能")
        adc = book.create_sheet("3_ADC Table")
        adc.cell(4, 4, "PIN")
        adc.cell(5, 4, "P02.1")
        spi = book.create_sheet("4-SPI总线")
        spi.cell(3, 2, "PIN")
        spi.cell(4, 2, "P00.8")
        spi.cell(5, 2, "P02.1")
        _link_detail_sheets(book)
        single = port.cell(4, 12)
        self.assertEqual(single.value, "FLTB_M_H_GM")
        self.assertEqual(single.hyperlink.location, port.cell(4, 2).hyperlink.location)
        self.assertEqual(single.hyperlink.location, "HSI_SPI_4")
        self.assertEqual(single.hyperlink.tooltip, "第4行 FLTB_M_H_GM")
        self.assertIsNone(port.cell(4, 13).hyperlink)
        many = port.cell(5, 12)
        self.assertEqual(many.value, "DO_ASC_PRI_H_P1")
        self.assertEqual(many.hyperlink.location, port.cell(5, 2).hyperlink.location)
        self.assertIn("跳转索引", many.hyperlink.location)
        self.assertIsNone(port.cell(5, 13).hyperlink)
        self.assertIsNone(port.cell(5, 14).value)
        index = book["跳转索引"]
        titles = [
            index.cell(row, 1).value
            for row in range(4, 12)
            if index.cell(row, 1).value and "处" in str(index.cell(row, 1).value)
        ]
        self.assertEqual(titles, ["P02.1（2 处）"])
        self.assertNotIn("跳转索引", single.hyperlink.location)

    def test_supply_pin_stays_on_the_sheet_and_is_hidden(self) -> None:
        from electrical_krow.hsi_book import DEFAULT_HSI_TEMPLATE, write_hsi_workbook

        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "out.xlsx"
            write_hsi_workbook(
                DEFAULT_HSI_TEMPLATE,
                dest,
                mcu="TC499",
                package="BGA436",
                pins=(
                    _pin("VDD", "A1", "Digital Core Power Supply"),
                    _pin("AN0", "W13", "Analog Input 0", direction="Input"),
                ),
            )
            out = load_workbook(dest)
            try:
                port = out[[name for name in out.sheetnames if name.startswith("2_Port")][0]]
                symbols = {port.cell(row, 3).value: row for row in range(4, port.max_row + 1)}
                self.assertIn("VDD", symbols)
                self.assertIn("AN0", symbols)
                self.assertTrue(port.row_dimensions[symbols["VDD"]].hidden)
                self.assertFalse(port.row_dimensions[symbols["AN0"]].hidden)
                self.assertIn("手册分类：电源", str(port.cell(symbols["VDD"], COL_MARK).value))
                self.assertIsNone(port.cell(symbols["VDD"], 10).value)
                self.assertEqual(port.cell(symbols["AN0"], 10).value, "Analog")
                self.assertIn("分配待人工确认", str(port.cell(symbols["AN0"], COL_MARK).value))
                self.assertNotIn("手册分类：ADC", str(port.cell(symbols["AN0"], COL_MARK).value))
                self.assertNotIn("三相电流", str(port.cell(symbols["AN0"], COL_MARK).value))
                adc = out["3_ADC Table"]
                self.assertEqual(adc.cell(4, 2).value, "Gr")
                self.assertIsNone(adc.cell(5, 2).value)
                self.assertIsNone(adc.cell(130, 2).value)
                self.assertIsNone(adc.cell(140, 2).value)
            finally:
                out.close()

    def test_other_vendor_pin_table_keeps_power_and_signal(self) -> None:
        page = """
Pin Assignment BGA337
A1 VDD I Core supply
B2 GPIO_0 I/O General-purpose input
"""
        pins = {pin.symbol: pin for pin in parse_pins([(3, page)], "BGA337")}
        self.assertEqual(set(pins), {"VDD", "GPIO_0"})
        self.assertEqual(pin_supply_kind(pins["VDD"].symbol), "电源")
        self.assertEqual(pin_class(pins["GPIO_0"]), "GPIO")

    def test_dedicated_symbols_get_a_manual_class(self) -> None:
        self.assertEqual(pin_class(_pin("NC1_A26", "A26", "Not connected")), "空脚")
        self.assertEqual(pin_class(_pin("XTAL1", "R23", "Crystal input")), "时钟")
        self.assertEqual(pin_class(_pin("PHY1_TXP", "E26", "Ethernet transmit")), "以太网")
        self.assertEqual(pin_class(_pin("TRST", "P22", "JTAG reset")), "调试")
        self.assertEqual(pin_class(_pin("PORST", "K20", "Power on reset")), "复位")
        self.assertEqual(pin_class(_pin("P00.8", "N7", "Port", "ADC_TMADC2CH6")), "ADC")
        self.assertEqual(pin_class(_pin("P02.1", "F5", "Port", "GTM_TOUT17")), "Timer")

    def test_renaming_port_updates_every_linked_name_and_symbol(self) -> None:
        from electrical_krow.hsi_book import _link_detail_sheets

        book = Workbook()
        book.active.title = "Cover"
        port = book.create_sheet("2_Port Assignment ")
        port.cell(3, 9, "Direction")
        port.cell(3, 10, "Function")
        port.cell(3, 12, "Pin Definition")
        port.cell(4, 2, "P00.8")
        port.cell(4, 12, "IA_S/M_TM")
        adc = book.create_sheet("3_ADC Table")
        adc.cell(4, 4, "PIN")
        adc.cell(4, 6, "Signal name")
        adc.cell(4, 24, "Signal name")
        adc.cell(5, 4, "P00.8")
        adc.cell(5, 6, "IA_S/M_TM")
        adc.cell(5, 24, "IA_S/M_TM")
        spi = book.create_sheet("4-SPI总线")
        spi.cell(3, 2, "PIN")
        spi.cell(3, 6, "Fuction Des")
        spi.cell(4, 2, "P00.8")
        spi.cell(4, 6, "IA_S/M_TM")
        _link_detail_sheets(book)
        for cell in (adc.cell(5, 6), adc.cell(5, 24), spi.cell(4, 6)):
            self.assertIn("L4", str(cell.value))
        for cell in (adc.cell(5, 4), spi.cell(4, 2)):
            self.assertIn("B4", str(cell.value))
            self.assertNotIn("80", str(cell.value))

    def test_schematic_writes_net_and_external_pull_for_review(self) -> None:
        from electrical_krow.hsi_book import STATUS_DRAFT, _apply_schematic

        edif = """(edif demo
          (library COMPONENT_LIB
            (cell DEMO (view NetlistView (contents
              (Instance R822A
                (Property Type (String "Res" ))
                (Property Value (String "68kΩ" ))
              )
              (Instance R100
                (Property Type (String "Res" ))
                (Property Value (String "100Ω" ))
              )
              (Instance R913A
                (Property Type (String "Res" ))
                (Property Value (String "10kΩ" ))
              )
              (Net (rename PWM_M_AH_GM "PWM_M/D_AH_GM")
                (Joined
                  (PortRef P02.1 (InstanceRef U1))
                  (PortRef &1 (InstanceRef R822A))
                  (PortRef &1 (InstanceRef R100))
                )
              )
              (Net GND
                (Joined
                  (PortRef &2 (InstanceRef R822A))
                )
              )
              (Net NetC808B_1
                (Joined
                  (PortRef &2 (InstanceRef R100))
                )
              )
              (Net (rename CSH_M_SPI_TM "CSH_M/D_SPI_TM")
                (Joined
                  (PortRef P33.13 (InstanceRef U1))
                  (PortRef &1 (InstanceRef R913A))
                )
              )
              (Net 5V_P_LAC
                (Joined
                  (PortRef &2 (InstanceRef R913A))
                )
              )
            )))
          )
        )
        """
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "board.edf"
            path.write_text(edif, encoding="utf-8")
            book = Workbook()
            book.active.title = "Cover"
            port = book.create_sheet("2_Port Assignment ")
            port.cell(2, 15, "电路外部硬件状态")
            port.cell(3, 9, "Direction")
            port.cell(3, 10, "Function")
            port.cell(3, 11, "星驱原理图网络")
            port.cell(3, 12, "Pin Definition")
            port.cell(4, 2, "P02.1")
            port.cell(4, 11, "DPO_DRV_UH_M1")
            port.cell(4, 12, "PWM_M_AH_GM")
            port.cell(4, 22, STATUS_DRAFT)
            port.cell(5, 2, "P33.13")
            port.cell(5, 12, "CSH_M_SPI_TM")
            port.cell(6, 2, "AN0")
            port.cell(6, 11, "AI_IU_CH1_M2")
            port.cell(6, 12, "IA_S/M_TM")
            updated = _apply_schematic(book, path)
            self.assertEqual(updated, 2)
            self.assertIsNone(port.cell(4, 11).value)
            self.assertEqual(port.cell(4, 12).value, "PWM_M/D_AH_GM")
            self.assertEqual(port.cell(4, 15).value, "下拉 68kΩ")
            self.assertNotIn("100", str(port.cell(4, 23).value))
            self.assertIn("R822A", str(port.cell(4, 23).value))
            self.assertIn("待人工复核", str(port.cell(4, 23).value))
            self.assertIn(STATUS_DRAFT, str(port.cell(4, 22).value))
            self.assertEqual(port.cell(5, 15).value, "上拉 10kΩ")
            self.assertIsNone(port.cell(6, 11).value)
            self.assertEqual(port.cell(6, 12).value, "IA_S/M_TM")
            self.assertIsNone(port.cell(6, 15).value)

    def test_revise_hsi_from_schematic_keeps_unmatched_rows(self) -> None:
        from electrical_krow.hsi_book import revise_hsi_from_schematic

        edif = """(edif demo
          (library COMPONENT_LIB (cell DEMO (view NetlistView (contents
            (Instance J402
              (Property Type (String "CON" ))
            )
            (Instance R822A
              (Property Type (String "Res" ))
              (Property Value (String "68kΩ" ))
            )
            (Net (rename PWM_M_AH_GM "PWM_M/D_AH_GM")
              (Joined
                (PortRef &20 (InstanceRef J402))
                (PortRef &1 (InstanceRef R822A))
              )
            )
            (Net GND
              (Joined
                (PortRef &2 (InstanceRef R822A))
              )
            )
          ))))
        )
        """
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            base = root / "base.xlsx"
            dest = root / "out.xlsx"
            book = Workbook()
            book.active.title = "Cover"
            port = book.create_sheet("2_Port Assignment ")
            port["B2"] = "MCU_TC499"
            port.cell(2, 15, "电路外部硬件状态")
            port.cell(3, 9, "Direction")
            port.cell(3, 10, "Function")
            port.cell(3, 11, "星驱原理图网络")
            port.cell(3, 12, "Pin Definition")
            port.cell(4, 2, "P02.1")
            port.cell(4, 11, "DPO_DRV_UH_M1")
            port.cell(4, 12, "PWM_M_AH_GM")
            port.cell(5, 2, "AN0")
            port.cell(5, 12, "IA_S/M_TM")
            port.cell(5, 11, "AI_IU_CH1_M2")
            book.save(base)
            book.close()
            schematic = root / "board.edf"
            schematic.write_text(edif, encoding="utf-8")
            result = revise_hsi_from_schematic(base, dest, schematic)
            self.assertEqual(result.schematic_updates, 1)
            out = load_workbook(dest)
            try:
                sheet = out["2_Port Assignment "]
                symbols = [sheet.cell(row, 2).value for row in range(4, 8)]
                self.assertIn("J402.20", symbols)
                self.assertNotIn("P02.1", symbols)
                self.assertNotIn("AN0", symbols)
                self.assertIsNone(sheet.cell(4, 11).value)
                self.assertEqual(sheet.cell(4, 12).value, "PWM_M/D_AH_GM")
                self.assertEqual(sheet.cell(4, 15).value, "下拉 68kΩ")
                self.assertIn("待人工复核", str(sheet.cell(4, 23).value))
                self.assertIn("R822A", str(sheet.cell(4, 23).value))
                self.assertNotIn("原理图网络", str(sheet.cell(4, 23).value))
                self.assertNotIn("P02.1", str(sheet.cell(4, 23).value))
            finally:
                out.close()

    def test_schematic_lists_unconnected_connector_pin_and_clears_template_pages(self) -> None:
        from electrical_krow.hsi_book import revise_hsi_from_schematic

        edif = """(edif demo
          (library COMPONENT_LIB
            (cell CON2 (view NetlistView (interface
              (port (rename &1 "1") (direction INOUT))
              (port (rename &2 "2") (direction INOUT))
            )))
            (cell DEMO (view NetlistView (contents
              (Instance J501
                (viewRef NetlistView (cellRef CON2))
                (Property Type (String "CON" ))
              )
              (Net SIG
                (Joined
                  (PortRef &2 (InstanceRef J501))
                )
              )
            )))
          )
        )
        """
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            base = root / "base.xlsx"
            dest = root / "out.xlsx"
            book = Workbook()
            cover = book.active
            cover.title = "Cover"
            cover.cell(1, 4, "修改人")
            cover.cell(2, 4, "殷桂来")
            cover.cell(1, 5, "需要修改内容")
            cover.cell(2, 5, "修改K和L列对应原理图的网络名")
            cover.cell(2, 3, "硬件版本识别")
            history = book.create_sheet("1_Chang History")
            history.cell(1, 1, "编号")
            history.cell(1, 2, "版本")
            history.cell(2, 2, "v1.3")
            history.cell(2, 4, "根据星驱原理图匹配")
            port = book.create_sheet("2_Port Assignment ")
            port.cell(2, 12, "Superevo pin Definition")
            port.cell(3, 12, "Pin Definition")
            port.cell(1, 1, "TC499 Port Assignment [Main Table]")
            port.cell(2, 2, "MCU_TC499")
            port.cell(3, 2, r"BGA436\Ball")
            port.cell(3, 9, "Direction")
            port.cell(3, 10, "Function")
            port.cell(3, 11, "星驱原理图网络")
            port.cell(3, 12, "Pin Definition")
            port.cell(3, 13, "Pin Definition")
            adc = book.create_sheet("3_ADC Table")
            adc.cell(2, 2, "MCU_TC499")
            for column, title in enumerate(("Pin", "Signal name", "Formula", "Min", "Max"), start=5):
                adc.cell(4, column, title)
            adc.cell(4, 6).fill = PatternFill(fill_type="solid", fgColor="FFD9E2F3")
            adc.cell(9, 6, "IA_S/M_TM")
            adc.cell(9, 6).fill = PatternFill(fill_type="solid", fgColor="FF92D050")
            adc.cell(9, 6).border = Border(left=Side(style="thin"))
            adc.cell(9, 8, "IT=(UT-2.5)/0.001511")
            adc.conditional_formatting.add(
                "F5:F20",
                FormulaRule(formula=["TRUE"], fill=PatternFill(fill_type="solid", fgColor="FFDEEBF7")),
            )
            adc.add_image(Image(BytesIO(_TINY_PNG)), "B6")
            dead = book.create_sheet("7_Dead Time")
            dead.cell(7, 10, 1.6)
            book.save(base)
            book.close()
            schematic = root / "board.edf"
            schematic.write_text(edif, encoding="utf-8")
            result = revise_hsi_from_schematic(base, dest, schematic)
            self.assertEqual(result.schematic_updates, 2)
            out = load_workbook(dest)
            try:
                sheet = out["2_Port Assignment "]
                self.assertIsNone(sheet.cell(2, 12).value)
                self.assertEqual(sheet.cell(3, 12).value, "Pin Definition")
                self.assertEqual(sheet.cell(3, 13).value, "Pin Function Description")
                self.assertTrue(sheet.column_dimensions["K"].hidden)
                self.assertIsNone(sheet.cell(3, 11).value)
                rows = {
                    sheet.cell(row, 2).value: row
                    for row in range(4, 7)
                    if sheet.cell(row, 2).value
                }
                self.assertEqual(set(rows), {"J501.1", "J501.2"})
                empty = rows["J501.1"]
                linked = rows["J501.2"]
                self.assertIsNone(sheet.cell(empty, 11).value)
                self.assertIsNone(sheet.cell(empty, 12).value)
                self.assertEqual(sheet.cell(empty, 23).value, "未进入任何网络；待人工复核")
                self.assertNotIn("接插件", str(sheet.cell(empty, 23).value))
                self.assertIsNone(sheet.cell(linked, 11).value)
                self.assertEqual(sheet.cell(linked, 12).value, "SIG")
                self.assertEqual(sheet.cell(linked, 23).value, "未看到接到电源或地的电阻；待人工复核")
                self.assertNotIn("原理图网络", str(sheet.cell(linked, 23).value))
                self.assertEqual(sheet.cell(3, 22).value, "核对状态")
                self.assertEqual(sheet.cell(3, 23).value, "标记说明")
                self.assertEqual(sheet.cell(3, 24).value, "人工修改")
                self.assertGreaterEqual(sheet.column_dimensions["W"].width, 36)
                self.assertTrue(sheet.cell(linked, 23).alignment.wrap_text)
                end = str(sheet.auto_filter.ref).split(":")[-1]
                self.assertGreaterEqual(end[0], "W")
                self.assertEqual(out["3_ADC Table"].cell(4, 6).value, "Signal name")
                self.assertIsNone(out["3_ADC Table"].cell(9, 6).value)
                self.assertIsNone(out["3_ADC Table"].cell(9, 8).value)
                self.assertEqual(out["Cover"].cell(1, 4).value, "修改人")
                self.assertIsNone(out["Cover"].cell(2, 4).value)
                self.assertIsNone(out["Cover"].cell(1, 5).value)
                self.assertIsNone(out["Cover"].cell(2, 5).value)
                self.assertEqual(out["Cover"].cell(2, 3).value, "硬件版本识别")
                self.assertEqual(out["1_Chang History"].cell(1, 2).value, "版本")
                self.assertIsNone(out["1_Chang History"].cell(2, 2).value)
                self.assertIsNone(out["1_Chang History"].cell(2, 4).value)
                self.assertEqual(sheet.cell(1, 1).value, "Port Assignment [Main Table]")
                self.assertIsNone(sheet.cell(2, 2).value)
                self.assertEqual(sheet.cell(3, 2).value, "Ball")
                self.assertIsNone(sheet.cell(3, 11).value)
                self.assertIsNone(out["3_ADC Table"].cell(2, 2).value)
                page = out["3_ADC Table"]
                self.assertEqual(page.cell(4, 6).fill.fgColor.rgb, "FFD9E2F3")
                self.assertTrue(page.cell(9, 6).fill.patternType in (None, "none"))
                self.assertIsNone(page.cell(9, 6).border.left)
                self.assertEqual(list(page.conditional_formatting), [])
                self.assertEqual(page._images, [])
                self.assertEqual(out["7_Dead Time"]._images, [])
                with zipfile.ZipFile(dest) as package:
                    self.assertFalse(any(name.endswith("drawing_dead_time.xml") for name in package.namelist()))
            finally:
                out.close()

    def test_schematic_repeated_net_opens_the_same_index(self) -> None:
        from electrical_krow.hsi_book import revise_hsi_from_schematic

        edif = """(edif demo
          (library COMPONENT_LIB
            (cell CON3 (view NetlistView (interface
              (port (rename &1 "1") (direction INOUT))
              (port (rename &2 "2") (direction INOUT))
              (port (rename &3 "3") (direction INOUT))
            )))
            (cell DEMO (view NetlistView (contents
              (Instance J1
                (viewRef NetlistView (cellRef CON3))
                (Property Type (String "CON" ))
              )
              (Net GND
                (Joined
                  (PortRef &1 (InstanceRef J1))
                  (PortRef &2 (InstanceRef J1))
                )
              )
              (Net SIG
                (Joined
                  (PortRef &3 (InstanceRef J1))
                )
              )
            )))
          )
        )
        """
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            base = root / "base.xlsx"
            dest = root / "out.xlsx"
            book = Workbook()
            book.active.title = "Cover"
            port = book.create_sheet("2_Port Assignment ")
            port.cell(3, 9, "Direction")
            port.cell(3, 10, "Function")
            port.cell(3, 11, "星驱原理图网络")
            port.cell(3, 12, "Pin Definition")
            book.save(base)
            book.close()
            schematic = root / "board.edf"
            schematic.write_text(edif, encoding="utf-8")
            revise_hsi_from_schematic(base, dest, schematic)
            out = load_workbook(dest)
            try:
                sheet = out["2_Port Assignment "]
                rows = {
                    sheet.cell(row, 2).value: row
                    for row in range(4, 8)
                    if sheet.cell(row, 2).value
                }
                first = rows["J1.1"]
                second = rows["J1.2"]
                single = rows["J1.3"]
                self.assertIsNone(sheet.cell(first, 11).value)
                self.assertEqual(sheet.cell(first, 12).value, "GND")
                self.assertEqual(sheet.cell(second, 12).value, "GND")
                self.assertEqual(sheet.cell(single, 12).value, "SIG")
                self.assertEqual(
                    sheet.cell(first, 12).hyperlink.location,
                    sheet.cell(second, 12).hyperlink.location,
                )
                self.assertIn("跳转索引", sheet.cell(first, 12).hyperlink.location)
                self.assertIsNone(sheet.cell(single, 12).hyperlink)
                self.assertIsNone(sheet.cell(first, 2).hyperlink)
                index = out["跳转索引"]
                listed = [
                    index.cell(row, 1).value
                    for row in range(4, 10)
                    if index.cell(row, 1).value
                ]
                self.assertIn("GND（2 处）", listed)
                self.assertTrue(any("J1.1" in str(item) for item in listed))
                self.assertTrue(any("J1.2" in str(item) for item in listed))
                self.assertFalse(any("J1.3" in str(item) for item in listed))
            finally:
                out.close()

    def test_schematic_drops_short_template_notes_and_empty_adc_banner(self) -> None:
        from electrical_krow.hsi_book import (
            DEFAULT_HSI_TEMPLATE,
            _clear_template_detail_rows,
            _strip_schematic_template_identity,
        )

        book = load_workbook(DEFAULT_HSI_TEMPLATE)
        try:
            _clear_template_detail_rows(book, drop_template_chrome=True)
            _strip_schematic_template_identity(book)
            self.assertIsNone(book["13_HVDC Overvoltage & Diag"].cell(4, 1).value)
            self.assertIn("采样电路", str(book["13_HVDC Overvoltage & Diag"].cell(1, 1).value))
            self.assertIsNone(book["15_SiC Temp"].cell(4, 2).value)
            self.assertIn("IGBT", str(book["15_SiC Temp"].cell(3, 2).value))
            self.assertIsNone(book["19_单片机温度"].cell(4, 2).value)
            self.assertIn("MCU_OilTemp", str(book["17_变速器油温"].cell(1, 1).value))
            adc = book["3_ADC Table"]
            self.assertFalse(any(str(merged) == "B2:G3" for merged in adc.merged_cells.ranges))
            self.assertIn("Signal name", str(adc.cell(4, 6).value))
        finally:
            book.close()

    def test_schematic_ball_stays_on_the_same_row(self) -> None:
        from electrical_krow.hsi_schematic import pins_from_schematic_words

        words = [
            (568, 190, 588, 198, "P31_5/NC"),
            (596, 188, 610, 196, "AF13"),
            (568, 200, 588, 208, "P31_6/NC"),
            (596, 198, 610, 206, "AE13"),
            (591, 201, 609, 207, "PIU37010AE13"),
        ]
        pins = {pin.symbol: pin.ball for pin in pins_from_schematic_words(words, "CB10")}
        self.assertEqual(pins["P31.5"], "AF13")
        self.assertEqual(pins["P31.6"], "AE13")

    def test_schematic_analog_pins_are_kept(self) -> None:
        from electrical_krow.hsi_schematic import pins_from_schematic_words

        words = [
            (100, 200, 160, 208, "AN36/P40_6"),
            (162, 197, 178, 205, "K20"),
            (100, 240, 170, 248, "AN62/P41_7/NC"),
            (172, 237, 188, 245, "L8"),
            (100, 280, 130, 288, "AN0"),
            (132, 277, 150, 285, "W13"),
            (100, 320, 150, 328, "AN56/NC"),
        ]
        pins = {pin.symbol: pin for pin in pins_from_schematic_words(words, "CB10")}
        self.assertEqual(pins["AN36"].function, "P40.6")
        self.assertEqual(pins["AN36"].ball, "K20")
        self.assertEqual(pins["AN62"].function, "P41.7")
        self.assertEqual(pins["AN62"].ball, "L8")
        self.assertEqual(pins["AN0"].ball, "W13")
        self.assertEqual(pins["AN0"].function, "")
        self.assertEqual(pins["AN56"].function, "")
        self.assertIn("AN56", pins)

    def test_schematic_net_follows_the_wire_on_the_pin_side(self) -> None:
        from electrical_krow.hsi_schematic import pins_from_schematic_words

        words = [
            (76, 122, 118, 128, "CB18_P1_GM_Driver"),
            (122, 122, 148, 128, "RDY_M_H_GM"),
            (194, 122, 227, 128, "P00_0/CAN10_TXD"),
            (242, 122, 252, 128, "P00_8"),
            (288, 122, 315, 128, "CSN3_M/T_SPI3"),
            (329, 122, 365, 128, "CB11_RRO_CHASSIS"),
            (430, 122, 480, 128, "FLTA_M_H_TM"),
        ]
        lines = [(124.4, 162.0, 191.0), (124.4, 254.0, 284.0)]
        pins = {pin.symbol: pin for pin in pins_from_schematic_words(words, "CB09", lines)}
        self.assertEqual(pins["P00.0"].net, "RDY_M_H_GM")
        self.assertEqual(pins["P00.0"].function, "CAN10_TXD")
        self.assertEqual(pins["P00.8"].net, "CSN3_M/T_SPI3")
        self.assertNotEqual(pins["P00.8"].net, "FLTA_M_H_TM")
        self.assertNotIn("CB18", pins["P00.0"].net)
        self.assertNotIn("CB11", pins["P00.8"].net)

    def test_jump_index_keeps_the_rows_under_each_net(self) -> None:
        from electrical_krow.hsi_book import _clear_template_detail_rows

        book = Workbook()
        cover = book.active
        cover.title = "Cover"
        cover.cell(1, 4, "修改人")
        book.create_sheet("0_硬件版本识别")
        index = book.create_sheet("跳转索引")
        index["A4"] = "FLTA_M_H_TM（2 处）"
        index["A5"] = "第5行 P00.1"
        index["A6"] = "第8行 P14.0"
        index["A12"] = "GND（2 处）"
        index["A13"] = "第20行 P02.0"
        _clear_template_detail_rows(book, drop_template_chrome=True)
        self.assertEqual(index["A4"].value, "FLTA_M_H_TM（2 处）")
        self.assertEqual(index["A5"].value, "第5行 P00.1")
        self.assertEqual(index["A6"].value, "第8行 P14.0")
        self.assertEqual(index["A12"].value, "GND（2 处）")
        self.assertEqual(index["A13"].value, "第20行 P02.0")

    def test_schematic_symbol_functions_fill_later_sheets(self) -> None:
        from electrical_krow.hsi_book import (
            _chips_from_schematic,
            _fill_adc_from_manual,
            _fill_can_from_manual,
            _fill_spi_from_manual,
        )
        from electrical_krow.hsi_schematic import SchematicSymbolPin

        pins = [
            SchematicSymbolPin("P00.0", "K4", "QSPI2_TXD", "CB09", "RDY_M_H_GM"),
            SchematicSymbolPin("P14.0", "E19", "CAN10_TXD", "CB08", "CANTX_M/T_DB"),
            SchematicSymbolPin("P00.1", "K5", "GPIO", "CB09", ""),
            SchematicSymbolPin("AN0", "W13", "EVADC_G9CH11", "CB10", "IA_S"),
        ]
        chips = _chips_from_schematic(pins)
        book = Workbook()
        adc = book.active
        adc.title = "3_ADC Table"
        adc["B4"] = "Gr"
        adc["C4"] = "Channel"
        adc["D4"] = "PIN"
        adc["E4"] = "Ball"
        spi = book.create_sheet("4-SPI总线")
        spi["B4"] = "PIN"
        spi["C4"] = "Pin Function"
        spi["D4"] = "I/O"
        book.create_sheet("6_CAN")
        _fill_adc_from_manual(book, chips)
        _fill_spi_from_manual(book, chips)
        _fill_can_from_manual(book, chips)
        self.assertEqual(adc["D5"].value, "AN0")
        self.assertEqual(adc["E5"].value, "W13")
        self.assertEqual(adc["B5"].value, "G9")
        self.assertIn("EVADC_G9CH11", str(adc["C5"].value))
        self.assertIsNone(adc["D6"].value)
        self.assertEqual(spi["B5"].value, "P00.0")
        self.assertIn("QSPI2_TXD", str(spi["C5"].value))
        self.assertIsNone(spi["D5"].value)
        self.assertEqual(book["6_CAN"]["B3"].value, "P14.0")
        self.assertIn("CAN10_TXD", str(book["6_CAN"]["C3"].value))
        book.close()

    def test_schematic_adc_group_follows_the_manual_ball(self) -> None:
        from electrical_krow.hsi_book import _chips_from_schematic, _fill_adc_from_manual, _merge_manual_adc
        from electrical_krow.hsi_schematic import SchematicSymbolPin
        from electrical_krow.mcu_pins import ChipPin

        pins = [
            SchematicSymbolPin("AN36", "T7", "P40.6", "CB10", "RDC_S/M_BT"),
            SchematicSymbolPin("AN0", "W13", "", "CB10", ""),
            SchematicSymbolPin("P00.1", "K5", "GPIO", "CB09", ""),
        ]
        manual = {
            "T7": ChipPin(
                "",
                "T7",
                "AN36",
                "",
                "",
                "Analog Input 36",
                "P40.6 General-purpose input；ADC_TMADC3CH8 Analog Input for TMADC3 Channel 8；ADC_DSADC8PA Analog Input for DSADC8 Positive Input",
                "1",
                "",
            ),
            "W13": ChipPin(
                "",
                "W13",
                "AN0",
                "",
                "",
                "Analog Input 0",
                "ADC_TMADC0CH0 Analog Input for TMADC0 Channel 0；ADC_FCC1 Analog Input for FCC1",
                "1",
                "",
            ),
        }
        chips = _merge_manual_adc(pins, _chips_from_schematic(pins), manual)
        by_symbol = {pin.symbol: pin for pin in chips}
        self.assertIn("ADC_TMADC3CH8", by_symbol["AN36"].mux)
        self.assertIn("P40.6", by_symbol["AN36"].mux)
        self.assertEqual(by_symbol["AN36"].function, "P40.6")
        self.assertNotIn("ADC", by_symbol["P00.1"].mux)
        book = Workbook()
        adc = book.active
        adc.title = "3_ADC Table"
        adc["B4"] = "Gr"
        adc["C4"] = "Channel"
        adc["D4"] = "PIN"
        adc["E4"] = "Ball"
        _fill_adc_from_manual(book, chips)
        rows = {
            adc.cell(row, 4).value: (
                adc.cell(row, 2).value,
                str(adc.cell(row, 3).value or ""),
                adc.cell(row, 5).value,
            )
            for row in range(5, 8)
            if adc.cell(row, 4).value
        }
        self.assertEqual(rows["AN36"][0], "TMADC3")
        self.assertIn("ADC_TMADC3CH8", rows["AN36"][1])
        self.assertEqual(rows["AN36"][2], "T7")
        self.assertEqual(rows["AN0"][0], "TMADC0")
        self.assertIn("ADC_TMADC0CH0", rows["AN0"][1])
        self.assertNotIn("P00.1", rows)
        book.close()

    def test_schematic_adc_group_reads_the_tc499_manual(self) -> None:
        from electrical_krow.hsi_book import _adc_channel_names, _adc_group, _chips_with_manual_adc
        from electrical_krow.hsi_schematic import SchematicSymbolPin

        manual = (
            Path(__file__).resolve().parents[2]
            / "资料"
            / "MCU 芯片手册"
            / "infineon-sak-tc499pp-20mf400ms-ab-datasheet-en.pdf"
        )
        if not manual.is_file():
            self.skipTest("本机没有 TC499 手册")
        pins = [
            SchematicSymbolPin("AN0", "W13", "", "CB10", ""),
            SchematicSymbolPin("AN36", "T7", "P40.6", "CB10", ""),
        ]
        chips = {pin.symbol: pin for pin in _chips_with_manual_adc(pins, "TC499")}
        self.assertIn("ADC_TMADC0CH0", chips["AN0"].mux)
        self.assertEqual(_adc_group(_adc_channel_names(chips["AN36"])), "TMADC3")
        self.assertEqual(chips["AN36"].function, "P40.6")

    def test_schematic_pdf_reads_pin_and_ball_on_the_symbol(self) -> None:
        import pymupdf

        from electrical_krow.hsi_book import revise_hsi_from_schematic

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            drawing = root / "sheet.pdf"
            doc = pymupdf.open()
            page = doc.new_page(width=842, height=595)
            page.insert_text((40, 40), "CB10_MCU DIO.SchDoc", fontsize=10)
            page.insert_text((40, 60), "SAK-TC499PP-20MF400MS AB", fontsize=10)
            page.insert_text((100, 220), "P14_0/ASCLIN0_ATX", fontsize=6)
            page.insert_text((78, 217), "E19", fontsize=6)
            page.insert_text((100, 260), "P24_0", fontsize=6)
            page.insert_text((78, 257), "L25", fontsize=6)
            doc.save(drawing)
            doc.close()
            base = root / "base.xlsx"
            dest = root / "out.xlsx"
            book = Workbook()
            book.active.title = "Cover"
            port = book.create_sheet("2_Port Assignment ")
            port.cell(1, 1, "TC499 Port Assignment [Main Table]")
            port.cell(2, 2, "MCU_TC499")
            port.cell(3, 2, r"BGA436\Ball")
            port.cell(3, 3, "Pin_Symbol")
            port.cell(3, 9, "Direction")
            port.cell(3, 10, "Function")
            port.cell(2, 12, "Superevo pin Definition")
            port.cell(3, 12, "Pin Definition")
            book.save(base)
            book.close()
            result = revise_hsi_from_schematic(base, dest, drawing)
            self.assertEqual(result.schematic_updates, 2)
            self.assertEqual(result.mcu, "TC499")
            out = load_workbook(dest)
            try:
                sheet = out["2_Port Assignment "]
                rows = {
                    sheet.cell(row, 3).value: row
                    for row in range(4, 8)
                    if sheet.cell(row, 3).value
                }
                self.assertEqual(set(rows), {"P14.0", "P24.0"})
                tx = rows["P14.0"]
                self.assertEqual(sheet.cell(tx, 2).value, "E19")
                self.assertEqual(sheet.cell(tx, 19).value, "ASCLIN0_ATX")
                self.assertIn("CB10_MCU DIO", str(sheet.cell(tx, 23).value))
                self.assertNotIn("ASCLIN0_ATX", str(sheet.cell(tx, 23).value))
                self.assertIsNone(sheet.cell(tx, 10).value)
                plain = rows["P24.0"]
                self.assertEqual(sheet.cell(plain, 2).value, "L25")
                self.assertIsNone(sheet.cell(plain, 19).value)
                self.assertIn("未标功能", str(sheet.cell(plain, 23).value))
                self.assertIn("TC499", str(sheet.cell(1, 1).value))
                self.assertEqual(sheet.cell(2, 2).value, "MCU_TC499")
                self.assertEqual(sheet.cell(3, 2).value, "Ball")
                self.assertIsNone(sheet.cell(2, 12).value)
                self.assertEqual(sheet.cell(3, 12).value, "Pin Definition")
            finally:
                out.close()

    def test_board_pins_drop_template_yellow_and_purple_rows(self) -> None:
        from electrical_krow.hsi_book import DEFAULT_HSI_TEMPLATE, _write_board_pins
        from electrical_krow.hsi_schematic import BoardPin

        book = load_workbook(DEFAULT_HSI_TEMPLATE)
        try:
            port = book[[name for name in book.sheetnames if name.startswith("2_Port")][0]]
            self.assertIn(4, port.row_dimensions)
            self.assertIn(22, port.row_dimensions)
            written = _write_board_pins(
                book,
                [BoardPin(ref="J402", pin="20", net="PWM_M/D_AH_GM", pulls=())],
            )
            self.assertEqual(written, 1)
            self.assertNotIn(22, port.row_dimensions)
            self.assertNotEqual(port.row_dimensions[4].fill.patternType, "solid")
            self.assertEqual(port.sheet_view.view, "normal")
            self.assertEqual(port.sheet_view.topLeftCell, "A1")
            self.assertEqual(list(port.conditional_formatting), [])
            for dim in port.column_dimensions.values():
                self.assertNotEqual(dim.fill.patternType, "solid")
                self.assertTrue(dim.max is None or dim.max < 200)
        finally:
            book.close()

    def test_manual_ports_drop_template_yellow_and_purple_rows(self) -> None:
        from electrical_krow.hsi_book import DEFAULT_HSI_TEMPLATE, _write_ports

        book = load_workbook(DEFAULT_HSI_TEMPLATE)
        try:
            port = book[[name for name in book.sheetnames if name.startswith("2_Port")][0]]
            self.assertIn(4, port.row_dimensions)
            self.assertIn(22, port.row_dimensions)
            self.assertEqual(port.sheet_view.view, "pageBreakPreview")
            _write_ports(port, "TC399", "BGA292", [], (), {})
            self.assertNotIn(4, port.row_dimensions)
            self.assertNotIn(22, port.row_dimensions)
            self.assertEqual(port.sheet_view.view, "normal")
            self.assertEqual(port.sheet_view.topLeftCell, "A1")
            self.assertEqual(list(port.conditional_formatting), [])
            for dim in port.column_dimensions.values():
                self.assertNotEqual(dim.fill.patternType, "solid")
                self.assertTrue(dim.max is None or dim.max < 200)
        finally:
            book.close()

