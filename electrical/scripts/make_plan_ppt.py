"""极光湾电子电器 · 方案汇报 PPT。版式对齐同事 KAD / 仿真稿：左轨、陶土强调、大标题。"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

# 同事稿 token（kad-cae / krow 客户端）
ACCENT = RGBColor(0xBF, 0x46, 0x1B)
ACCENT_INK = RGBColor(0x8E, 0x33, 0x12)
ACCENT_WASH = RGBColor(0xF6, 0xE2, 0xD8)
INK = RGBColor(0x13, 0x18, 0x1C)
INK2 = RGBColor(0x48, 0x53, 0x5B)
INK3 = RGBColor(0x7C, 0x88, 0x91)
RULE = RGBColor(0xC6, 0xCE, 0xD4)
RULE2 = RGBColor(0xDC, 0xE2, 0xE6)
SURFACE = RGBColor(0xFF, 0xFF, 0xFF)
SURFACE3 = RGBColor(0xF4, 0xF6, 0xF7)
SURFACE4 = RGBColor(0xE7, 0xEC, 0xEF)
STEEL = RGBColor(0x1D, 0x6A, 0x85)
OK = RGBColor(0x4C, 0x8A, 0x3C)
DARK = RGBColor(0x13, 0x18, 0x1C)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
KM = STEEL
JG = ACCENT
MILE = ACCENT_INK

W = Inches(13.333)
H = Inches(7.5)
RAIL = Inches(0.67)
ML = Inches(1.12)
OUT = Path("/Users/wwj/Desktop/极光湾电子电器SOR填表-方案汇报.pptx")


def _font(run, text, size=14, bold=False, color=INK, name="微软雅黑"):
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = name
    rpr = run._r.get_or_add_rPr()
    ea = rpr.find(qn("a:ea"))
    if ea is None:
        ea = etree.SubElement(rpr, qn("a:ea"))
    ea.set("typeface", "微软雅黑")
    latin = rpr.find(qn("a:latin"))
    if latin is None:
        latin = etree.SubElement(rpr, qn("a:latin"))
    latin.set("typeface", name)


def txt(tf, text, size=14, bold=False, color=INK, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, name="微软雅黑"):
    tf.word_wrap = True
    try:
        tf.vertical_anchor = anchor
    except Exception:
        pass
    p = tf.paragraphs[0]
    p.alignment = align
    p.clear()
    _font(p.add_run(), text, size, bold, color, name)


def para(tf, text, size=13, bold=False, color=INK, before=6, name="微软雅黑"):
    p = tf.add_paragraph()
    p.alignment = PP_ALIGN.LEFT
    p.space_before = Pt(before)
    _font(p.add_run(), text, size, bold, color, name)


def rect(slide, l, t, w, h, color, border=None, lw=0.75):
    s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, l, t, w, h)
    s.fill.solid()
    s.fill.fore_color.rgb = color
    s.shadow.inherit = False
    if border is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = border
        s.line.width = Pt(lw)
    return s


def box(slide, l, t, w, h, text, size=14, bold=False, color=INK, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, name="微软雅黑"):
    tb = slide.shapes.add_textbox(l, t, w, h)
    txt(tb.text_frame, text, size=size, bold=bold, color=color, align=align, anchor=anchor, name=name)
    return tb


def new_slide(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def _vert(shape):
    body = shape.text_frame._txBody.find(qn("a:bodyPr"))
    if body is not None:
        body.set("vert", "eaVert")


def rail(slide, num: str, sec: str, brand: str = "kmind"):
    rect(slide, 0, 0, W, H, SURFACE)
    rect(slide, 0, 0, RAIL, H, SURFACE3)
    rect(slide, RAIL, 0, Pt(1), H, RULE)
    box(
        slide,
        Inches(0.02),
        Inches(0.28),
        RAIL - Inches(0.04),
        Inches(0.4),
        num,
        size=16,
        bold=True,
        color=ACCENT,
        align=PP_ALIGN.CENTER,
        name="Calibri",
    )
    rect(slide, Inches(0.23), Inches(0.78), Inches(0.21), Pt(1), RULE)
    tb = slide.shapes.add_textbox(Inches(0.08), Inches(1.05), Inches(0.5), Inches(4.6))
    txt(tb.text_frame, sec.upper(), size=9, bold=True, color=INK3, align=PP_ALIGN.CENTER, name="Calibri")
    _vert(tb)
    box(
        slide,
        Inches(0.02),
        Inches(6.95),
        RAIL - Inches(0.04),
        Inches(0.35),
        brand,
        size=9,
        bold=True,
        color=INK3,
        align=PP_ALIGN.CENTER,
        name="Calibri",
    )


def eyebrow(slide, text):
    box(slide, ML, Inches(0.32), Inches(11.5), Inches(0.28), text.upper(), size=10, color=INK3, name="Calibri")


def title(slide, text, size=28):
    box(slide, ML, Inches(0.58), Inches(11.6), Inches(0.55), text, size=size, bold=True, color=INK)


def sub(slide, text, y=Inches(1.12)):
    box(slide, ML, y, Inches(11.6), Inches(0.32), text, size=12, color=INK2)


def inset_bar(slide, l, t, h, color=ACCENT):
    rect(slide, l, t, Pt(3), h, color)


def cover(prs):
    s = new_slide(prs)
    rail(s, "01", "Cover")
    # 浅网格（右半）
    for i in range(10, 28):
        x = Inches(i * 0.44)
        if x < W:
            rect(s, x, 0, Pt(0.6), H, RULE2)
    for j in range(0, 18):
        y = Inches(j * 0.44)
        if y < H:
            rect(s, RAIL, y, W - RAIL, Pt(0.6), RULE2)
    rect(s, RAIL, 0, Inches(7.2), H, SURFACE)  # 左文案区盖住网格
    box(s, ML, Inches(1.55), Inches(0.4), Inches(0.08), " ", size=4)
    rect(s, ML, Inches(1.72), Inches(0.4), Pt(3), ACCENT)
    box(s, ML + Inches(0.52), Inches(1.62), Inches(8), Inches(0.28), "KMIND  ·  极光湾电子电器开发中心", size=11, color=INK3, name="Calibri")
    tb = s.shapes.add_textbox(ML, Inches(2.05), Inches(10.5), Inches(2.1))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.clear()
    r = p.add_run()
    _font(r, "电子电器 · ", 40, True, INK)
    r2 = p.add_run()
    _font(r2, "SOR填表", 40, True, ACCENT)
    p2 = tf.add_paragraph()
    p2.space_before = Pt(8)
    r3 = p2.add_run()
    _font(r3, "方案", 40, True, INK)
    box(
        s,
        ML,
        Inches(4.35),
        Inches(10.2),
        Inches(0.7),
        "工位本机出可核对表，8–12 月分阶段交付；2027 年推进原理图/布局检查单和方案对比。",
        size=15,
        color=INK2,
    )
    rect(s, ML, Inches(6.55), Inches(11.4), Pt(1), RULE)
    box(s, ML, Inches(6.7), Inches(7.2), Inches(0.28), "功能清单  ·  架构图  ·  方案  ·  开发计划  ·  展望", size=11, color=INK3, name="Calibri")
    box(s, Inches(9.2), Inches(6.7), Inches(1.4), Inches(0.28), "2026-08-24  ·  9 页", size=11, color=INK3, name="Calibri")
    box(s, Inches(11.0), Inches(6.65), Inches(1.5), Inches(0.32), "kmind", size=16, bold=True, color=INK, name="Calibri")


def toc(prs, n, total):
    s = new_slide(prs)
    rail(s, f"{n:02d}", "Index")
    eyebrow(s, "目录")
    title(s, "五块结构")
    sub(s, "功能清单 · 架构图 · 方案 · 开发计划 · 展望")
    items = [
        ("01", "FEATURES", "功能清单", "SOR 工具能力 + 全年延伸交付"),
        ("02", "ARCHITECTURE", "架构图", "工位本机闭环 + 全年双线并行"),
        ("03", "PLAN", "方案", "出表流程 · 双方配合 · 工位条件"),
        ("04", "ROADMAP", "开发计划", "甘特图：8–12 月节点与双方配合"),
        ("05", "OUTLOOK", "展望", "2027 年原理图/布局检查单和方案对比"),
    ]
    for i, (num, en, zh, desc) in enumerate(items):
        y = Inches(1.52) + Inches(i * 1.02)
        rect(s, ML, y, Inches(11.4), Inches(0.92), SURFACE3, RULE)
        inset_bar(s, ML, y, Inches(0.92))
        box(s, ML + Inches(0.28), y + Inches(0.08), Inches(1.1), Inches(0.76), num, size=20, bold=True, color=ACCENT, anchor=MSO_ANCHOR.MIDDLE, name="Calibri")
        box(s, ML + Inches(1.5), y + Inches(0.08), Inches(3.2), Inches(0.24), en, size=10, color=INK3, name="Calibri")
        box(s, ML + Inches(1.5), y + Inches(0.32), Inches(9.4), Inches(0.28), zh, size=16, bold=True, color=INK)
        box(s, ML + Inches(1.5), y + Inches(0.6), Inches(9.4), Inches(0.24), desc, size=12, color=INK2)


def features(prs, n, total):
    s = new_slide(prs)
    rail(s, f"{n:02d}", "Features")
    eyebrow(s, "一 · 功能清单")
    title(s, "五项交付", size=26)
    sub(s, "一期工具能力 + 延伸任务（独立交付成果，不纳入填表工具功能范围）")

    headers = ["编号", "模块", "功能项", "说明", "节点"]
    widths = [Inches(0.7), Inches(1.55), Inches(2.15), Inches(5.35), Inches(1.65)]
    rows = [
        ("grp", "A · SOR 自动填表", "8–9 月上线，工位本机独立操作"),
        ("1.1", "导入", "规格书导入", "Windows 工位导入 PDF / Word / Excel，单份处理", "8–9 月"),
        ("1.2", "出表", "约 5 分钟出表", "数字稿约 5 分钟；扫描件约 8 分钟", "8–9 月"),
        ("1.3", "核对", "可溯源 + 待复核", "值 / 页码 / 原文；黄底待复核；无原文依据不填写", "8–9 月"),
        ("1.4", "配置", "表头可配置", "按极光湾底稿出表；中 / 英 / 德择一处理", "8–9 月"),
        ("1.5", "部署", "本机识别", "规格书不出公网，识别在本机完成", "8–9 月"),
        ("grp", "B · 全年延伸交付", "与工具并行推进，各月底出稿确认"),
        ("2.1", "拆解", "功能落地拆解", "功能维度划分，约 1～2 周", "9 月底"),
        ("2.2", "接口", "IO 口规划", "接口 / 端口命名与限制", "10 月底"),
        ("2.3", "企标", "测试项对比", "企标测试项 + 测试清单对比", "11 月底"),
        ("2.4", "物料", "CE BOM", "CE BOM Excel（BOM / 物料表形态）", "12 月底"),
    ]
    top = Inches(1.52)
    x0 = ML
    h_head = Inches(0.32)
    h_row = Inches(0.38)
    h_grp = Inches(0.34)
    # header
    x = x0
    for w, htxt in zip(widths, headers):
        rect(s, x, top, w, h_head, SURFACE4, RULE2)
        box(s, x + Inches(0.06), top, w - Inches(0.08), h_head, htxt, size=9, color=INK3, anchor=MSO_ANCHOR.MIDDLE, name="Calibri")
        x += w
    y = top + h_head
    for row in rows:
        if row[0] == "grp":
            rect(s, x0, y, sum(widths, Emu(0)), h_grp, SURFACE4, RULE)
            inset_bar(s, x0, y, h_grp)
            box(s, x0 + Inches(0.18), y, Inches(4), h_grp, row[1], size=12, bold=True, color=INK, anchor=MSO_ANCHOR.MIDDLE)
            box(s, x0 + Inches(4.2), y, Inches(7), h_grp, row[2], size=11, color=INK3, anchor=MSO_ANCHOR.MIDDLE)
            y += h_grp
            continue
        no, mod, fn, ds, node = row
        x = x0
        cells = [no, mod, fn, ds, node]
        sizes = [10, 11, 12, 11, 10]
        bolds = [True, False, True, False, False]
        colors = [ACCENT, INK3, INK, INK2, INK2]
        for i, (w, cell) in enumerate(zip(widths, cells)):
            rect(s, x, y, w, h_row, SURFACE if i else SURFACE, RULE2)
            box(
                s,
                x + Inches(0.06),
                y,
                w - Inches(0.08),
                h_row,
                cell,
                size=sizes[i],
                bold=bolds[i],
                color=colors[i],
                anchor=MSO_ANCHOR.MIDDLE,
                name="Calibri" if i in (0, 4) else "微软雅黑",
            )
            x += w
        y += h_row


def architecture(prs, n, total):
    s = new_slide(prs)
    rail(s, f"{n:02d}", "Architecture")
    eyebrow(s, "二 · 架构图")
    title(s, "工位本机闭环", size=26)
    sub(s, "规格书不出公网，识别在本机完成  ·  全年双线并行")

    # 工位带
    rect(s, ML, Inches(1.52), Inches(11.4), Inches(3.55), SURFACE3, RULE)
    inset_bar(s, ML, Inches(1.52), Inches(3.55), STEEL)
    box(s, ML + Inches(0.22), Inches(1.58), Inches(7.0), Inches(0.32), "工位电脑  Windows 10/11  ·  程序与模型均装在本机", size=12, bold=True, color=INK)
    box(s, ML + Inches(8.55), Inches(1.58), Inches(2.6), Inches(0.32), "规格书不出公网", size=12, bold=True, color=ACCENT, align=PP_ALIGN.RIGHT)

    cols = [
        ("输入", "规格书单份导入\nPDF / Word / Excel\n中 · 英 · 德 择一\n扫描件本机 OCR"),
        ("① 本机读取", "解析正文 / 表格\n保留页码"),
        ("② 本机识别", "本地模型按底稿\n一次抽取"),
        ("③ 本机出表", "值 + 页码 + 原文\n+ 置信度"),
        ("输出", "可核对 Excel\n黄底 = 待复核\n待核对 / 通过 / 需修改"),
    ]
    for i, (k, v) in enumerate(cols):
        left = ML + Inches(0.28) + Inches(i * 2.22)
        wash = ACCENT_WASH if i in (0, 4) else SURFACE
        bcol = ACCENT if i in (0, 4) else RULE
        rect(s, left, Inches(2.05), Inches(2.08), Inches(2.75), wash, bcol)
        box(s, left + Inches(0.1), Inches(2.15), Inches(1.88), Inches(0.4), k, size=13, bold=True, color=ACCENT if i in (0, 4) else INK)
        box(s, left + Inches(0.1), Inches(2.58), Inches(1.88), Inches(2.05), v, size=12, color=INK2)

    # 双线
    rect(s, ML, Inches(5.25), Inches(5.55), Inches(1.55), SURFACE3, RULE)
    inset_bar(s, ML, Inches(5.25), Inches(1.55), STEEL)
    box(s, ML + Inches(0.22), Inches(5.35), Inches(5.15), Inches(0.32), "线 A  ·  SOR 填表工具", size=13, bold=True, color=INK)
    box(s, ML + Inches(0.22), Inches(5.72), Inches(5.15), Inches(0.9), "8–9 月上线  ·  工位本机部署  ·  按上图读 → 抽 → 出 → 核", size=12, color=INK2)

    rect(s, ML + Inches(5.85), Inches(5.25), Inches(5.55), Inches(1.55), SURFACE3, RULE)
    inset_bar(s, ML + Inches(5.85), Inches(5.25), Inches(1.55), ACCENT)
    box(s, ML + Inches(6.07), Inches(5.35), Inches(5.15), Inches(0.32), "线 B  ·  延伸交付（独立成果）", size=13, bold=True, color=INK)
    box(
        s,
        ML + Inches(6.07),
        Inches(5.72),
        Inches(5.15),
        Inches(0.9),
        "功能拆解 → IO 口规划 → 企标对比 → CE BOM\n不纳入填表工具功能范围；各月底出稿确认",
        size=12,
        color=INK2,
    )


def solution(prs, n, total):
    s = new_slide(prs)
    rail(s, f"{n:02d}", "Plan")
    eyebrow(s, "三 · 方案")
    title(s, "读 → 抽 → 出 → 核", size=26)
    sub(s, "一期固定流程出表  ·  延伸：明确需求 → 出稿 → 当月确认")

    steps = [
        ("01", "读", "本机解析 PDF / Word / Excel；扫描件本机 OCR。"),
        ("02", "抽", "按底稿一次结构化抽取；无原文依据不填写。"),
        ("03", "出", "核对表含值、页码、原文、置信度；黄底待复核。"),
        ("04", "核", "Excel 标注待核对 / 通过 / 需修改；反馈页码与正确值。"),
    ]
    for i, (num, k, desc) in enumerate(steps):
        left = ML + Inches(i * 2.9)
        rect(s, left, Inches(1.58), Inches(2.75), Inches(1.55), SURFACE3, RULE)
        inset_bar(s, left, Inches(1.58), Inches(1.55))
        box(s, left + Inches(0.16), Inches(1.64), Inches(1.2), Inches(0.28), num, size=11, bold=True, color=ACCENT, name="Calibri")
        box(s, left + Inches(0.16), Inches(1.92), Inches(2.4), Inches(0.32), k, size=16, bold=True, color=INK)
        box(s, left + Inches(0.16), Inches(2.28), Inches(2.45), Inches(0.72), desc, size=11, color=INK2)

    box(s, ML, Inches(3.28), Inches(11.4), Inches(0.28), "延伸交付  ·  功能拆解 / IO / 企标 / CE BOM（独立交付）", size=11, color=INK3, name="Calibri")
    ext = [
        ("1  明确需求", "院方提供项目口径、接口约定、企标与测试项、BOM 形态要求"),
        ("2  出成果", "KMind 按节点输出拆解稿 / IO 规划 / 对比表 / CE BOM Excel"),
        ("3  当月确认", "月底前出稿；院方当周审核确认后，进入下一节点"),
    ]
    for i, (k, v) in enumerate(ext):
        left = ML + Inches(i * 3.85)
        rect(s, left, Inches(3.62), Inches(3.7), Inches(1.15), SURFACE, RULE)
        inset_bar(s, left, Inches(3.62), Inches(1.15), STEEL)
        box(s, left + Inches(0.18), Inches(3.7), Inches(3.4), Inches(0.32), k, size=13, bold=True, color=INK)
        box(s, left + Inches(0.18), Inches(4.05), Inches(3.4), Inches(0.6), v, size=11, color=INK2)

    notes = [
        ("一期验收", "PDF 基本参数 → Word 表内一致 → 扫描件可出表；9/15 功能确认，9/30 正式交付"),
        ("准确率", "9/15 功能确认不考核准确率；准确率以标准答案复核后另行约定"),
        ("不做范围", "整文件夹批量、直接写旧表、自动报价/回客户、网页端及现有系统对接（本期不纳入）"),
    ]
    for i, (k, v) in enumerate(notes):
        y = Inches(4.95) + Inches(i * 0.58)
        rect(s, ML, y, Inches(11.4), Inches(0.52), SURFACE4, RULE)
        inset_bar(s, ML, y, Inches(0.52), STEEL if i else ACCENT)
        box(s, ML + Inches(0.2), y, Inches(1.55), Inches(0.52), k, size=12, bold=True, color=INK, anchor=MSO_ANCHOR.MIDDLE)
        box(s, ML + Inches(1.85), y, Inches(9.3), Inches(0.52), v, size=12, color=INK2, anchor=MSO_ANCHOR.MIDDLE)


def cooperation(prs, n, total):
    s = new_slide(prs)
    rail(s, f"{n:02d}", "Plan")
    eyebrow(s, "三 · 方案")
    title(s, "双方配合与工位条件", size=26)
    sub(s, "启动资料齐套后推进研制；工位条件满足后进行试装交付")

    rect(s, ML, Inches(1.52), Inches(5.55), Inches(3.15), SURFACE3, RULE)
    inset_bar(s, ML, Inches(1.52), Inches(3.15))
    box(s, ML + Inches(0.2), Inches(1.58), Inches(5.15), Inches(0.32), "启动需提供（院方）", size=13, bold=True, color=INK)
    mats = [
        ("01", "现用填表", "正在使用的空表或已填表示例"),
        ("02", "出表底稿", "目标 Excel 列名、分组初稿"),
        ("03", "真规格书 ≥3 份", "建议英 PDF、中 Word、扫描件各一"),
        ("04", "脱敏口径", "样例是否脱敏；电压等参数勿涂改"),
    ]
    for i, (num, t, d) in enumerate(mats):
        y = Inches(2.0) + Inches(i * 0.62)
        box(s, ML + Inches(0.22), y, Inches(0.5), Inches(0.5), num, size=12, bold=True, color=ACCENT, anchor=MSO_ANCHOR.MIDDLE, name="Calibri")
        box(s, ML + Inches(0.75), y, Inches(4.55), Inches(0.26), t, size=13, bold=True, color=INK)
        box(s, ML + Inches(0.75), y + Inches(0.26), Inches(4.55), Inches(0.26), d, size=11, color=INK2)

    right = ML + Inches(5.85)
    rect(s, right, Inches(1.52), Inches(5.55), Inches(3.15), SURFACE3, RULE)
    inset_bar(s, right, Inches(1.52), Inches(3.15), STEEL)
    box(s, right + Inches(0.2), Inches(1.58), Inches(5.15), Inches(0.32), "工位部署条件", size=13, bold=True, color=INK)
    env = [
        ("系统", "Windows 10 / 11（64 位）"),
        ("内存", "建议 16GB 及以上"),
        ("磁盘", "预留约 10GB（含本机模型）"),
        ("网络", "识别阶段可断公网；规格书不上传"),
        ("权限", "试装工位需安装与运行权限"),
    ]
    for i, (k, v) in enumerate(env):
        y = Inches(2.0) + Inches(i * 0.5)
        rect(s, right + Inches(0.2), y, Inches(1.15), Inches(0.4), SURFACE4, RULE2)
        box(s, right + Inches(0.2), y, Inches(1.15), Inches(0.4), k, size=11, bold=True, color=INK, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        box(s, right + Inches(1.5), y, Inches(3.8), Inches(0.4), v, size=12, color=INK2, anchor=MSO_ANCHOR.MIDDLE)

    box(s, ML, Inches(4.82), Inches(11.4), Inches(0.26), "全年确认节点  ·  院方当周审核确认", size=11, color=INK3, name="Calibri")
    nodes = [
        ("9/15", "SOR 功能确认"),
        ("9/30", "SOR 正式交付"),
        ("10/31", "IO 口规划确认"),
        ("11/30", "企标对比确认"),
        ("12/31", "CE BOM 确认"),
    ]
    for i, (d, t) in enumerate(nodes):
        left = ML + Inches(i * 2.32)
        rect(s, left, Inches(5.16), Inches(2.18), Inches(1.45), SURFACE3, RULE)
        inset_bar(s, left, Inches(5.16), Inches(1.45), ACCENT if i else STEEL)
        box(s, left + Inches(0.14), Inches(5.28), Inches(1.9), Inches(0.4), d, size=18, bold=True, color=INK, name="Calibri")
        box(s, left + Inches(0.14), Inches(5.72), Inches(1.9), Inches(0.7), t, size=13, color=INK2)


def gantt(slide, left0, top0, width, row_h, start, end, ticks, tasks, name_w=Inches(2.35)):
    days = max((end - start).days, 1)
    for d, label in ticks:
        x = left0 + int(width * ((d - start).days / days))
        rect(slide, x, top0 - Inches(0.12), Pt(1), Inches(0.1), RULE)
        box(slide, x - Inches(0.35), top0 - Inches(0.36), Inches(0.8), Inches(0.22), label, size=9, color=INK3, align=PP_ALIGN.CENTER, name="Calibri")
    for i, (name, a, b, color) in enumerate(tasks):
        y = top0 + i * row_h
        if i % 2:
            rect(slide, ML, y, Inches(11.4), row_h, SURFACE3)
        box(slide, ML + Inches(0.08), y, name_w, row_h, name, size=11, bold=True, color=INK, anchor=MSO_ANCHOR.MIDDLE)
        x1 = left0 + int(width * (max((a - start).days, 0) / days))
        w = max(int(width * (max((b - a).days, 1) / days)), int(Inches(0.12)))
        rect(slide, x1, y + row_h * 0.28, w, row_h * 0.44, color)


def plan_gantt(prs, n, total):
    s = new_slide(prs)
    rail(s, f"{n:02d}", "Roadmap")
    eyebrow(s, "四 · 开发计划")
    title(s, "甘特  ·  8–12 月", size=26)
    legend = [(KM, "钢蓝 · KMind 研制"), (JG, "陶土 · 院方审核确认"), (MILE, "深橙 · 里程碑节点")]
    lx = ML
    for color, label in legend:
        rect(s, lx, Inches(1.22), Inches(0.28), Inches(0.14), color)
        box(s, lx + Inches(0.36), Inches(1.16), Inches(3.1), Inches(0.26), label, size=11, color=INK2, anchor=MSO_ANCHOR.MIDDLE)
        lx += Inches(3.55)
    start, end = date(2026, 8, 21), date(2026, 12, 31)
    ticks = [
        (date(2026, 8, 21), "8/21"),
        (date(2026, 9, 15), "9/15"),
        (date(2026, 9, 30), "9/30"),
        (date(2026, 10, 31), "10/31"),
        (date(2026, 11, 30), "11/30"),
        (date(2026, 12, 31), "12/31"),
    ]
    tasks = [
        ("SOR 填表研制", date(2026, 8, 21), date(2026, 9, 30), KM),
        ("功能确认", date(2026, 9, 15), date(2026, 9, 15), MILE),
        ("SOR 正式交付", date(2026, 9, 28), date(2026, 9, 30), MILE),
        ("功能落地拆解", date(2026, 9, 15), date(2026, 9, 30), KM),
        ("IO 口规划", date(2026, 10, 1), date(2026, 10, 31), KM),
        ("企标测试对比", date(2026, 11, 1), date(2026, 11, 30), KM),
        ("CE BOM 交付", date(2026, 12, 1), date(2026, 12, 31), KM),
        ("院方确认（9/15）", date(2026, 9, 15), date(2026, 9, 15), JG),
        ("院方确认（9/30）", date(2026, 9, 28), date(2026, 9, 30), JG),
        ("院方确认（10/31）", date(2026, 10, 31), date(2026, 10, 31), JG),
        ("院方确认（11/30）", date(2026, 11, 30), date(2026, 11, 30), JG),
        ("院方确认（12/31）", date(2026, 12, 31), date(2026, 12, 31), JG),
    ]
    gantt(s, Inches(3.55), Inches(1.72), Inches(8.9), Inches(0.38), start, end, ticks, tasks)
    rect(s, ML, Inches(6.45), Inches(11.4), Inches(0.48), ACCENT_WASH, RULE)
    inset_bar(s, ML, Inches(6.45), Inches(0.48))
    box(
        s,
        ML + Inches(0.18),
        Inches(6.5),
        Inches(11.05),
        Inches(0.38),
        "节点：9/15 SOR 功能确认  ·  9/30 SOR 交付及功能拆解确认  ·  10/31 IO  ·  11/30 企标对比  ·  12/31 CE BOM。",
        size=11,
        color=INK2,
        anchor=MSO_ANCHOR.MIDDLE,
    )


def plan_detail(prs, n, total):
    s = new_slide(prs)
    rail(s, f"{n:02d}", "Roadmap")
    eyebrow(s, "四 · 开发计划")
    title(s, "SOR 一期周计划", size=26)
    sub(s, "2026-08-21 — 09-30（第一阶段）")
    legend = [(KM, "钢蓝 · 研制阶段"), (JG, "陶土 · 以院方为主"), (MILE, "深橙 · 里程碑")]
    lx = ML
    y_leg = Inches(1.42)
    for color, label in legend:
        rect(s, lx, y_leg + Inches(0.06), Inches(0.28), Inches(0.14), color)
        box(s, lx + Inches(0.36), y_leg, Inches(3.0), Inches(0.26), label, size=11, color=INK2, anchor=MSO_ANCHOR.MIDDLE)
        lx += Inches(3.55)
    start, end = date(2026, 8, 21), date(2026, 9, 30)
    ticks = [
        (date(2026, 8, 21), "8/21"),
        (date(2026, 8, 31), "8/31"),
        (date(2026, 9, 7), "9/7"),
        (date(2026, 9, 15), "9/15"),
        (date(2026, 9, 21), "9/21"),
        (date(2026, 9, 30), "9/30"),
    ]
    tasks = [
        ("资料收集与底稿确认（双方）", date(2026, 8, 21), date(2026, 8, 25), KM),
        ("英文 PDF 出表与复核", date(2026, 8, 24), date(2026, 8, 30), KM),
        ("Word / 扫描件出表与复核", date(2026, 8, 31), date(2026, 9, 6), KM),
        ("操作界面可用与业务试用", date(2026, 9, 7), date(2026, 9, 13), KM),
        ("功能确认", date(2026, 9, 15), date(2026, 9, 15), MILE),
        ("标准答案调优", date(2026, 9, 16), date(2026, 9, 20), KM),
        ("工位试装", date(2026, 9, 21), date(2026, 9, 27), KM),
        ("正式交付", date(2026, 9, 28), date(2026, 9, 30), MILE),
    ]
    gantt(s, Inches(3.9), Inches(1.95), Inches(8.55), Inches(0.52), start, end, ticks, tasks, name_w=Inches(2.7))
    rect(s, ML, Inches(6.45), Inches(11.4), Inches(0.48), SURFACE4, RULE)
    inset_bar(s, ML, Inches(6.45), Inches(0.48), STEEL)
    box(
        s,
        ML + Inches(0.18),
        Inches(6.5),
        Inches(11.05),
        Inches(0.38),
        "各研制阶段均含院方同期配合（交资料 / 复核反馈 / 试用）；深橙为确认与交付节点。",
        size=12,
        color=INK2,
        anchor=MSO_ANCHOR.MIDDLE,
    )


def outlook(prs, n, total):
    s = new_slide(prs)
    rail(s, f"{n:02d}", "Outlook")
    eyebrow(s, "五 · 展望")
    title(s, "原理图 / 布局检查单", size=26)
    sub(s, "2027 年  ·  本年五项交付完成后推进  ·  不纳入 2026 年交付与验收")

    cards = [
        (
            "01",
            "原理图 / 布局检查单",
            "对原理图与布局输出可核对的检查单，辅助工程人员排查与确认。",
            "对应落地计划中「原理图/布局检查单」。启动时再明确检查项与样例范围。",
        ),
        (
            "02",
            "方案对比",
            "在检查单基础上做方案对比，支撑选型与改版决策。",
            "对应落地计划中「方案对比」。对比维度与输出形态届时与院方确认。",
        ),
    ]
    for i, (num, k, lead, note) in enumerate(cards):
        left = ML + Inches(i * 5.85)
        rect(s, left, Inches(1.65), Inches(5.55), Inches(3.55), SURFACE3, RULE)
        inset_bar(s, left, Inches(1.65), Inches(3.55))
        box(s, left + Inches(0.22), Inches(1.8), Inches(1.2), Inches(0.32), num, size=14, bold=True, color=ACCENT, name="Calibri")
        box(s, left + Inches(0.22), Inches(2.25), Inches(5.1), Inches(0.55), k, size=18, bold=True, color=INK)
        box(s, left + Inches(0.22), Inches(2.9), Inches(5.1), Inches(1.0), lead, size=14, color=INK)
        box(s, left + Inches(0.22), Inches(4.1), Inches(5.1), Inches(0.85), note, size=12, color=INK2)

    rect(s, ML, Inches(5.5), Inches(11.4), Inches(1.2), SURFACE4, RULE)
    inset_bar(s, ML, Inches(5.5), Inches(1.2), STEEL)
    box(s, ML + Inches(0.22), Inches(5.62), Inches(11.0), Inches(0.28), "配合与边界", size=12, bold=True, color=INK)
    box(
        s,
        ML + Inches(0.22),
        Inches(5.98),
        Inches(11.0),
        Inches(0.55),
        "到时再要资料、再验收。资料清单与验收标准届时另定；不挤占 2026 年 8–12 月节点，亦不纳入本年验收。",
        size=14,
        color=INK2,
    )


def main() -> None:
    prs = Presentation()
    prs.slide_width = W
    prs.slide_height = H
    slides = [
        cover,
        toc,
        features,
        architecture,
        solution,
        cooperation,
        plan_gantt,
        plan_detail,
        outlook,
    ]
    cover(prs)
    for i, fn in enumerate(slides[1:], start=2):
        fn(prs, i, len(slides))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(f"wrote {OUT} ({len(slides)} slides)")


if __name__ == "__main__":
    main()
