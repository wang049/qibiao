"""电子电器 · SOR填表 · 实现逻辑汇报。版式对齐方案稿：左轨、陶土强调、大标题。"""
from __future__ import annotations

from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

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

W = Inches(13.333)
H = Inches(7.5)
RAIL = Inches(0.67)
ML = Inches(1.12)
TW = Inches(11.4)
N_SLIDES = 15
OUT = Path("/Users/wwj/Desktop/电子电器SOR填表-实现逻辑汇报.pptx")


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


def code_lines(slide, l, t, w, h, lines, size=14, color=INK):
    tb = slide.shapes.add_textbox(l, t, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        p.space_after = Pt(6)
        if i == 0:
            p.clear()
        _font(p.add_run(), line, size, False, color, "Consolas")
    return tb


def new_slide(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def _vert(shape):
    body = shape.text_frame._txBody.find(qn("a:bodyPr"))
    if body is not None:
        body.set("vert", "eaVert")


def notes(slide, text: str) -> None:
    """备注给自己看：PowerPoint 视图 → 备注。"""
    slide.notes_slide.notes_text_frame.text = text.strip() + "\n"


def rail(slide, num: str, sec: str, brand: str = "kMind"):
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
    box(slide, ML, Inches(0.32), TW, Inches(0.28), text.upper(), size=10, color=INK3, name="Calibri")


def title(slide, text, size=28):
    box(slide, ML, Inches(0.58), TW, Inches(0.52), text, size=size, bold=True, color=INK)


def sub(slide, text, y=Inches(1.12)):
    box(slide, ML, y, TW, Inches(0.32), text, size=12, color=INK2)


def inset_bar(slide, l, t, h, color=ACCENT):
    rect(slide, l, t, Pt(3), h, color)


def footer(slide, left: str, right: str | None = None):
    rect(slide, ML, Inches(7.18), TW, Pt(1), RULE)
    box(slide, ML, Inches(7.22), Inches(8.2), Inches(0.24), left, size=10, color=INK3, name="Calibri")
    if right:
        box(
            slide,
            Inches(9.5),
            Inches(7.22),
            Inches(3.0),
            Inches(0.24),
            right,
            size=10,
            color=INK3,
            align=PP_ALIGN.RIGHT,
            name="Calibri",
        )


def cover(prs):
    s = new_slide(prs)
    rail(s, "01", "Cover")
    for i in range(10, 28):
        x = Inches(i * 0.44)
        if x < W:
            rect(s, x, 0, Pt(0.6), H, RULE2)
    for j in range(0, 18):
        y = Inches(j * 0.44)
        if y < H:
            rect(s, RAIL, y, W - RAIL, Pt(0.6), RULE2)
    rect(s, RAIL, 0, Inches(8.15), H, SURFACE)
    rect(s, ML, Inches(1.72), Inches(0.4), Pt(3), ACCENT)
    box(
        s,
        ML + Inches(0.52),
        Inches(1.62),
        Inches(8),
        Inches(0.28),
        "kMind  ·  极光湾电子电器开发中心",
        size=11,
        color=INK3,
        name="Calibri",
    )
    tb = s.shapes.add_textbox(ML, Inches(2.05), Inches(10.6), Inches(2.15))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.clear()
    r = p.add_run()
    _font(r, "电子电器 · ", 40, True, INK)
    r2 = p.add_run()
    _font(r2, "SOR填表", 40, True, ACCENT)
    p2 = tf.add_paragraph()
    p2.space_before = Pt(10)
    r3 = p2.add_run()
    _font(r3, "实现逻辑", 40, True, INK)
    box(
        s,
        ML,
        Inches(4.45),
        Inches(10.2),
        Inches(0.85),
        "工位电脑导入规格书，本机出可核对 Excel。规格书不出公网。\n抽出值须对原文；专有云可作为指定场所另做，不替代本期工位交付。",
        size=16,
        color=INK2,
    )
    rect(s, ML, Inches(6.55), Inches(11.4), Pt(1), RULE)
    box(
        s,
        ML,
        Inches(6.7),
        Inches(8.4),
        Inches(0.28),
        "产品口径  ·  架构  ·  流水线  ·  读取  ·  样张  ·  工位操作  ·  专有云  ·  每页有备注",
        size=11,
        color=INK3,
        name="Calibri",
    )
    box(s, Inches(9.2), Inches(6.7), Inches(1.6), Inches(0.28),         "2026-08-27  ·  15 页", size=11, color=INK3, name="Calibri")
    box(s, Inches(11.0), Inches(6.65), Inches(1.5), Inches(0.32), "kMind", size=16, bold=True, color=INK, name="Calibri")
    notes(
        s,
        "【这一页】封面。产品名：电子电器 · SOR填表。\n\n"
        "【自己怎么理解】客户规格书里的参数，按甲方确认的核对表模板填报。"
        "这是工位电脑上的出表程序。"
        "规格书不出公网 = 文件不上传互联网、不调用公网识别。\n\n"
        "【记住】本期交工位本机。甲方指定专有云是另一条路，见第 11–12 页。\n\n"
        "【看备注】后面每页都有白话。PowerPoint：视图 → 备注。",
    )


def toc(prs, n, total):
    s = new_slide(prs)
    rail(s, f"{n:02d}", "Index")
    eyebrow(s, "目录")
    title(s, "十块结构")
    sub(s, "从产品口径讲到工位怎么开、怎么点；专有云单独成块，不和本期工位交付混在一起")
    items = [
        ("01", "PRODUCT", "产品与口径", "工位出表；抽出值须对原文"),
        ("02", "ARCHITECTURE", "三层架构", "本机页面 · 出表服务 · 本机大模型"),
        ("03", "PIPELINE", "端到端流程", "读文件 → 分流 → 抽取 → 出表"),
        ("04", "CLASSIFY", "文件分流", "先定性，再决定是否按模板抽取"),
        ("05", "EXTRACT", "抽取与保准", "规则先填，模型补空，对不上就空"),
        ("06", "SDK", "文件读取", "本机解析办公文件，不调用公网"),
        ("07", "SAMPLES", "六份样张", "哪份主验收、哪份空表是对的"),
        ("08", "RUNTIME", "工位操作", "命令拉起 · 页面出表 · 时间花在模型"),
        ("09", "PRIVATE CLOUD", "专有云方案", "本期工位；专有云须书面确认"),
        ("10", "CLOSE", "汇报三句话", "本机 · 分流 · 保准"),
    ]
    for i, (num, en, zh, desc) in enumerate(items):
        col = i // 5
        row = i % 5
        left = ML + Inches(col * 5.85)
        y = Inches(1.52) + Inches(row * 1.02)
        rect(s, left, y, Inches(5.55), Inches(0.92), SURFACE3, RULE)
        inset_bar(s, left, y, Inches(0.92))
        box(
            s,
            left + Inches(0.2),
            y + Inches(0.08),
            Inches(1.0),
            Inches(0.76),
            num,
            size=18,
            bold=True,
            color=ACCENT,
            anchor=MSO_ANCHOR.MIDDLE,
            name="Calibri",
        )
        box(s, left + Inches(1.25), y + Inches(0.08), Inches(4.05), Inches(0.22), en, size=10, color=INK3, name="Calibri")
        box(s, left + Inches(1.25), y + Inches(0.30), Inches(4.05), Inches(0.28), zh, size=15, bold=True, color=INK)
        box(s, left + Inches(1.25), y + Inches(0.58), Inches(4.05), Inches(0.26), desc, size=11, color=INK2)
    notes(
        s,
        "【这一页】目录。质量在 04 分流 + 05 抽取；容易被追问的是 06 SDK 和 09 专有云。\n\n"
        "【自己怎么理解】先钉死「交什么、怎么算对」，再讲程序怎么跑。"
        "SDK 单独一页，避免别人以为规格书进了公网。\n\n"
        "【讲的时候】被问专有云，翻到 09，不要在架构页说已经上云。被问怎么开，翻到 08。",
    )


def product(prs, n, total):
    s = new_slide(prs)
    rail(s, f"{n:02d}", "Product")
    eyebrow(s, "一 · 产品与口径")
    title(s, "工位导入规格书，本机出核对表", size=26)
    sub(s, "按甲方确认的核对表模板填写，下载一张可核对 Excel")

    left = [
        ("做什么", "工位电脑导入 PDF / Word / Excel，本机抽取，下载核对表。一次只跑一份。"),
        ("交付形态", "按既定步骤出表。输出含抽出值、页码与原文摘录，供人工确认。"),
        ("人工怎么核", "只改黄格和空格。黄色表示待人工确认，不当场代填。"),
    ]
    for i, (k, v) in enumerate(left):
        y = Inches(1.58) + Inches(i * 1.55)
        rect(s, ML, y, Inches(5.55), Inches(1.42), SURFACE3, RULE)
        inset_bar(s, ML, y, Inches(1.42))
        box(s, ML + Inches(0.22), y + Inches(0.12), Inches(5.1), Inches(0.32), k, size=15, bold=True, color=INK)
        box(s, ML + Inches(0.22), y + Inches(0.5), Inches(5.1), Inches(0.78), v, size=13, color=INK2)

    right = ML + Inches(5.85)
    rect(s, right, Inches(1.58), Inches(5.55), Inches(4.52), ACCENT_WASH, ACCENT)
    inset_bar(s, right, Inches(1.58), Inches(4.52))
    box(s, right + Inches(0.24), Inches(1.74), Inches(5.1), Inches(0.36), "质量口径", size=16, bold=True, color=ACCENT)
    lines = [
        "抽出值必须对得上原文。",
        "对不上则留空或标为待确认，不得静默填写。",
        "验收看已填项是否可追溯，不要求格格填满。",
        "ESOW、变速器 SR 整表不适用，空表是分流正确。",
    ]
    for i, line in enumerate(lines):
        y = Inches(2.28) + Inches(i * 0.88)
        box(s, right + Inches(0.24), y, Inches(0.4), Inches(0.7), f"{i + 1:02d}", size=16, bold=True, color=ACCENT, anchor=MSO_ANCHOR.MIDDLE, name="Calibri")
        box(s, right + Inches(0.72), y, Inches(4.55), Inches(0.7), line, size=14, color=INK, anchor=MSO_ANCHOR.MIDDLE)
    notes(
        s,
        "【这一页】产品是什么，以及怎么算抽对了。\n\n"
        "【已检索到】格子里有值，能在这份规格书原文找到对应句子，并且和这条清单是同一件事。"
        "例如原文写了最高转速，不能填进「P1 转速需求」。\n\n"
        "【未检索到 / 空着】原文没有、或对不上条目。留空优于误填。不要求格格填满。\n\n"
        "【黄格】待人工确认：空值，或程序没把握。不当场替填需要人工写的格子。\n\n"
        "【空表】ESOW、变速器 SR 不按电控核对表抽取，整表「不适用」是分流对了，不是故障。",
    )


def architecture(prs, n, total):
    s = new_slide(prs)
    rail(s, f"{n:02d}", "Architecture")
    eyebrow(s, "二 · 三层架构")
    title(s, "本期：全部留在工位本机", size=26)
    sub(s, "页面只传文件、查进度、下载表  ·  规格书不到公网  ·  专有云见第 09 块")

    layers = [
        ("01", "页面", "本机浏览器  ·  127.0.0.1:8765", "选文件、看进度、下载核对表。只监听本机，外网打不进来。"),
        ("02", "出表服务", "Python 程序，本机 8765 端口", "读文件 → 分流 → 抽取 → 写 Excel。同时只跑一份，避免抢模型。"),
        ("03", "本机模型", "工位本地大模型", "只访问本机地址。不调用公网识别服务。"),
    ]
    for i, (num, name, en, desc) in enumerate(layers):
        y = Inches(1.55) + Inches(i * 1.55)
        rect(s, ML, y, TW, Inches(1.42), SURFACE3, RULE)
        inset_bar(s, ML, y, Inches(1.42), STEEL if i != 2 else ACCENT)
        box(s, ML + Inches(0.22), y + Inches(0.18), Inches(1.1), Inches(1.05), num, size=22, bold=True, color=ACCENT, anchor=MSO_ANCHOR.MIDDLE, name="Calibri")
        box(s, ML + Inches(1.45), y + Inches(0.18), Inches(3.4), Inches(0.4), name, size=20, bold=True, color=INK)
        box(s, ML + Inches(1.45), y + Inches(0.62), Inches(4.2), Inches(0.55), en, size=13, color=INK3)
        box(s, ML + Inches(5.9), y + Inches(0.22), Inches(5.2), Inches(1.0), desc, size=14, color=INK2, anchor=MSO_ANCHOR.MIDDLE)
    notes(
        s,
        "【这一页】程序装在哪、模型装在哪。三层都在同一台工位电脑上。\n\n"
        "【页面】浏览器打开 http://127.0.0.1:8765/ 。127.0.0.1 表示只听这台机器，旁边电脑和外网都打不进来。\n\n"
        "【出表服务】真正干活的 Python：读 PDF/Word、判断类型、按模板抽取、写 Excel。\n\n"
        "【本机模型】工位电脑上的本地大模型。对外说本机大模型，不要报第三方产品名。"
        "抽取时程序把「一段原文 + 仍空的条目」发给它。\n\n"
        "【不要】调用公网识别。配错地址程序会拒绝，防止规格书出网。\n\n"
        "【被问专有云】甲方指定专有云可另做。出表仍走分段补全，见第 11–12 页。这一页讲的是本期工位。",
    )


def pipeline(prs, n, total):
    s = new_slide(prs)
    rail(s, f"{n:02d}", "Pipeline")
    eyebrow(s, "三 · 端到端流程")
    title(s, "读 → 分流 → 抽 → 出", size=26)
    sub(s, "数字稿读取约数秒；时间主要花在本机模型分段补空")

    steps = [
        ("01", "读", "把 PDF/Word/Excel 转成带「第 N 页」的文本。扫描件、表图用本机 OCR 认字。这一步不用模型。"),
        ("02", "分流", "先看这是不是电控规格。ESOW、变速器 SR、目录页整表标不适用，不按电控核对表硬抽。"),
        ("03", "抽", "规则能对上的先填。仍空的格子：规格书切成十几段，一段一段送给本机模型。对不上就空着。"),
        ("04", "出", "Excel：说明、电控设计需求（主核对）、清单外需求（对不上 1–120 的当份要求）、清单口径（模板字段说明，不是本份抽出值）。"),
    ]
    for i, (num, k, desc) in enumerate(steps):
        left = ML + Inches(i * 2.9)
        rect(s, left, Inches(1.58), Inches(2.75), Inches(3.55), SURFACE3, RULE)
        inset_bar(s, left, Inches(1.58), Inches(3.55))
        box(s, left + Inches(0.16), Inches(1.72), Inches(2.4), Inches(0.32), num, size=14, bold=True, color=ACCENT, name="Calibri")
        box(s, left + Inches(0.16), Inches(2.12), Inches(2.4), Inches(0.45), k, size=22, bold=True, color=INK)
        box(s, left + Inches(0.16), Inches(2.7), Inches(2.45), Inches(2.15), desc, size=13, color=INK2)

    rect(s, ML, Inches(5.32), TW, Inches(1.55), SURFACE4, RULE)
    inset_bar(s, ML, Inches(5.32), Inches(1.55), STEEL)
    box(s, ML + Inches(0.22), Inches(5.44), Inches(11.0), Inches(0.32), "核对表主表列", size=13, bold=True, color=INK)
    box(
        s,
        ML + Inches(0.22),
        Inches(5.82),
        Inches(11.0),
        Inches(0.85),
        "核对状态  ·  条目  ·  抽出值  ·  页码  ·  原文摘录  ·  人工填写  ·  置信度\n"
        "黄底 = 待人工确认。清单口径页是模板字段说明，不是本份抽出值。",
        size=14,
        color=INK2,
    )
    notes(
        s,
        "【这一页】一份文件从拖进去到下载表，固定四步。\n\n"
        "【读】SDK 阅读器 / 自制 Word 阅读。OCR = 把图里的字认出来，仍在本机，不上网。\n\n"
        "【分流】先定性。错把工作说明书当 DPR，就会胡填；所以宁可整表不适用。\n\n"
        "【抽 · 空缺再分段打本机模型】不是把整本丢给模型。\n"
        "空缺 = 规则填完后仍没有值的清单项。\n"
        "再 = 先规则、后模型；模型不准改已填的格。\n"
        "分段 = 本机模型一次吃不下整本，切成约 10～16 段，页面上会显示「第 3/14 段」。\n"
        "打本机模型 = 每段发给工位上的本地大模型。只准从本段原文抽仍空的项；对不上或不是同一件事就空着。\n\n"
        "【出】人工只改黄格和空格。清单口径页说明模板字段含义，不是这份规格书抽出来的数。",
    )


def classify(prs, n, total):
    s = new_slide(prs)
    rail(s, f"{n:02d}", "Classify")
    eyebrow(s, "四 · 文件分流")
    title(s, "先定性，再决定抽不抽", size=26)
    sub(s, "空表在 ESOW / 变速器 SR 上是分流正确，不是失败")

    headers = ["类型", "是否按模板抽取", "结果", "对应样张"]
    widths = [Inches(2.35), Inches(2.15), Inches(2.55), Inches(4.35)]
    rows = [
        ("电控 DPR", "抽", "按清单出核对表", "SuperEvo、DHTS160 DPR、扫描件 DPR"),
        ("逆变器 SR", "抽", "可出表，表图多、覆盖偏低", "Inverter SR from Outside.pdf"),
        ("工作说明书 ESOW", "不抽", "整表不适用", "DHTS160 ESOW.docx"),
        ("变速器 / 传动 SR", "不抽", "整表不适用", "Inverter SR from Outside-2.pdf"),
        ("目录页", "不抽", "整表不适用", "夹在规格书前的目录"),
    ]
    top = Inches(1.55)
    x0 = ML
    h_head = Inches(0.38)
    h_row = Inches(0.72)
    x = x0
    for w, htxt in zip(widths, headers):
        rect(s, x, top, w, h_head, SURFACE4, RULE)
        box(s, x + Inches(0.1), top, w - Inches(0.14), h_head, htxt, size=11, color=INK3, anchor=MSO_ANCHOR.MIDDLE)
        x += w
    for i, (kind, do, result, sample) in enumerate(rows):
        y = top + h_head + Inches(i * 0.72)
        fill = SURFACE3 if i % 2 else SURFACE
        cells = [kind, do, result, sample]
        x = x0
        for c, (w, cell) in enumerate(zip(widths, cells)):
            rect(s, x, y, w, h_row, fill, RULE2)
            color = INK
            bold = c == 0
            if c == 1:
                color = ACCENT if cell == "抽" else INK3
                bold = True
            box(
                s,
                x + Inches(0.1),
                y,
                w - Inches(0.14),
                h_row,
                cell,
                size=13 if c < 3 else 12,
                bold=bold,
                color=color,
                anchor=MSO_ANCHOR.MIDDLE,
            )
            x += w
    notes(
        s,
        "【这一页】不是每份文件都按电控核对表硬抽。先看文件是什么。\n\n"
        "【电控 DPR】设计前提 / 电控需求，如 SuperEvo、DHTS160 DPR、扫描件 DPR。这才是主场景。\n\n"
        "【逆变器 SR】供应商逆变器规格，可抽，但很多参数在图里，覆盖会低于数字稿 DPR。\n\n"
        "【ESOW】工作说明书，写谁干什么，不是参数表。空表 = 对。\n\n"
        "【Outside-2】文件名像逆变器，正文是变速器/传动。空表 = 对。\n\n"
        "【被问为什么空】先答分流，再谈抽取质量。不要先道歉说没抽出来。",
    )


def extract(prs, n, total):
    s = new_slide(prs)
    rail(s, f"{n:02d}", "Extract")
    eyebrow(s, "五 · 抽取与保准")
    title(s, "三道闸，依据不足则留空", size=26)
    sub(s, "全场景保准：数字稿、扫描件、逆变器 SR 都走规则 + 本机模型 + 拒绝误绑")

    cols = [
        ("01", "规则先填", "程序按原文固定格式抓数：电压、P1/P3 功率扭矩转速、放电、重量等。对得上就写。SuperEvo 多数准格来自这一步。"),
        ("02", "空缺再分段", "规则填完仍空的项，把长文切成约 10～16 段，逐段问本机模型。已填的不改。编造、本段找不到的都不写。"),
        ("03", "拒绝误绑", "原文里有这句话还不够，必须和这条清单是同一件事。对不上就「未检索到」。下面六条是典型错绑。"),
    ]
    for i, (num, k, v) in enumerate(cols):
        left = ML + Inches(i * 3.85)
        rect(s, left, Inches(1.55), Inches(3.7), Inches(3.05), SURFACE3, RULE)
        inset_bar(s, left, Inches(1.55), Inches(3.05))
        box(s, left + Inches(0.18), Inches(1.68), Inches(3.3), Inches(0.32), num, size=13, bold=True, color=ACCENT, name="Calibri")
        box(s, left + Inches(0.18), Inches(2.05), Inches(3.3), Inches(0.4), k, size=18, bold=True, color=INK)
        box(s, left + Inches(0.18), Inches(2.55), Inches(3.35), Inches(1.85), v, size=13, color=INK2)

    rejects = [
        ("UDC 13kW", "不当 P3 峰值功率"),
        ("充电纹波", "不当母线 / 高压安全"),
        ("Y 电容批准套话", "无 nF 不填"),
        ("逆变器 12.5 kHz", "不当加速踏板 PWM"),
        ("最高转速", "不当 P1/P3 转速需求"),
        ("过压英文流程句", "不当过压保护值"),
    ]
    for i, (a, b) in enumerate(rejects):
        col = i % 3
        row = i // 3
        left = ML + Inches(col * 3.85)
        y = Inches(4.78) + Inches(row * 0.95)
        rect(s, left, y, Inches(3.7), Inches(0.85), SURFACE4, RULE)
        inset_bar(s, left, y, Inches(0.85), ACCENT)
        box(s, left + Inches(0.18), y + Inches(0.08), Inches(3.35), Inches(0.32), a, size=13, bold=True, color=INK)
        box(s, left + Inches(0.18), y + Inches(0.42), Inches(3.35), Inches(0.32), b, size=12, color=INK2)
    notes(
        s,
        "【这一页】质量核心。三道闸缺一不可。数字稿也不跳过模型，是保准，不是为了赶时间。\n\n"
        "【规则】像用尺子量：原文出现「额定电压 650–900 V」这种确定句，直接写入对应格子。快、稳。\n\n"
        "【空缺再分段】规则填完可能还空几十格。本机模型一次看不完 100 页，所以切段。"
        "每一段只问：这些空格在本段有没有原文。页面「第 3/14 段」就是在等本机模型。这就是耗时的来源。\n\n"
        "【拒绝误绑】模型或规则可能把「邻近的数」塞进错误条目。程序会挡："
        "UDC 13kW 不是 P3 峰值；充电纹波不是母线纹波；逆变器开关频率不是踏板 PWM；最高转速不是转速需求。\n\n"
        "【扫描件 / 表图】覆盖偏低是预期。验收看已检索到的项能否对原文，不要求格格填满。",
    )


def sdk(prs, n, total):
    s = new_slide(prs)
    rail(s, f"{n:02d}", "SDK")
    eyebrow(s, "六 · 文件读取")
    title(s, "本机解析 PDF / Word / Excel", size=26)
    sub(s, "读取在工位完成，不调用公网文档服务")

    rect(s, ML, Inches(1.55), Inches(5.55), Inches(4.35), SURFACE3, RULE)
    inset_bar(s, ML, Inches(1.55), Inches(4.35), OK)
    box(s, ML + Inches(0.22), Inches(1.68), Inches(5.1), Inches(0.36), "读取做什么", size=16, bold=True, color=INK)
    used = [
        ("办公文件", "本机将 PDF / Excel 转为带页码文本。"),
        ("Word 表格", "按正文顺序读取表格，页码与目录对应。"),
        ("安装一次", "工位装好阅读能力后，不必再接公网文档服务。"),
        ("角色定位", "只负责把文件读成带页码的文本。这一步不调用模型。"),
    ]
    for i, (k, v) in enumerate(used):
        y = Inches(2.18) + Inches(i * 0.88)
        box(s, ML + Inches(0.22), y, Inches(5.1), Inches(0.28), k, size=14, bold=True, color=INK)
        box(s, ML + Inches(0.22), y + Inches(0.3), Inches(5.1), Inches(0.5), v, size=12, color=INK2)

    right = ML + Inches(5.85)
    rect(s, right, Inches(1.55), Inches(5.55), Inches(4.35), ACCENT_WASH, ACCENT)
    inset_bar(s, right, Inches(1.55), Inches(4.35))
    box(s, right + Inches(0.22), Inches(1.68), Inches(5.1), Inches(0.36), "抽取怎么做", size=16, bold=True, color=ACCENT)
    unused = [
        ("本机抽取", "规则先填，空缺由本机大模型分段补全。"),
        ("不出公网", "规格书不上传，不调用公网识别服务。"),
        ("可追溯", "已填项须能回到页码与原文；依据不足则留空。"),
        ("范围", "不接入甲方既有业务系统。"),
    ]
    for i, (k, v) in enumerate(unused):
        y = Inches(2.18) + Inches(i * 0.88)
        box(s, right + Inches(0.22), y, Inches(5.1), Inches(0.28), k, size=14, bold=True, color=INK)
        box(s, right + Inches(0.22), y + Inches(0.3), Inches(5.1), Inches(0.5), v, size=12, color=INK2)

    rect(s, ML, Inches(6.05), TW, Inches(0.85), SURFACE4, RULE)
    inset_bar(s, ML, Inches(6.05), Inches(0.85), STEEL)
    box(
        s,
        ML + Inches(0.22),
        Inches(6.18),
        Inches(11.0),
        Inches(0.6),
        "阅读在工位完成本机解析。结构表与图片 OCR 对照过：主路径仍用整页识别，不换。",
        size=13,
        color=INK2,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    notes(
        s,
        "【这一页】读取在本机完成。对外不讲产品名和密钥。\n\n"
        "【用到的】krow-agent-sdk[office] 自带 PDF/Excel 阅读器，Word 我们自己排顺序（默认阅读器页码对不上目录），只借用表格转文本。\n\n"
        "【抽取】空格补全走本机大模型接口。规格书不出公网。\n\n"
        "【对照过、结论】逆变器 SR、扫描件 DPR：现路径（Markdown+整页 OCR）vs SDK get_tables+图片回调。"
        "逆变器准格 28→16；扫描件 15→14。SuperEvo 主路径不换。\n\n"
        "【被问为什么装读取库】安装一次就能本机解析办公格式。",
    )


def samples(prs, n, total):
    s = new_slide(prs)
    rail(s, f"{n:02d}", "Samples")
    eyebrow(s, "七 · 六份样张")
    title(s, "哪份主验收，哪份空表是对的", size=26)
    sub(s, "演示时一次只出一份  ·  扫描件不当主验收")

    headers = ["样张", "类型", "汇报时怎么讲"]
    widths = [Inches(4.15), Inches(2.35), Inches(4.9)]
    rows = [
        ("SuperEvo（1000V）DPR", "电控 DPR 数字稿", "主验收。已检索到应对原文。"),
        ("DHTS160 DPR", "电控 DPR 数字稿", "备验收。同一口径，依据不足则留空。"),
        ("DHTS160 ESOW", "工作说明书", "只演示分流。空表是对的。"),
        ("Inverter SR from Outside-2", "变速器 / 传动 SR", "文件名像逆变器，内容不是。空表是对的。"),
        ("Inverter SR from Outside", "逆变器 SR", "可出表。表图多，覆盖偏低是预期。"),
        ("4LDHT260 扫描件 DPR", "电控 DPR 扫描件", "能分流、能出表。不当主验收。"),
    ]
    top = Inches(1.52)
    x0 = ML
    h_head = Inches(0.36)
    h_row = Inches(0.72)
    x = x0
    for w, htxt in zip(widths, headers):
        rect(s, x, top, w, h_head, SURFACE4, RULE)
        box(s, x + Inches(0.1), top, w - Inches(0.14), h_head, htxt, size=11, color=INK3, anchor=MSO_ANCHOR.MIDDLE)
        x += w
    for i, (name, kind, talk) in enumerate(rows):
        y = top + h_head + Inches(i * 0.72)
        fill = ACCENT_WASH if i == 0 else (SURFACE3 if i % 2 else SURFACE)
        x = x0
        cells = [name, kind, talk]
        for c, (w, cell) in enumerate(zip(widths, cells)):
            rect(s, x, y, w, h_row, fill, RULE2)
            color = ACCENT if i == 0 and c == 0 else INK
            box(
                s,
                x + Inches(0.1),
                y,
                w - Inches(0.14),
                h_row,
                cell,
                size=13 if c else 13,
                bold=(c == 0 or i == 0),
                color=color,
                anchor=MSO_ANCHOR.MIDDLE,
            )
            x += w
    notes(
        s,
        "【这一页】六份客户样张各自扮演什么角色。演示一次只出一份。\n\n"
        "【主验收】SuperEvo（1000V）DPR 数字稿。已检索到必须对原文。\n\n"
        "【备验收】DHTS160 DPR，同一口径。\n\n"
        "【只演示分流】ESOW、Inverter-2（变速器）。打开若是空表/不适用，主动说这是对的。\n\n"
        "【可出但不当主验收】逆变器 SR（表图多）；扫描件 DPR（OCR 覆盖低）。"
        "不要承诺和 SuperEvo 一样满。整页 OCR 优于 SDK 图片回调，主路径已按现方式做。",
    )


def operate_cmd(prs, n, total):
    s = new_slide(prs)
    rail(s, f"{n:02d}", "Runtime")
    eyebrow(s, "八 · 工位操作")
    title(s, "三条命令把出表开起来", size=26)
    sub(s, "本机模型服务先开着  ·  出表只听本机地址  ·  不调用公网识别")

    prereq = [
        ("本机模型", "本机大模型已装在工位，服务保持后台运行。页面顶部会显示是否就绪。"),
        ("运行环境", "工位已装好运行环境。不调用公网识别，不需要云端密钥。"),
        ("停掉", "关掉出表：在启动那条终端按 Ctrl+C。模型服务可继续留在后台。"),
    ]
    for i, (k, v) in enumerate(prereq):
        y = Inches(1.52) + Inches(i * 0.88)
        rect(s, ML, y, Inches(5.55), Inches(0.8), SURFACE3, RULE)
        inset_bar(s, ML, y, Inches(0.8), STEEL)
        box(s, ML + Inches(0.2), y + Inches(0.08), Inches(5.15), Inches(0.28), k, size=14, bold=True, color=INK)
        box(s, ML + Inches(0.2), y + Inches(0.36), Inches(5.15), Inches(0.38), v, size=12, color=INK2)

    right = ML + Inches(5.85)
    rect(s, right, Inches(1.52), Inches(5.55), Inches(3.52), SURFACE4, RULE)
    inset_bar(s, right, Inches(1.52), Inches(3.52), ACCENT)
    box(s, right + Inches(0.2), Inches(1.64), Inches(5.15), Inches(0.28), "终端里依次执行", size=14, bold=True, color=INK)
    code_lines(
        s,
        right + Inches(0.2),
        Inches(2.02),
        Inches(5.15),
        Inches(2.75),
        [
            "cd ~/电子电器项目/electrical",
            'export PATH="$HOME/.venv/bin:$HOME/.local/bin:$PATH"',
            "PYTHONPATH=. python -m electrical.backend",
        ],
        size=13,
    )

    rect(s, ML, Inches(4.28), TW, Inches(1.18), SURFACE3, RULE)
    inset_bar(s, ML, Inches(4.28), Inches(1.18), STEEL)
    box(s, ML + Inches(0.22), Inches(4.4), Inches(11.0), Inches(0.28), "起来之后", size=13, bold=True, color=INK)
    box(
        s,
        ML + Inches(0.22),
        Inches(4.72),
        Inches(11.0),
        Inches(0.58),
        "终端出现「工位本机出表（仅本机）」后，浏览器打开 http://127.0.0.1:8765/ 。"
        "加 --no-browser 则只起服务、不自动开页。工位 Windows 把目录换成安装路径即可。",
        size=13,
        color=INK2,
    )

    rect(s, ML, Inches(5.6), TW, Inches(1.28), ACCENT_WASH, ACCENT)
    inset_bar(s, ML, Inches(5.6), Inches(1.28))
    box(s, ML + Inches(0.22), Inches(5.72), Inches(11.0), Inches(0.28), "也可以不用页面，命令行出一份", size=13, bold=True, color=INK)
    code_lines(
        s,
        ML + Inches(0.22),
        Inches(6.08),
        Inches(11.0),
        Inches(0.62),
        ["PYTHONPATH=. python -m electrical /路径/规格书.pdf"],
        size=14,
    )
    notes(
        s,
        "【这一页】工程怎么起来。先开本机模型服务，再开出表服务。\n\n"
        "【三条命令】进项目目录 → 用本机虚拟环境的 Python → 启动 8765。"
        "PYTHONPATH=. 是为了在项目根直接跑包，不必先 pip install -e .\n\n"
        "【本机模型】对外说工位本地大模型、只访问本机地址。不要报第三方产品名。"
        "没开着时，页面健康检查会红，出表会失败。\n\n"
        "【不要】调用公网识别。命令行和页面不要同时跑两份，会抢同一台本机模型。\n\n"
        "【演示】这一页可以投屏对着终端敲；下一页对着浏览器点。",
    )


def operate_ui(prs, n, total):
    s = new_slide(prs)
    rail(s, f"{n:02d}", "Runtime")
    eyebrow(s, "八 · 工位操作")
    title(s, "浏览器里怎么出表", size=26)
    sub(s, "一次只跑一份  ·  跑完再传下一份  ·  黄格不当场代填")

    steps = [
        ("01", "打开页面", "地址栏只认 http://127.0.0.1:8765/ 。外网和旁边电脑打不进来。"),
        ("02", "看是否就绪", "页顶健康检查：本机模型要显示就绪。未就绪先开模型服务，再刷新。"),
        ("03", "选一份规格书", "PDF / Word / Excel。SuperEvo 做主验收；ESOW、变速器 SR 用来演示空表。"),
        ("04", "等分段进度", "「第 3/14 段」是在问本机模型，不是卡住。数字稿可能数分钟到十几分钟。"),
        ("05", "下载核对表", "打开 Excel：先看说明页类型，再筛「已检索到」。黄底待人工确认。"),
        ("06", "再出下一份", "上一份下载完再传。不要开两个窗口同时出表。"),
    ]
    for i, (num, k, v) in enumerate(steps):
        col = i % 3
        row = i // 3
        left = ML + Inches(col * 3.85)
        y = Inches(1.52) + Inches(row * 2.15)
        rect(s, left, y, Inches(3.7), Inches(2.0), SURFACE3, RULE)
        inset_bar(s, left, y, Inches(2.0))
        box(s, left + Inches(0.16), y + Inches(0.12), Inches(3.35), Inches(0.32), num, size=14, bold=True, color=ACCENT, name="Calibri")
        box(s, left + Inches(0.16), y + Inches(0.48), Inches(3.35), Inches(0.36), k, size=16, bold=True, color=INK)
        box(s, left + Inches(0.16), y + Inches(0.92), Inches(3.4), Inches(0.92), v, size=13, color=INK2)
    notes(
        s,
        "【这一页】对着浏览器讲，不讲原理。\n\n"
        "【健康检查】未就绪多半是本机模型服务没开。不要去配公网地址。\n\n"
        "【一次一份】8765 同时只跑一份任务。演示六份就出六次。\n\n"
        "【进度】分段数字在涨 = 在抽。扫描件前面还有 OCR，更久。\n\n"
        "【空表】ESOW、Outside-2 整表不适用，主动说这是分流对了。\n\n"
        "【黄格】待人工确认，不当场替填。",
    )


def runtime(prs, n, total):
    s = new_slide(prs)
    rail(s, f"{n:02d}", "Runtime")
    eyebrow(s, "八 · 工位操作")
    title(s, "时间主要花在本机模型", size=26)
    sub(s, "启动见前两页  ·  本机大模型先开着  ·  浏览器只打开本机 8765")

    cards = [
        ("读取 + 规则", "大约数秒", "数字稿 Word / PDF 解析和规则抽取。"),
        ("本机模型分段", "数分钟到十几分钟", "空格按 10～16 段串行问本机模型。数字稿也走这一步，为了保准。"),
        ("扫描件 OCR", "更长", "本机 Vision / Tesseract。不当主验收耗时。"),
    ]
    for i, (k, t, d) in enumerate(cards):
        left = ML + Inches(i * 3.85)
        rect(s, left, Inches(1.55), Inches(3.7), Inches(2.35), SURFACE3, RULE)
        inset_bar(s, left, Inches(1.55), Inches(2.35), STEEL if i != 1 else ACCENT)
        box(s, left + Inches(0.18), Inches(1.7), Inches(3.35), Inches(0.32), k, size=14, bold=True, color=INK)
        box(s, left + Inches(0.18), Inches(2.1), Inches(3.35), Inches(0.55), t, size=20, bold=True, color=ACCENT if i == 1 else INK)
        box(s, left + Inches(0.18), Inches(2.72), Inches(3.35), Inches(0.95), d, size=13, color=INK2)

    points = [
        ("模型", "使用本机大模型。更换须双方书面确认。"),
        ("并发", "同时只出一份。不要后台抢同一台本机模型跑多份。"),
        ("网络", "识别阶段可断公网。不调用公网识别服务。"),
        ("内存", "建议 16GB。模型装在工位本机，规格书不上传。"),
    ]
    for i, (k, v) in enumerate(points):
        col = i % 2
        row = i // 2
        left = ML + Inches(col * 5.85)
        y = Inches(4.12) + Inches(row * 1.18)
        rect(s, left, y, Inches(5.55), Inches(1.05), SURFACE4, RULE)
        inset_bar(s, left, y, Inches(1.05))
        box(s, left + Inches(0.2), y, Inches(1.15), Inches(1.05), k, size=14, bold=True, color=INK, anchor=MSO_ANCHOR.MIDDLE)
        box(s, left + Inches(1.45), y, Inches(3.9), Inches(1.05), v, size=13, color=INK2, anchor=MSO_ANCHOR.MIDDLE)
    notes(
        s,
        "【这一页】时间花在哪。读文件+规则大约数秒；等人的是本机模型逐段补空。\n\n"
        "【为什么十几分钟】每段都要等本机大模型处理一遍，串行大约十几段。不是卡住。\n\n"
        "【为什么不换更小模型】更快但更容易填错、误绑，和保准冲突。更大模型只会更慢。\n\n"
        "【为什么数字稿也走模型】全场景保准，不能「规则抽完就出表」。规则已经覆盖大部分准格，模型只补空。\n\n"
        "【约五分钟】以目标工位电脑实测为准。\n\n"
        "【被问专有云】甲方指定专有云可另做。现程序锁死本机回环，上云要改白名单。见下一页。",
    )


def cloud_paths(prs, n, total):
    s = new_slide(prs)
    rail(s, f"{n:02d}", "Cloud")
    eyebrow(s, "九 · 专有云方案")
    title(s, "两条路径，不要混成一版", size=26)
    sub(s, "本期工位本机交付  ·  专有云须书面确认后另做  ·  抽取仍按既定步骤")

    rect(s, ML, Inches(1.52), Inches(5.55), Inches(3.42), SURFACE3, RULE)
    inset_bar(s, ML, Inches(1.52), Inches(3.42), STEEL)
    box(s, ML + Inches(0.22), Inches(1.64), Inches(1.4), Inches(0.28), "路径 A", size=12, bold=True, color=STEEL, name="Calibri")
    box(s, ML + Inches(0.22), Inches(1.96), Inches(5.1), Inches(0.4), "工位本机", size=20, bold=True, color=INK)
    box(
        s,
        ML + Inches(0.22),
        Inches(2.42),
        Inches(5.1),
        Inches(2.3),
        "填表人在工位导入规格书，本机大模型抽取。\n"
        "页面只听 127.0.0.1，模型只打回环地址。\n"
        "规格书不出这台电脑。\n"
        "这是本期交付和 9 月底验收口径。",
        size=14,
        color=INK2,
    )

    right = ML + Inches(5.85)
    rect(s, right, Inches(1.52), Inches(5.55), Inches(3.42), ACCENT_WASH, ACCENT)
    inset_bar(s, right, Inches(1.52), Inches(3.42))
    box(s, right + Inches(0.22), Inches(1.64), Inches(1.4), Inches(0.28), "路径 B", size=12, bold=True, color=ACCENT, name="Calibri")
    box(s, right + Inches(0.22), Inches(1.96), Inches(5.1), Inches(0.4), "甲方指定专有云", size=20, bold=True, color=INK)
    box(
        s,
        right + Inches(0.22),
        Inches(2.42),
        Inches(5.1),
        Inches(2.3),
        "出表程序部署于甲方指定专有云。\n"
        "大模型由甲方在云内部署。\n"
        "规格书出工位、只留专有云内网。\n"
        "须书面确认；不纳入本期工位验收。",
        size=14,
        color=INK2,
    )

    rows = [
        ("工位本机", "规格书不出这台电脑", "现在就能交"),
        ("公网识别服务", "规格书离开指定场所", "禁止"),
        ("甲方指定专有云", "出表 + 本机同款抽取，留在内网", "另做；须只内网可达"),
    ]
    for i, (k, v, tag) in enumerate(rows):
        left = ML + Inches(i * 3.85)
        y = Inches(5.12)
        rect(s, left, y, Inches(3.7), Inches(1.55), SURFACE4, RULE)
        bar = ACCENT if i == 1 else (STEEL if i == 0 else ACCENT_INK)
        inset_bar(s, left, y, Inches(1.55), bar)
        box(s, left + Inches(0.18), y + Inches(0.12), Inches(3.35), Inches(0.36), k, size=14, bold=True, color=INK)
        box(s, left + Inches(0.18), y + Inches(0.5), Inches(3.35), Inches(0.45), v, size=13, color=INK2)
        box(s, left + Inches(0.18), y + Inches(1.0), Inches(3.35), Inches(0.38), tag, size=13, bold=True, color=ACCENT if i == 1 else STEEL)
    notes(
        s,
        "【这一页】部署有两条路，不要说成已经上云。\n\n"
        "【路径 A 本期】工位电脑 + 本机大模型。规格书不出这台电脑。9 月底按这个验收。\n\n"
        "【路径 B 另做】出表程序和模型都在甲方指定专有云。"
        "抽取仍按规则加分段补空，只是模型不在填表人电脑上，而在其内网。\n\n"
        "【中间那格禁止】公网识别服务。专有云内网的大模型不是公网。\n\n"
        "【既有系统】出表不接入甲方既有业务系统。有自建大模型就继续走补全接口。",
    )


def cloud_connect(prs, n, total):
    s = new_slide(prs)
    rail(s, f"{n:02d}", "Cloud")
    eyebrow(s, "九 · 专有云方案")
    title(s, "接专有云大模型，抽取步骤不变", size=26)
    sub(s, "甲方在云内部署大模型  ·  流水线不变  ·  不接入既有业务系统")

    cols = [
        (
            "模型谁来部署",
            "甲方在指定专有云部署大模型。出表继续打补全接口，和工位打本机模型是同一件事。",
        ),
        (
            "与既有系统",
            "出表不接入甲方既有业务系统。有自建大模型，抽表走既定补全接口即可。",
        ),
        (
            "什么不改",
            "分流、规则、拒绝误绑、依据不足则留空，全部保留。不调用公网识别。黄格仍待人工确认。",
        ),
    ]
    for i, (k, v) in enumerate(cols):
        left = ML + Inches(i * 3.85)
        rect(s, left, Inches(1.52), Inches(3.7), Inches(2.55), SURFACE3, RULE)
        inset_bar(s, left, Inches(1.52), Inches(2.55), STEEL if i != 1 else ACCENT)
        box(s, left + Inches(0.16), Inches(1.64), Inches(3.4), Inches(0.4), k, size=14, bold=True, color=INK)
        box(s, left + Inches(0.16), Inches(2.1), Inches(3.4), Inches(1.8), v, size=13, color=INK2)

    box(s, ML, Inches(4.2), TW, Inches(0.28), "要改的（现程序锁死本机，不能原样安装）", size=12, color=INK3, name="Calibri")
    changes = [
        ("监听", "改为内网地址，加登录；不对公网裸开。"),
        ("模型白名单", "放行专有云内大模型地址，继续拦截公网识别。"),
        ("OCR", "Linux 云无 Mac Vision，扫描件用 Tesseract 等。"),
        ("任务", "多用户、存储、并发要重做；现在同时只跑一份。"),
    ]
    for i, (k, v) in enumerate(changes):
        left = ML + Inches((i % 4) * 2.9)
        y = Inches(4.52)
        rect(s, left, y, Inches(2.75), Inches(1.22), SURFACE4, RULE)
        inset_bar(s, left, y, Inches(1.22))
        box(s, left + Inches(0.12), y + Inches(0.08), Inches(2.5), Inches(0.32), k, size=13, bold=True, color=INK)
        box(s, left + Inches(0.12), y + Inches(0.42), Inches(2.5), Inches(0.7), v, size=12, color=INK2)

    rect(s, ML, Inches(5.9), TW, Inches(0.95), ACCENT_WASH, ACCENT)
    inset_bar(s, ML, Inches(5.9), Inches(0.95))
    box(
        s,
        ML + Inches(0.22),
        Inches(6.02),
        Inches(11.0),
        Inches(0.72),
        "前置条件：书面确认规格书可进该专有云、服务只内网可达。"
        "网页端与接入既有系统不纳入本期填表验收。未确认前，仍按工位本机交付。",
        size=14,
        color=INK,
        anchor=MSO_ANCHOR.MIDDLE,
    )
    notes(
        s,
        "【这一页】专有云怎么接模型。口径：甲方部署大模型，出表仍走既定抽取步骤。\n\n"
        "【和工位的差别】抽取逻辑相同（规则 + 空缺分段补空）。差别只是大模型在工位电脑上，还是在甲方内网服务器上。\n\n"
        "【为什么现程序装不上去】页面只绑本机地址；模型地址必须是本机回环。上云后要允许内网大模型，仍禁止公网识别。\n\n"
        "【既有系统】出表不接入甲方业务系统。若只提供对话接口、没有补全接口，才需要适配层。\n\n"
        "【四件要改】监听改内网并加登录；白名单放行内网大模型；Linux OCR；多用户任务。"
        "书面确认规格书留在专有云内网。不纳入本期工位验收。",
    )


def close(prs, n, total):
    s = new_slide(prs)
    rail(s, f"{n:02d}", "Close")
    eyebrow(s, "十 · 汇报三句话")
    title(s, "本机 · 分流 · 保准", size=26)
    sub(s, "被追问时回到这三句  ·  专有云是第二路径，须书面确认")

    lines = [
        (
            "01",
            "规格书不出公网",
            "本期工位本机识别。专有云用甲方自建大模型，规格书只留内网，不调用公网识别。",
        ),
        (
            "02",
            "先判断文件是不是电控规格",
            "再决定按核对表抽取还是整表不适用。ESOW、变速器 SR 空表是分流正确。",
        ),
        (
            "03",
            "验收看抽出项是否可追溯",
            "不要求格格填满。已检索到必须对原文；对不上则留空，不得静默填写。",
        ),
    ]
    for i, (num, k, v) in enumerate(lines):
        y = Inches(1.55) + Inches(i * 1.55)
        rect(s, ML, y, TW, Inches(1.42), SURFACE3, RULE)
        inset_bar(s, ML, y, Inches(1.42))
        box(s, ML + Inches(0.22), y + Inches(0.18), Inches(1.15), Inches(1.05), num, size=22, bold=True, color=ACCENT, anchor=MSO_ANCHOR.MIDDLE, name="Calibri")
        box(s, ML + Inches(1.5), y + Inches(0.18), Inches(9.6), Inches(0.45), k, size=20, bold=True, color=INK)
        box(s, ML + Inches(1.5), y + Inches(0.68), Inches(9.6), Inches(0.55), v, size=14, color=INK2)

    notes(
        s,
        "【这一页】收束。被追问时回到这三句，不要展开成新故事。\n\n"
        "1 规格书不出公网。本期本机大模型；专有云用甲方自建大模型，只留内网。\n"
        "2 先分流。ESOW / 变速器空表是对的。\n"
        "3 验收看可追溯，不看满不满。依据不足则留空。\n\n"
        "【若还有时间】主验收 SuperEvo；黄格待人工确认；读取对照过不换主路径。",
    )


def main() -> None:
    prs = Presentation()
    prs.slide_width = W
    prs.slide_height = H
    slides = [
        cover,
        toc,
        product,
        architecture,
        pipeline,
        classify,
        extract,
        sdk,
        samples,
        operate_cmd,
        operate_ui,
        runtime,
        cloud_paths,
        cloud_connect,
        close,
    ]
    cover(prs)
    for i, fn in enumerate(slides[1:], start=2):
        fn(prs, i, len(slides))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(f"wrote {OUT} ({len(slides)} slides)")


if __name__ == "__main__":
    main()
