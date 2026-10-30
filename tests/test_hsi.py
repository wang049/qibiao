from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook, load_workbook

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
                self.assertEqual(port["L5"].value, "L1")
                self.assertEqual(port["M5"].value, "QM")
                self.assertEqual(port.cell(5, COL_STATUS).value, STATUS_DRAFT)
                self.assertNotEqual(port.cell(5, COL_STATUS).value, "已确认")
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
                self.assertEqual(book[SHEET_PORT]["J5"].value, "KEEP_ME")
                self.assertEqual(book[SHEET_PORT]["L5"].value, "L1")
                self.assertNotEqual(book[SHEET_PORT]["J5"].value, "OLD_NAME")
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
                    port.cell(row, 2).value: row
                    for row in range(4, 8)
                    if port.cell(row, 2).value
                }
                analog = located["AN0"]
                self.assertEqual(port.cell(analog, 9).value, "Input")
                self.assertEqual(port.cell(analog, 10).value, "Analog")
                self.assertEqual(port.cell(analog, 12).value, "IA_S/M_TM")
                self.assertIn("Analog", str(port.cell(analog, COL_MARK).value))
                drive = located["P02.1"]
                self.assertEqual(port.cell(drive, 3).value, "F5")
                self.assertEqual(port.cell(drive, 9).value, "Output")
                self.assertEqual(port.cell(drive, 10).value, "PWM")
                self.assertEqual(port.cell(drive, 11).value, "DPO_DRV_UH_M1")
                self.assertEqual(port.cell(drive, 12).value, "PWM_M_AH_GM")
                self.assertIn("ATOM1", str(port.cell(drive, 7).value))
                self.assertIn("DTM4_1", str(port.cell(drive, 8).value))
                self.assertIn("ATOM1", str(port.cell(drive, 19).value))
                name_link = port.cell(analog, 12).hyperlink
                self.assertIsNotNone(name_link)
                self.assertTrue((name_link.location or "").startswith("HSI_ADC_"))
                self.assertIn("IA_S/M_TM", name_link.tooltip or "")
                self.assertIn("第", name_link.tooltip or "")
                self.assertFalse(name_link.target)
                anchor = out.defined_names[name_link.location].attr_text
                self.assertIn("3_ADC Table", anchor)
                self.assertIn(":$", anchor)
                adc = out["3_ADC Table"]
                self.assertTrue(adc.column_dimensions["Z"].hidden)
                self.assertTrue(adc.column_dimensions["AD"].hidden)
                self.assertFalse(adc.column_dimensions["AA"].hidden)
            finally:
                out.close()

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
        self.assertTrue(adc.column_dimensions["Z"].hidden)
        self.assertTrue(adc.column_dimensions["AD"].hidden)
        self.assertFalse(adc.column_dimensions["AA"].hidden)

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
            self.assertEqual(port.cell(4, 11).value, "PWM_M/D_AH_GM")
            self.assertEqual(port.cell(4, 15).value, "下拉 68kΩ")
            self.assertNotIn("100", str(port.cell(4, 23).value))
            self.assertIn("R822A", str(port.cell(4, 23).value))
            self.assertIn("待人工复核", str(port.cell(4, 23).value))
            self.assertIn(STATUS_DRAFT, str(port.cell(4, 22).value))
            self.assertEqual(port.cell(5, 15).value, "上拉 10kΩ")
            self.assertEqual(port.cell(6, 11).value, "AI_IU_CH1_M2")
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
                self.assertEqual(sheet.cell(4, 11).value, "PWM_M/D_AH_GM")
                self.assertEqual(sheet.cell(4, 12).value, "PWM_M/D_AH_GM")
                self.assertEqual(sheet.cell(4, 15).value, "下拉 68kΩ")
                self.assertIn("待人工复核", str(sheet.cell(4, 23).value))
                self.assertNotIn("P02.1", str(sheet.cell(4, 23).value))
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
            self.assertNotIn(4, port.row_dimensions)
            self.assertNotIn(22, port.row_dimensions)
            self.assertEqual(port.sheet_view.view, "normal")
        finally:
            book.close()

