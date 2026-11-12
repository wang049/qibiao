"""生成可公开分发的示例规格书（PDF / Word / Excel）。"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt
from openpyxl import Workbook
import pymupdf

ROOT = Path(__file__).resolve().parent

TITLE = "交流伺服电机 产品规格书"
VERSION = "V2.1"
DATE = "2026-03-12"
DOC_NO = "SPEC-SV-200-2026"

FIELDS = [
    ("产品名称", "交流伺服电机"),
    ("型号", "SV-200A-400W"),
    ("制造商", "华科驱动有限公司"),
    ("品牌", "华科驱动"),
    ("额定电压", "220 V AC"),
    ("额定电流", "2.8 A"),
    ("额定功率", "400 W"),
    ("频率", "50/60 Hz"),
    ("外形尺寸", "60 × 60 × 128 mm"),
    ("重量", "1.35 kg（净重）"),
    ("安装方式", "法兰安装，插头接线"),
    ("工作温度", "-10 ℃ ~ +40 ℃"),
    ("防护等级", "IP65（轴伸除外 IP54）"),
    ("认证标准", "GB/T 30557、CCC、CE"),
]

EXTRA_ROWS = [
    ("额定转速", "3000 r/min"),
    ("最大转速", "5000 r/min"),
    ("额定转矩", "1.27 N·m"),
    ("编码器", "17-bit 增量式"),
]


def _set_cjk_font(run, name: str = "Songti SC") -> None:
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def write_docx(path: Path) -> None:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Songti SC"
    style.font.size = Pt(11)
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "Songti SC")

    h = doc.add_paragraph()
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = h.add_run(TITLE)
    run.bold = True
    run.font.size = Pt(18)
    _set_cjk_font(run)

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = meta.add_run(f"文件编号 {DOC_NO}    版本 {VERSION}    日期 {DATE}")
    _set_cjk_font(run)

    doc.add_paragraph("1. 产品概述")
    p = doc.add_paragraph(
        "本规格书描述交流伺服电机 SV-200A-400W 的电气、机械与环境参数，"
        "供选型与进货核对使用。表中数值均为额定工况。"
    )
    _set_cjk_font(p.runs[0])

    doc.add_paragraph("2. 基本参数")
    table = doc.add_table(rows=1, cols=2)
    table.style = "Table Grid"
    table.rows[0].cells[0].text = "项目"
    table.rows[0].cells[1].text = "规格"
    for name, value in FIELDS:
        row = table.add_row().cells
        row[0].text = name
        row[1].text = value

    doc.add_paragraph("3. 性能参数")
    table2 = doc.add_table(rows=1, cols=2)
    table2.style = "Table Grid"
    table2.rows[0].cells[0].text = "项目"
    table2.rows[0].cells[1].text = "规格"
    for name, value in EXTRA_ROWS:
        row = table2.add_row().cells
        row[0].text = name
        row[1].text = value

    doc.add_paragraph("4. 注意事项")
    note = doc.add_paragraph(
        "安装时轴伸需加防护。连续过载不得超过 1.5 倍额定转矩、持续 3 秒。"
        "本页为测试样例，非真实产品文件。"
    )
    _set_cjk_font(note.runs[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


def write_xlsx(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "规格"
    ws["A1"] = TITLE
    ws["A2"] = f"文件编号 {DOC_NO}"
    ws["B2"] = f"版本 {VERSION}"
    ws["C2"] = f"日期 {DATE}"
    ws["A4"] = "项目"
    ws["B4"] = "规格"
    row_i = 5
    for name, value in FIELDS + EXTRA_ROWS:
        ws.cell(row_i, 1, name)
        ws.cell(row_i, 2, value)
        row_i += 1
    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["B"].width = 36
    wb.save(path)


def write_pdf(path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    font = "china-s"
    y = 56
    page.insert_text((72, y), TITLE, fontsize=18, fontname=font)
    y += 28
    page.insert_text(
        (72, y),
        f"文件编号 {DOC_NO}    版本 {VERSION}    日期 {DATE}",
        fontsize=10,
        fontname=font,
    )
    y += 28
    page.insert_text((72, y), "第 1 页", fontsize=9, fontname=font)
    y += 24
    page.insert_text((72, y), "1. 产品概述", fontsize=12, fontname=font)
    y += 20
    overview = (
        "本规格书描述交流伺服电机 SV-200A-400W 的电气、机械与环境参数，"
        "供选型与进货核对使用。表中数值均为额定工况。"
    )
    rect = pymupdf.Rect(72, y, 523, y + 48)
    page.insert_textbox(rect, overview, fontsize=11, fontname=font)
    y += 56
    page.insert_text((72, y), "2. 基本参数", fontsize=12, fontname=font)
    y += 18
    for name, value in FIELDS:
        page.insert_text((72, y), f"{name}    {value}", fontsize=11, fontname=font)
        y += 16
    y += 8
    page.insert_text((72, y), "3. 性能参数", fontsize=12, fontname=font)
    y += 18
    for name, value in EXTRA_ROWS:
        page.insert_text((72, y), f"{name}    {value}", fontsize=11, fontname=font)
        y += 16
    y += 12
    page.insert_text((72, y), "4. 注意事项（第 1 页）", fontsize=12, fontname=font)
    y += 18
    note = (
        "安装时轴伸需加防护。连续过载不得超过 1.5 倍额定转矩、持续 3 秒。"
        "本文件为测试样例，非真实产品规格书。"
    )
    page.insert_textbox(pymupdf.Rect(72, y, 523, y + 48), note, fontsize=11, fontname=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    doc.close()


def write_hard_pdf(path: Path) -> None:
    """两页 + 干扰项：历史型号、峰值电流、包装重量、认证在第 2 页。"""
    doc = pymupdf.open()
    font = "china-s"

    p1 = doc.new_page(width=595, height=842)
    y = 56
    p1.insert_text((72, y), TITLE, fontsize=18, fontname=font)
    y += 26
    p1.insert_text((72, y), f"文件编号 {DOC_NO}    版本 {VERSION}    日期 {DATE}", fontsize=10, fontname=font)
    y += 22
    p1.insert_text((72, y), "第 1 页 / 共 2 页", fontsize=9, fontname=font)
    y += 22
    p1.insert_text((72, y), "1. 封面说明", fontsize=12, fontname=font)
    y += 18
    p1.insert_textbox(
        pymupdf.Rect(72, y, 523, y + 70),
        "现行型号为 SV-200A-400W。历史型号 SV-200A-200W 已停产，仅出现在本页说明中，"
        "不得写入现行规格。峰值电流 8.4 A 不是额定电流。包装重量 1.8 kg 不是净重。",
        fontsize=11,
        fontname=font,
    )
    y += 80
    p1.insert_text((72, y), "2. 产品标识（第 1 页）", fontsize=12, fontname=font)
    y += 18
    for line in (
        "产品名称    交流伺服电机",
        "型号    SV-200A-400W",
        "制造商    华科驱动有限公司",
        "品牌    华科驱动",
    ):
        p1.insert_text((72, y), line, fontsize=11, fontname=font)
        y += 16

    p2 = doc.new_page(width=595, height=842)
    y = 56
    p2.insert_text((72, y), f"{TITLE}（续）", fontsize=16, fontname=font)
    y += 24
    p2.insert_text((72, y), "第 2 页 / 共 2 页", fontsize=9, fontname=font)
    y += 22
    p2.insert_text((72, y), "3. 电气与机械（第 2 页）", fontsize=12, fontname=font)
    y += 18
    for line in (
        "额定电压    220 V AC",
        "额定电流    2.8 A",
        "峰值电流    8.4 A",
        "额定功率    400 W",
        "频率    50/60 Hz",
        "外形尺寸    60 × 60 × 128 mm",
        "净重    1.35 kg",
        "包装重量    1.8 kg",
        "安装方式    法兰安装，插头接线",
        "工作温度    -10 ℃ ~ +40 ℃",
        "防护等级    IP65（轴伸除外 IP54）",
        "认证标准    GB/T 30557、CCC、CE",
    ):
        p2.insert_text((72, y), line, fontsize=11, fontname=font)
        y += 16

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    doc.close()


def write_english_pdf(path: Path) -> None:
    """English-only datasheet."""
    font = "helv"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 56
    page.insert_text((72, y), "AC Servo Motor Technical Datasheet", fontsize=16, fontname=font)
    y += 24
    page.insert_text((72, y), f"Doc. No. {DOC_NO}    Version {VERSION}    Date {DATE}", fontsize=10, fontname=font)
    y += 18
    page.insert_text((72, y), "Page 1", fontsize=9, fontname=font)
    y += 22
    page.insert_text((72, y), "Ratings", fontsize=12, fontname=font)
    y += 18
    for line in (
        "Product name    AC servo motor",
        "Type    SV-200A-400W",
        "Manufacturer    Huake Drive Co., Ltd.",
        "Brand    Huake",
        "Rated voltage    220 V AC",
        "Rated current    2.8 A",
        "Peak current    8.4 A",
        "Rated power    400 W",
        "Frequency    50/60 Hz",
        "Dimensions    60 x 60 x 128 mm",
        "Net weight    1.35 kg",
        "Packed weight    1.8 kg",
        "Mounting    Flange, connector",
        "Operating temperature    -10 C to +40 C",
        "Degree of protection    IP65 (except shaft IP54)",
        "Standards    EN 61800-5-1, CE, CCC",
    ):
        page.insert_text((72, y), line, fontsize=11, fontname=font)
        y += 15
    y += 8
    page.insert_textbox(
        pymupdf.Rect(72, y, 523, y + 40),
        "Note: Discontinued type SV-200A-200W must not be copied as the current model.",
        fontsize=10,
        fontname=font,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    doc.close()


def write_german_pdf(path: Path) -> None:
    """German-only Datenblatt, decimal comma."""
    font = "helv"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 56
    page.insert_text((72, y), "Technisches Datenblatt AC-Servomotor", fontsize=16, fontname=font)
    y += 24
    page.insert_text((72, y), f"Dokumentnr. {DOC_NO}    Version {VERSION}    Datum {DATE}", fontsize=10, fontname=font)
    y += 18
    page.insert_text((72, y), "Seite 1", fontsize=9, fontname=font)
    y += 22
    page.insert_text((72, y), "Kenndaten", fontsize=12, fontname=font)
    y += 18
    for line in (
        "Produktname    AC-Servomotor",
        "Typ    SV-200A-400W",
        "Hersteller    Huake Antrieb GmbH",
        "Marke    Huake",
        "Nennspannung    220 V AC",
        "Nennstrom    2,8 A",
        "Spitzenstrom    8,4 A",
        "Nennleistung    400 W",
        "Frequenz    50/60 Hz",
        "Abmessungen    60 x 60 x 128 mm",
        "Nettogewicht    1,35 kg",
        "Verpackungsgewicht    1,8 kg",
        "Montage    Flansch, Stecker",
        "Betriebstemperatur    -10 C bis +40 C",
        "Schutzart    IP65 (Welle IP54)",
        "Normen    EN 61800-5-1, CE, CCC",
    ):
        page.insert_text((72, y), line, fontsize=11, fontname=font)
        y += 15
    y += 8
    page.insert_textbox(
        pymupdf.Rect(72, y, 523, y + 40),
        "Hinweis: Der historische Typ SV-200A-200W ist nicht mehr lieferbar und darf nicht als aktueller Typ verwendet werden.",
        fontsize=10,
        fontname=font,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    doc.close()


def main() -> None:
    write_pdf(ROOT / "sample_servo_spec.pdf")
    write_docx(ROOT / "sample_servo_spec.docx")
    write_xlsx(ROOT / "sample_servo_spec.xlsx")
    write_hard_pdf(ROOT / "sample_servo_spec_hard.pdf")
    write_english_pdf(ROOT / "sample_servo_spec_en.pdf")
    write_german_pdf(ROOT / "sample_servo_spec_de.pdf")
    print("wrote", ROOT / "sample_servo_spec.pdf")
    print("wrote", ROOT / "sample_servo_spec.docx")
    print("wrote", ROOT / "sample_servo_spec.xlsx")
    print("wrote", ROOT / "sample_servo_spec_hard.pdf")
    print("wrote", ROOT / "sample_servo_spec_en.pdf")
    print("wrote", ROOT / "sample_servo_spec_de.pdf")


if __name__ == "__main__":
    main()
