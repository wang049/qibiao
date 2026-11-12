"""极光湾电子电器 · 咨询服务 PPT。版式对齐同事《仿真咨询》：左轨、大标题、全程用表。"""
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

W = Inches(13.333)
H = Inches(7.5)
RAIL = Inches(0.67)
ML = Inches(1.12)
TW = Inches(11.55)
TABLE_TOP = Inches(1.92)
TABLE_H = Inches(4.64)
PAD = (6, 7, 3, 3)
PAD_DENSE = (5, 6, 2, 2)
OUT = Path("/Users/wwj/Desktop/电子电器工程服务方案.pptx")
OUT_NEW = Path("/Users/wwj/Desktop/电子电器工程服务方案.pptx")
N_SLIDES = 12


def _hex(color: RGBColor) -> str:
    return f"{int(color[0]):02X}{int(color[1]):02X}{int(color[2]):02X}"


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


def eyebrow(slide, lead: str, rest: str):
    tb = slide.shapes.add_textbox(ML, Inches(0.30), TW, Inches(0.22))
    tf = tb.text_frame
    tf.word_wrap = False
    p = tf.paragraphs[0]
    p.clear()
    _font(p.add_run(), lead, 11, True, ACCENT)
    _font(p.add_run(), f"  ·  {rest}", 11, False, INK3)


def title(slide, text, size=34):
    box(slide, ML, Inches(0.62), TW, Inches(0.52), text, size=size, bold=True, color=INK)


def sub(slide, lead: str, trail: str | None = None):
    tb = slide.shapes.add_textbox(ML, Inches(1.26), TW, Inches(0.56))
    tf = tb.text_frame
    tf.word_wrap = True
    _no_autofit(tf)
    try:
        tf.vertical_anchor = MSO_ANCHOR.TOP
    except Exception:
        pass
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    p.clear()
    _font(p.add_run(), lead, 12, False, INK2)
    p.line_spacing = 1.15
    p.space_after = Pt(2) if trail else Pt(0)
    if trail:
        p2 = tf.add_paragraph()
        p2.alignment = PP_ALIGN.LEFT
        _font(p2.add_run(), trail, 12, False, INK2)
        p2.line_spacing = 1.15


def note(slide, lead: str, rest: str, top=None):
    tb = slide.shapes.add_textbox(ML, top or Inches(6.68), TW, Inches(0.40))
    tf = tb.text_frame
    tf.word_wrap = True
    _no_autofit(tf)
    p = tf.paragraphs[0]
    p.clear()
    _font(p.add_run(), lead, 10, True, INK2)
    _font(p.add_run(), rest, 10, False, INK3)
    p.line_spacing = 1.15


def _cell_fill(cell, color: RGBColor):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    for tag in ("a:solidFill", "a:gradFill", "a:noFill"):
        for el in list(tcPr.findall(qn(tag))):
            tcPr.remove(el)
    sf = etree.SubElement(tcPr, qn("a:solidFill"))
    srgb = etree.SubElement(sf, qn("a:srgbClr"))
    srgb.set("val", _hex(color))


def _cell_borders(cell, color=RULE2, left=None, left_w=None):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    for el in list(tcPr.findall(qn("a:tcBdr"))):
        tcPr.remove(el)
    bdr = etree.SubElement(tcPr, qn("a:tcBdr"))

    def add_ln(tag, col, w_pt):
        ln = etree.SubElement(bdr, qn(tag))
        ln.set("w", str(int(w_pt * 12700)))
        ln.set("cap", "flat")
        ln.set("cmpd", "sng")
        ln.set("algn", "ctr")
        fill = etree.SubElement(ln, qn("a:solidFill"))
        srgb = etree.SubElement(fill, qn("a:srgbClr"))
        srgb.set("val", _hex(col))
        dash = etree.SubElement(ln, qn("a:prstDash"))
        dash.set("val", "solid")

    add_ln("a:lnL", left or color, left_w or 0.75)
    add_ln("a:lnR", color, 0.75)
    add_ln("a:lnT", color, 0.75)
    add_ln("a:lnB", color, 0.75)


def _cell_margin(cell, l=5, r=5, t=2, b=2):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    for el in list(tcPr.findall(qn("a:tcMar"))):
        tcPr.remove(el)
    mar = etree.SubElement(tcPr, qn("a:tcMar"))
    for tag, val in (("a:left", l), ("a:right", r), ("a:top", t), ("a:bottom", b)):
        n = etree.SubElement(mar, qn(tag))
        n.set("sz", str(int(Pt(val))))


def _no_autofit(tf):
    body = tf._txBody.find(qn("a:bodyPr"))
    if body is None:
        return
    for tag in ("a:normAutofit", "a:spAutoFit", "a:noAutofit"):
        for el in list(body.findall(qn(tag))):
            body.remove(el)
    etree.SubElement(body, qn("a:noAutofit"))


def _tf_setup(tf, pad, anchor=MSO_ANCHOR.MIDDLE):
    tf.word_wrap = True
    _no_autofit(tf)
    try:
        tf.vertical_anchor = anchor
    except Exception:
        pass
    body = tf._txBody.find(qn("a:bodyPr"))
    if body is None:
        return
    body.set("lIns", str(int(Pt(pad[0]))))
    body.set("rIns", str(int(Pt(pad[1]))))
    body.set("tIns", str(int(Pt(pad[2]))))
    body.set("bIns", str(int(Pt(pad[3]))))
    body.set("anchor", "ctr" if anchor == MSO_ANCHOR.MIDDLE else "t")


def _paint_cell(
    slide,
    l,
    t,
    w,
    h,
    text,
    *,
    size=11,
    bold=False,
    color=INK2,
    fill=SURFACE,
    align=PP_ALIGN.LEFT,
    name="微软雅黑",
    sub=None,
    accent_left=False,
    pad=(6, 7, 3, 3),
    v_anchor=MSO_ANCHOR.MIDDLE,
    border=RULE2,
):
    rect(slide, l, t, w, h, fill, border=border, lw=0.75)
    if accent_left:
        rect(slide, l, t, Pt(2.2), h, ACCENT)
    tb = slide.shapes.add_textbox(l, t, w, h)
    tf = tb.text_frame
    _tf_setup(tf, pad, v_anchor)
    p = tf.paragraphs[0]
    p.alignment = align
    p.clear()
    _font(p.add_run(), text or "", size, bold, color, name)
    p.line_spacing = 1.08
    if sub:
        p2 = tf.add_paragraph()
        p2.alignment = align
        p2.space_before = Pt(1)
        _font(p2.add_run(), sub, 9, False, INK3, name)
        p2.line_spacing = 1.08


def _paint_grp(slide, t, h, title_t, hint, pad):
    rect(slide, ML, t, TW, h, SURFACE4, border=RULE, lw=0.75)
    rect(slide, ML, t, Pt(2.4), h, ACCENT)
    tb = slide.shapes.add_textbox(ML, t, TW, h)
    tf = tb.text_frame
    _tf_setup(tf, (10, 8, 3, 3), MSO_ANCHOR.MIDDLE)
    p = tf.paragraphs[0]
    p.clear()
    _font(p.add_run(), title_t, 12, True, INK)
    if hint:
        _font(p.add_run(), f"    {hint}", 10, False, INK3)
    p.line_spacing = 1.1


def put_table(slide, headers, rows, col_w, top, height, pad=(5, 5, 2, 2), v_anchor=MSO_ANCHOR.TOP):
    total_w = float(sum(col_w))
    widths = [TW * (w / total_w) for w in col_w]
    col_in = [TW.inches * w / total_w for w in col_w]
    max_h_in = height.inches

    hs = [0.32]
    for row in rows:
        if row[0] == "grp":
            hs.append(0.34)
        else:
            n = max(1, _row_lines(row, col_in))
            hs.append(max(0.36, 0.18 * n + 0.18))
    if sum(hs) > max_h_in:
        scale = max_h_in / sum(hs)
        hs = [max(0.22, x * scale) for x in hs]
    else:
        n = len(hs)
        cap, target = 0.46, min(max_h_in, 4.40)
        if n <= 7:
            cap = 0.68
            target = min(max_h_in, 4.55)
        extra = max(0.0, target - sum(hs))
        cans = [max(0.0, cap - x) for x in hs]
        cansum = sum(cans)
        if extra and cansum:
            take = min(extra, cansum)
            for i, c in enumerate(cans):
                hs[i] += take * c / cansum

    y = top
    x = ML
    for i, htxt in enumerate(headers):
        _paint_cell(
            slide,
            x,
            y,
            widths[i],
            Inches(hs[0]),
            htxt,
            size=11,
            color=INK3,
            fill=SURFACE4,
            pad=pad,
            v_anchor=MSO_ANCHOR.MIDDLE,
        )
        x += widths[i]
    y += Inches(hs[0])

    for r, row in enumerate(rows):
        rh = Inches(hs[r + 1])
        if row[0] == "grp":
            _paint_grp(slide, y, rh, row[1], row[2], pad)
            y += rh
            continue
        fill = SURFACE3 if r % 2 == 1 else SURFACE
        x = ML
        for c, item in enumerate(row[1]):
            if isinstance(item, str):
                item = {"text": item}
            style = item.get("style", "")
            text = item.get("text", "")
            sub_t = item.get("sub")
            size, bold, color, align, name = 10, False, INK2, PP_ALIGN.LEFT, "微软雅黑"
            if style == "n":
                color, bold, align, name, size = ACCENT, True, PP_ALIGN.CENTER, "Calibri", 10
            elif style == "k":
                color, bold, size = INK, True, 11
            elif style == "e":
                color = ACCENT_INK
            elif style == "c":
                align = PP_ALIGN.CENTER
            elif style == "yes":
                color, bold, align = ACCENT, True, PP_ALIGN.CENTER
            _paint_cell(
                slide,
                x,
                y,
                widths[c],
                rh,
                text,
                size=size,
                bold=bold,
                color=color,
                fill=fill,
                align=align,
                name=name,
                sub=sub_t,
                pad=pad,
                v_anchor=v_anchor,
            )
            x += widths[c]
        y += rh
    return y


def _item_parts(item):
    if isinstance(item, str):
        return item, None
    return item.get("text", ""), item.get("sub")


def _char_units(text: str) -> float:
    w = 0.0
    for ch in str(text):
        o = ord(ch)
        if ch in " ··—–…、，。；：/":
            w += 0.55
        elif o > 0x2E7F:
            w += 1.0
        else:
            w += 0.58
    return w


def _est_lines(text, col_in, size=11):
    if not text:
        return 1
    em = (size / 72.0) * 1.12
    cpl = max(6.0, (max(0.5, col_in - 0.24) / em))
    total = 0
    for para in str(text).split("\n"):
        u = _char_units(para)
        total += max(1, int((u + cpl - 0.05) / cpl)) if para else 1
    return total


def _row_lines(row, col_in):
    if row[0] == "grp":
        return 1
    mx = 1
    for i, item in enumerate(row[1]):
        text, sub = _item_parts(item)
        size = 11
        if isinstance(item, dict) and item.get("style") == "n":
            size = 10
        lines = _est_lines(text, col_in[i], size)
        if sub:
            lines += _est_lines(sub, col_in[i], 9)
        mx = max(mx, lines)
    return mx


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
    rect(s, RAIL, 0, Inches(7.4), H, SURFACE)
    rect(s, ML, Inches(1.78), Inches(0.42), Pt(3), ACCENT)
    box(
        s,
        ML + Inches(0.54),
        Inches(1.68),
        Inches(9),
        Inches(0.28),
        "kmind  ·  Electrical Service",
        size=11,
        color=INK3,
        name="Calibri",
    )
    box(s, ML, Inches(2.18), Inches(11.2), Inches(1.15), "电子电器工程服务方案", size=40, bold=True, color=INK)
    box(
        s,
        ML,
        Inches(3.48),
        Inches(10.2),
        Inches(0.7),
        "面向规格书填表场景的能力移交、方案咨询与持续维护",
        size=15,
        color=INK2,
    )
    rect(s, ML, Inches(6.42), TW, Pt(1), RULE)
    box(s, ML, Inches(6.58), Inches(7.4), Inches(0.36), "培训  ·  咨询  ·  售后", size=13, color=INK3)
    box(s, Inches(10.85), Inches(6.52), Inches(1.8), Inches(0.42), "kmind", size=18, bold=True, color=INK, name="Calibri")
    rect(s, Inches(10.85), Inches(6.96), Inches(1.15), Pt(2.2), ACCENT)


def training_scope(prs):
    s = new_slide(prs)
    rail(s, "02", "Training")
    eyebrow(s, "模块一", "范围与能力边界  ·  1 / 4")
    title(s, "培训")
    sub(
        s,
        "出表系统分为三层。培训移交的是中间的标准配置层，即把核对规则写成可重复执行、可自动校验的配置。",
        "下表逐项列明各层内容、承担方，以及学员需达到的掌握程度。",
    )
    put_table(
        s,
        ["组成项", "承担 / 掌握", "说明"],
        [
            ("grp", "第一层 · 系统内核", "我方维护，学员无需掌握"),
            (
                "row",
                [
                    {"text": "读取 · 调度 · 出表 · 部署", "style": "k"},
                    {"text": "我方 · 无需掌握", "style": "c"},
                    "本机读取 PDF / Word / Excel，按三类检索状态出表；规格书不出公网",
                ],
            ),
            ("grp", "第二层 · 标准配置", "本模块移交"),
            (
                "row",
                [
                    {"text": "表头与字段定义", "style": "k"},
                    {"text": "贵司学员 · 独立配置", "style": "yes"},
                    "按底稿声明字段、别名、单位与缺省；中 / 英 / 德择一",
                ],
            ),
            (
                "row",
                [
                    {"text": "抽取与核对规则（重点）", "style": "k"},
                    {"text": "贵司学员 · 独立编写", "style": "yes"},
                    "有效值、互斥字段、禁止臆造；空项与局部对应",
                ],
            ),
            (
                "row",
                [
                    {"text": "用例与说明", "style": "k"},
                    {"text": "贵司学员 · 独立编写", "style": "yes"},
                    "至少一条空项或误抽用例；含用途、前置条件与限制",
                ],
            ),
            ("grp", "第三层 · 执行环境", "工位运行，不新增公网服务"),
            (
                "row",
                [
                    {"text": "工位工作站", "style": "k"},
                    {"text": "贵司现有 · 须熟练使用", "style": "c"},
                    "可运行出表程序的工位电脑",
                ],
            ),
            (
                "row",
                [
                    {"text": "本机模型服务", "style": "k"},
                    {"text": "我方提供 · 掌握启停", "style": "c"},
                    "安装包与启动说明；不接入公网识别",
                ],
            ),
            (
                "row",
                [
                    {"text": "出表程序", "style": "k"},
                    {"text": "我方提供 · 掌握操作", "style": "c"},
                    "导入规格书、查看进度、下载核对表",
                ],
            ),
        ],
        [210, 190, 456],
        TABLE_TOP,
        TABLE_H,
        pad=PAD_DENSE,
        v_anchor=MSO_ANCHOR.TOP,
    )
    note(
        s,
        "参训对象：",
        "使用培训面向填表人与接口人，不要求编程。独立开发培训面向后续开发人员，提供 krow-agent-sdk 与书面规范。",
    )


def training_outline(prs):
    s = new_slide(prs)
    rail(s, "03", "Training")
    eyebrow(s, "模块一", "课程大纲  ·  2 / 4")
    title(s, "培训")
    sub(
        s,
        "六个单元以贵司指定的规格书贯穿。使用培训覆盖 U1–U2，独立开发培训覆盖全部单元。",
        "下表列明各单元主题、教学内容、实操产出与考核方式。",
    )
    put_table(
        s,
        ["单元", "主题", "教学内容", "产出 / 考核"],
        [
            (
                "row",
                [
                    {"text": "U1", "style": "n"},
                    {"text": "环境与基础", "style": "k"},
                    "安装自检；导入规格书出表；目录与命名",
                    {"text": "环境自检记录；成功出一份核对表", "sub": "自检项全部通过"},
                ],
            ),
            (
                "row",
                [
                    {"text": "U2", "style": "n"},
                    {"text": "核对表读法", "style": "k"},
                    "三类检索状态；页码与原文；空项 / 局部对应 / 复核口径",
                    {"text": "带复核标记的读表记录", "sub": "状态判断与讲师标注一致"},
                ],
            ),
            (
                "row",
                [
                    {"text": "U3", "style": "n"},
                    {"text": "表头与字段", "style": "k"},
                    "底稿字段、别名与单位；不把其他类型说明书抽进本清单",
                    {"text": "按底稿完成的字段配置初稿", "sub": "与底稿一致，无多余无遗漏"},
                ],
            ),
            (
                "row",
                [
                    {"text": "U4", "style": "n"},
                    {"text": "抽取与校验", "style": "k"},
                    "有效值、互斥、禁止臆造；失败信息含缺失项与页码",
                    {"text": "含完整校验的规则稿", "sub": "人为注入误抽后能被校验拦截"},
                ],
            ),
            (
                "row",
                [
                    {"text": "U5", "style": "n"},
                    {"text": "本机自测", "style": "k"},
                    "本机运行与日志；扫描件差异；规格书不出公网检查",
                    {"text": "本机自测通过记录", "sub": "能独立定位并修复两类典型故障"},
                ],
            ),
            (
                "row",
                [
                    {"text": "U6", "style": "n"},
                    {"text": "扩展与提交", "style": "k"},
                    "扩展点、规范检查、提交与基线登记",
                    {"text": "通过验收并登记的配置或扩展", "sub": "三级验收全部通过"},
                ],
            ),
        ],
        [50, 120, 430, 256],
        TABLE_TOP,
        TABLE_H,
        pad=PAD,
        v_anchor=MSO_ANCHOR.MIDDLE,
    )
    note(
        s,
        "课时与班期：",
        "按人数与规格书复杂度开课前商定。培训用规格书由贵司指定，结课核对表即为成果。",
    )


def training_rules(prs):
    s = new_slide(prs)
    rail(s, "04", "Training")
    eyebrow(s, "模块一", "编写规范与自动检查  ·  3 / 4")
    title(s, "培训")
    sub(
        s,
        "规范由本机自动检查落实。学员与我方使用同一套规则与版本，提交前即可确认是否合规。",
        "下表列出强制规范与自动检查项，以及不合格时的处理。",
    )
    put_table(
        s,
        ["编号", "项目", "具体要求", "不合格时"],
        [
            ("grp", "强制规范", "任一项不满足即不予登记"),
            (
                "row",
                [
                    {"text": "R1", "style": "n"},
                    {"text": "字段定义完整", "style": "k"},
                    "每个字段声明别名、单位与缺省；用业务语言，不用内部代号",
                    {"text": "列出缺失字段，退回补齐", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "R2", "style": "n"},
                    {"text": "可复现且不出公网", "style": "k"},
                    "不得依赖界面选择；规格书不出公网；同一文件两次出表，状态与页码须一致",
                    {"text": "定位到规则，退回改写", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "R3", "style": "n"},
                    {"text": "结果必须可核对", "style": "k"},
                    "抽出值须回读页码与原文；无原文则标为未检索到，不得臆造",
                    {"text": "退回补写校验，并追加失败用例", "style": "e"},
                ],
            ),
            ("grp", "自动检查项", "本机可预先自查"),
            (
                "row",
                [
                    {"text": "C1", "style": "n"},
                    {"text": "位置与命名", "style": "k"},
                    "目录位置与命名符合规范，标识全局唯一",
                    {"text": "提示正确位置与命名", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "C2", "style": "n"},
                    {"text": "声明一致性", "style": "k"},
                    "字段声明与实际抽出字段一致，无多余、无遗漏",
                    {"text": "列出差异项", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "C3", "style": "n"},
                    {"text": "核对覆盖", "style": "k"},
                    "抽出值均有检索状态；已检索到的条目含页码与原文",
                    {"text": "列出缺少依据的条目", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "C4", "style": "n"},
                    {"text": "禁用公网识别", "style": "k"},
                    "未调用公网识别，未将规格书上传外网",
                    {"text": "拦截并改回本机识别", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "C5", "style": "n"},
                    {"text": "无写死内容", "style": "k"},
                    "无绝对路径、无写死样例文件名与单元格号",
                    {"text": "定位到具体语句", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "C6", "style": "n"},
                    {"text": "失败路径用例", "style": "k"},
                    "至少一条用例覆盖空项或误抽，确认校验能够拦截",
                    {"text": "退回补充用例", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "C7", "style": "n"},
                    {"text": "说明文档字段", "style": "k"},
                    "说明须含用途、前置条件与已知限制",
                    {"text": "列出缺失字段", "style": "e"},
                ],
            ),
        ],
        [50, 150, 470, 186],
        TABLE_TOP,
        TABLE_H,
        pad=PAD_DENSE,
        v_anchor=MSO_ANCHOR.MIDDLE,
    )
    note(
        s,
        "R3：",
        "模型可能对无原文的额定、峰值给出看似合理的数字。不能回读到原文的，标为未检索到。",
    )


def training_accept(prs):
    s = new_slide(prs)
    rail(s, "05", "Training")
    eyebrow(s, "模块一", "实施流程与验收  ·  4 / 4")
    title(s, "培训")
    sub(
        s,
        "从样例到登记经过五步、三级验收。A1、A3 由程序判定，A2 由我方用真实规格书复核。",
        "下表分列实施步骤与验收级别。",
    )
    put_table(
        s,
        ["编号", "步骤", "执行方", "具体内容", "完成标志"],
        [
            ("grp", "实施步骤", "按顺序执行"),
            (
                "row",
                [
                    {"text": "01", "style": "n"},
                    {"text": "样例与底稿", "style": "k"},
                    {"text": "贵司学员", "style": "c"},
                    "确认培训用规格书与出表底稿，记录字段取值依据",
                    {"text": "得到可解读的样例与底稿", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "02", "style": "n"},
                    {"text": "配置或编写", "style": "k"},
                    {"text": "贵司学员", "style": "c"},
                    "完成字段声明、抽取与核对规则、失败路径用例与说明",
                    {"text": "在本机可正常出表", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "03", "style": "n"},
                    {"text": "本机自测", "style": "k"},
                    {"text": "贵司学员", "style": "c"},
                    "本机出表并执行自动规范检查，直至全部通过",
                    {"text": "自测与规范检查均通过", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "04", "style": "n"},
                    {"text": "我方复核", "style": "k"},
                    {"text": "我方", "style": "c"},
                    "用同一份规格书出表，核对抽出值、状态、页码与原文",
                    {"text": "与本机结果逐项一致", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "05", "style": "n"},
                    {"text": "登记基线", "style": "k"},
                    {"text": "我方", "style": "c"},
                    "进入配置库，登记基线核对表，纳入后续变更回归",
                    {"text": "完成登记，可被后续场景调用", "style": "e"},
                ],
            ),
        ],
        [46, 120, 96, 400, 194],
        TABLE_TOP,
        Inches(2.52),
        pad=PAD,
        v_anchor=MSO_ANCHOR.MIDDLE,
    )
    put_table(
        s,
        ["编号", "级别", "判定", "内容", "不合格时"],
        [
            ("grp", "验收级别", "A1、A2 为登记条件；A3 为登记后持续约束"),
            (
                "row",
                [
                    {"text": "A1", "style": "n"},
                    {"text": "规范验收", "style": "k"},
                    {"text": "程序判定", "style": "c"},
                    "第 04 页七项自动检查；本机与我方使用同一套规则",
                    {"text": "列出不合格项，退回修改", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "A2", "style": "n"},
                    {"text": "复核验收", "style": "k"},
                    {"text": "我方复核", "style": "c"},
                    "用真实规格书出表，逐项核对抽出值与原文",
                    {"text": "出具差异报告，退回修改", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "A3", "style": "n"},
                    {"text": "变更回归", "style": "k"},
                    {"text": "程序判定", "style": "c"},
                    "框架、规则或底稿变更后重跑基线，忽略时间戳",
                    {"text": "暂停该次发布，列出受影响字段", "style": "e"},
                ],
            ),
        ],
        [46, 120, 96, 400, 194],
        Inches(4.52),
        Inches(1.98),
        pad=PAD,
        v_anchor=MSO_ANCHOR.MIDDLE,
    )
    note(
        s,
        "结课三项均须满足：",
        "独立完成一份真实规格书出表；配置通过三级验收并登记；能说明三类检索状态，以及为何禁止臆造。不设卷面考试。",
    )


def consult_items(prs):
    s = new_slide(prs)
    rail(s, "06", "Consulting")
    eyebrow(s, "模块二", "服务项与交付物  ·  1 / 4")
    title(s, "咨询")
    sub(
        s,
        "咨询围绕核对表底稿、规格书样本、抽取规则与验收判据展开，并据此确定本年场景。",
        "下表列出各服务项须回答的问题、主要交付物与建议顺序。",
    )
    put_table(
        s,
        ["编号", "服务项", "需要回答的问题", "主要交付物", "顺序"],
        [
            (
                "row",
                [
                    {"text": "A", "style": "n"},
                    {"text": "核对表底稿确认", "style": "k"},
                    "现行填表有哪些字段、分组与单位？哪些必须来自规格书原文，哪些由人工另填",
                    {"text": "底稿对照表 · 字段清单 · 必填 / 可空", "style": "e"},
                    {"text": "第 1 步", "style": "c"},
                ],
            ),
            (
                "row",
                [
                    {"text": "B", "style": "n"},
                    {"text": "规格书样本与可抽取范围", "style": "k"},
                    "中 / 英 / 德，以及 PDF、Word、Excel、扫描件，各能抽到什么程度？扫描件是否纳入本期",
                    {"text": "试抽结论 · 格式与语言覆盖 · 暂不纳入类型", "style": "e"},
                    {"text": "第 1 步", "style": "c"},
                ],
            ),
            (
                "row",
                [
                    {"text": "C", "style": "n"},
                    {"text": "抽取与核对规则", "style": "k"},
                    "有效值、互斥字段与单位如何写成可执行规则？无原文依据时如何处理",
                    {"text": "规则表 · 冲突组 · 失败用例", "style": "e"},
                    {"text": "第 2 步", "style": "c"},
                ],
            ),
            (
                "row",
                [
                    {"text": "D", "style": "n"},
                    {"text": "检索状态与验收判据", "style": "k"},
                    "已检索到 / 局部对应 / 未检索到如何界定？空项与局部对应由谁确认",
                    {"text": "判据表 · 签署人 · 复核口径", "style": "e"},
                    {"text": "第 2 步", "style": "c"},
                ],
            ),
            (
                "row",
                [
                    {"text": "E", "style": "n"},
                    {"text": "本年场景与培训范围", "style": "k"},
                    "填表、功能拆解、芯片 IO、企标对比、CE BOM 哪些纳入本期培训与售后",
                    {"text": "场景划分表 · 建议时点 · 培训选题", "style": "e"},
                    {"text": "第 3 步", "style": "c"},
                ],
            ),
        ],
        [46, 176, 360, 250, 70],
        TABLE_TOP,
        TABLE_H,
        pad=PAD,
        v_anchor=MSO_ANCHOR.MIDDLE,
    )
    note(
        s,
        "开课前置：",
        "无底稿无法按真实表头验收；无代表性规格书无法判定可抽取程度。C、D 未完成则检索状态只记录、不作验收拦截。E 的结论见第 07 页。",
    )


def consult_scenes(prs):
    s = new_slide(prs)
    rail(s, "07", "Consulting")
    eyebrow(s, "模块二", "本年场景与建议时点  ·  2 / 4")
    title(s, "咨询")
    sub(
        s,
        "同类电控场景建议分阶段开展。",
        "下表列明各场景的建议时点、主要产出与说明。",
    )
    put_table(
        s,
        ["编号", "场景", "时点", "主要产出", "说明"],
        [
            (
                "row",
                [
                    {"text": "01", "style": "n"},
                    {"text": "规格书填表", "style": "k"},
                    {"text": "8–9 月", "style": "c"},
                    {"text": "可核对 Excel", "style": "e"},
                    "当前已开展；培训与售后按此场景",
                ],
            ),
            (
                "row",
                [
                    {"text": "02", "style": "n"},
                    {"text": "功能落地拆解", "style": "k"},
                    {"text": "9 月", "style": "c"},
                    {"text": "拆解稿", "style": "e"},
                    "咨询先定划分维度、粒度及与现有清单的对应",
                ],
            ),
            (
                "row",
                [
                    {"text": "03", "style": "n"},
                    {"text": "芯片 IO 规划", "style": "k"},
                    {"text": "10 月", "style": "c"},
                    {"text": "可核对初始配置表", "style": "e"},
                    "对照数据手册；命名与限制由接口人确认",
                ],
            ),
            (
                "row",
                [
                    {"text": "04", "style": "n"},
                    {"text": "企标测试对比", "style": "k"},
                    {"text": "11 月", "style": "c"},
                    {"text": "测试项对比表", "style": "e"},
                    "差异按覆盖 / 部分覆盖 / 缺失分类，缺项进入测试策划",
                ],
            ),
            (
                "row",
                [
                    {"text": "05", "style": "n"},
                    {"text": "CE BOM", "style": "k"},
                    {"text": "12 月", "style": "c"},
                    {"text": "可核对物料 Excel", "style": "e"},
                    "字段抽取可辅助，单位与法规字段须人工确认",
                ],
            ),
        ],
        [50, 150, 100, 170, 486],
        TABLE_TOP,
        TABLE_H,
        pad=PAD,
        v_anchor=MSO_ANCHOR.MIDDLE,
    )
    note(
        s,
        "范围说明：",
        "实施顺序以服务项 E 的结论为准。建议时点尚未到达的场景，不纳入当期售后。原理图 / 布局检查单不纳入本年 8–12 月。新场景或范围变化以书面变更单确认后执行。",
    )


def consult_work(prs):
    s = new_slide(prs)
    rail(s, "08", "Consulting")
    eyebrow(s, "模块二", "各服务项工作内容  ·  3 / 4")
    title(s, "咨询")
    sub(
        s,
        "各项工作以真实规格书试抽、并与现行填表对照为基础，不以问卷代替。",
        "下表列明五项服务的具体工作内容与贵司需提供的材料。",
    )
    put_table(
        s,
        ["编号", "服务项", "具体工作内容", "贵司需提供"],
        [
            (
                "row",
                [
                    {"text": "A", "style": "n"},
                    {"text": "核对表底稿确认", "style": "k"},
                    "对照现行填表与目标 Excel，逐项确认字段、别名、单位与缺省；区分原文抽取项与人工另填项",
                    {"text": "现行填表（空表或已填示例）；目标出表 Excel 初稿", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "B", "style": "n"},
                    {"text": "规格书样本与可抽取范围", "style": "k"},
                    "用贵司指定规格书试抽；按语言与格式分级；标明扫描件及暂不具备条件的类型",
                    {"text": "代表性规格书（建议英 PDF、中 Word、扫描件各一）；脱敏口径", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "C", "style": "n"},
                    {"text": "抽取与核对规则", "style": "k"},
                    "将有效值、互斥、单位与禁止臆造写成可执行规则；编制空项与误抽失败用例",
                    {"text": "历史复核意见；易混字段说明（如额定与峰值）", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "D", "style": "n"},
                    {"text": "检索状态与验收判据", "style": "k"},
                    "标定三类检索状态与签署人；明确空项、局部对应的复核要求",
                    {"text": "现行质量口径；判据签署人", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "E", "style": "n"},
                    {"text": "本年场景与培训范围", "style": "k"},
                    "按作业环节划分场景，排定建议时点，划定培训与售后范围",
                    {"text": "本年重点项目节点；各场景使用频次", "style": "e"},
                ],
            ),
        ],
        [46, 176, 500, 234],
        TABLE_TOP,
        TABLE_H,
        pad=PAD,
        v_anchor=MSO_ANCHOR.MIDDLE,
    )
    note(
        s,
        "验收约束：",
        "无页码与原文的抽出值不得进入验收。扫描件是否纳入本期，以服务项 B 的试抽结论为准。",
    )


def consult_deliver(prs):
    s = new_slide(prs)
    rail(s, "09", "Consulting")
    eyebrow(s, "模块二", "交付物规格与工作阶段  ·  4 / 4")
    title(s, "咨询")
    sub(
        s,
        "交付物按统一规格书写。每阶段结束即交付该阶段材料并确认，不在末期一次性交付。",
        "下表分列交付物规格与工作阶段。",
    )
    put_table(
        s,
        ["编号", "交付物", "内容构成", "用途"],
        [
            ("grp", "交付物规格", "逐项列明"),
            (
                "row",
                [
                    {"text": "D1", "style": "n"},
                    {"text": "核对表底稿", "style": "k"},
                    "字段、分组、别名、单位、必填 / 可空、人工另填项",
                    {"text": "表头配置与培训 U3", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "D2", "style": "n"},
                    {"text": "样本试抽结论", "style": "k"},
                    "语言与格式覆盖、可抽取程度、暂不纳入类型及理由",
                    {"text": "本期范围确认", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "D3", "style": "n"},
                    {"text": "抽取与核对规则", "style": "k"},
                    "有效值、互斥、单位、禁止臆造、失败用例",
                    {"text": "自动检查与样例回归", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "D4", "style": "n"},
                    {"text": "验收判据", "style": "k"},
                    "三类检索状态、签署人、空项与局部对应复核口径",
                    {"text": "培训验收与售后拦截", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "D5", "style": "n"},
                    {"text": "本年场景安排", "style": "k"},
                    "场景划分、建议时点、培训选题、售后范围",
                    {"text": "开课范围与排期", "style": "e"},
                ],
            ),
        ],
        [46, 150, 520, 240],
        TABLE_TOP,
        Inches(2.58),
        pad=PAD,
        v_anchor=MSO_ANCHOR.MIDDLE,
    )
    put_table(
        s,
        ["阶段", "名称", "工作内容", "产出 / 贵司配合"],
        [
            ("grp", "工作阶段", "阶段结论确认后不再回退"),
            (
                "row",
                [
                    {"text": "P1", "style": "n"},
                    {"text": "资料收集", "style": "k"},
                    "收集底稿、现行填表、规格书样本与脱敏口径，识别缺口",
                    {"text": "缺口清单 · 贵司指定资料对接人", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "P2", "style": "n"},
                    {"text": "试抽与核对", "style": "k"},
                    "用真实规格书试抽出表；与填表人、质量对照现行填表核对差异",
                    {"text": "试抽记录 · 安排受访人与规格书样本", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "P3", "style": "n"},
                    {"text": "初稿与内部评审", "style": "k"},
                    "形成规则、判据与场景初稿并内部评审；未验证事项单独标注",
                    {"text": "初稿与未验证项 · 补充缺口资料", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "P4", "style": "n"},
                    {"text": "评审与定稿", "style": "k"},
                    "贵司评审，逐条答复并修订，形成定稿",
                    {"text": "定稿 · 贵司组织评审并签署确认", "style": "e"},
                ],
            ),
        ],
        [46, 150, 520, 240],
        Inches(4.58),
        Inches(1.92),
        pad=PAD,
        v_anchor=MSO_ANCHOR.MIDDLE,
    )
    note(
        s,
        "结论口径：",
        "每条结论须能进入实施排期。不能定论的写出前置条件与责任方；未验证事项单独标注，不与已验证结论混列。",
    )


def support_items(prs):
    s = new_slide(prs)
    rail(s, "10", "Support")
    eyebrow(s, "模块三", "服务内容  ·  1 / 3")
    title(s, "售后")
    sub(
        s,
        "售后覆盖已交付的出表程序、核对表模板、抽取与核对规则，以及培训中由贵司新增并登记的配置。",
        "下表列出四项服务内容、触发条件与输出物。",
    )
    put_table(
        s,
        ["编号", "服务项", "具体工作", "触发", "输出物"],
        [
            (
                "row",
                [
                    {"text": "S1", "style": "n"},
                    {"text": "程序与规则版本维护", "style": "k"},
                    "合入新增配置并统一命名；发布前样例回归，说明影响范围",
                    {"text": "按版本发布", "style": "c", "sub": "新增或规范调整时"},
                    {"text": "版本更新包\n更新说明", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "S2", "style": "n"},
                    {"text": "样例回归", "style": "k"},
                    "维护基线核对表；变更后全量重跑，差异定位到字段",
                    {"text": "每次变更后", "style": "c", "sub": "发布前强制执行"},
                    {"text": "回归报告\n差异清单", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "S3", "style": "n"},
                    {"text": "缺陷分级响应", "style": "k"},
                    "按第 11 页分级受理与修复；一级缺陷修复前提供临时出表路径",
                    {"text": "按事件", "style": "c", "sub": "贵司提交后启动"},
                    {"text": "处理记录\n修复版本", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "S4", "style": "n"},
                    {"text": "使用答疑与代码走查", "style": "k"},
                    "受理出表与扩展问题；对新规则走查，高频问题整理为补充材料",
                    {"text": "按需受理", "style": "c", "sub": "服务期内持续提供"},
                    {"text": "答疑记录\n走查意见", "style": "e"},
                ],
            ),
        ],
        [46, 168, 430, 130, 132],
        TABLE_TOP,
        TABLE_H,
        pad=PAD,
        v_anchor=MSO_ANCHOR.MIDDLE,
    )
    note(
        s,
        "关于 S2：",
        "日常不可见，却是判断本次变更是否影响已交付样例的依据。不做逐项比对，差异不会在当期被发现。",
    )


def support_flow(prs):
    s = new_slide(prs)
    rail(s, "11", "Support")
    eyebrow(s, "模块三", "响应分级与处理流程  ·  2 / 3")
    title(s, "售后")
    sub(
        s,
        "按对贵司作业的影响分级，不按技术复杂度。响应时限与服务期限在合同附件中另行约定。",
        "下表分列分级口径与处理流程。",
    )
    put_table(
        s,
        ["级别", "判定标准", "处理方式", "闭环条件"],
        [
            ("grp", "分级口径", "贵司接口人提出，双方确认后进入处理"),
            (
                "row",
                [
                    {"text": "一级", "style": "k"},
                    "已交付出表无法运行，或核对表不可用，作业无法继续",
                    "优先处理；修复前提供临时出表路径；每日通报",
                    {"text": "修复发布并通过样例回归", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "二级", "style": "k"},
                    "可以出表但抽出值有偏差，或耗时显著上升",
                    "排入最近版本；更新说明列明影响范围",
                    {"text": "差异消除并通过样例回归", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "三级", "style": "k"},
                    "改进建议、新场景需求、文档补充，不影响当前作业",
                    "按批纳入版本计划，或书面说明不采纳理由",
                    {"text": "纳入版本计划，或书面说明不采纳理由", "style": "e"},
                ],
            ),
        ],
        [70, 300, 400, 186],
        TABLE_TOP,
        Inches(2.34),
        pad=PAD,
        v_anchor=MSO_ANCHOR.MIDDLE,
    )
    put_table(
        s,
        ["步骤", "名称", "工作内容", "贵司需提供"],
        [
            ("grp", "处理流程", "一级与二级全程执行；三级并入版本计划"),
            (
                "row",
                [
                    {"text": "01", "style": "n"},
                    {"text": "受理与定级", "style": "k"},
                    "接收问题描述，确认影响范围，双方确认级别",
                    {"text": "问题描述与影响说明", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "02", "style": "n"},
                    {"text": "复现与定位", "style": "k"},
                    "在本机复现，定位到具体字段、规则与页码",
                    {"text": "可复现的规格书与出表记录", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "03", "style": "n"},
                    {"text": "修复与验证", "style": "k"},
                    "修复后在实际运行环境验证，并对受影响样例做回归",
                    {"text": "确认修复结果符合预期", "style": "e"},
                ],
            ),
            (
                "row",
                [
                    {"text": "04", "style": "n"},
                    {"text": "发布与归档", "style": "k"},
                    "随版本发布，记录成因与规避方式",
                    {"text": "接口人签署版本验收", "style": "e"},
                ],
            ),
        ],
        [70, 140, 520, 226],
        Inches(4.34),
        Inches(2.16),
        pad=PAD,
        v_anchor=MSO_ANCHOR.MIDDLE,
    )
    note(
        s,
        "临时出表",
        "仅用于一级缺陷，产出须带检索状态与原文。新功能、新类型规格书与未约定的公网识别不计入当前售后。",
    )


def support_duty(prs):
    s = new_slide(prs)
    rail(s, "12", "Support")
    eyebrow(s, "模块三", "双方职责  ·  3 / 3")
    title(s, "售后")
    sub(
        s,
        "我方负责系统持续可用，贵司配合提供质量判据与复现材料。",
        "下表列明服务期内双方各自承担的事项。",
    )
    put_table(
        s,
        ["编号", "事项", "说明"],
        [
            ("grp", "我方职责", "服务期内承担"),
            (
                "row",
                [
                    {"text": "M1", "style": "n"},
                    {"text": "程序、规则与模板的版本维护", "style": "k"},
                    "合入新增内容、统一规范、发布更新包并出具说明；维护禁用公网接口清单",
                ],
            ),
            (
                "row",
                [
                    {"text": "M2", "style": "n"},
                    {"text": "样例回归的维护与运行", "style": "k"},
                    "维护每份已交付样例的基线核对表，变更后全量重跑并出具报告",
                ],
            ),
            (
                "row",
                [
                    {"text": "M3", "style": "n"},
                    {"text": "缺陷受理与修复", "style": "k"},
                    "按分级口径受理、复现、定位、修复、验证与发布，并记录成因",
                ],
            ),
            (
                "row",
                [
                    {"text": "M4", "style": "n"},
                    {"text": "使用答疑与代码走查", "style": "k"},
                    "受理填表人与开发人员的技术问题，对新规则走查并给修改建议",
                ],
            ),
            ("grp", "贵司职责", "配合事项"),
            (
                "row",
                [
                    {"text": "G1", "style": "n"},
                    {"text": "提供可复现材料", "style": "k"},
                    "提交缺陷时附带可复现该问题的规格书、底稿与出表记录",
                ],
            ),
            (
                "row",
                [
                    {"text": "G2", "style": "n"},
                    {"text": "确认质量判据", "style": "k"},
                    "质量判据由贵司制定并签署；变更时书面通知，我方负责固化与校验",
                ],
            ),
            (
                "row",
                [
                    {"text": "G3", "style": "n"},
                    {"text": "指定接口人", "style": "k"},
                    "指定固定接口人，负责缺陷定级确认、版本验收与判据签署",
                ],
            ),
        ],
        [50, 250, 706],
        TABLE_TOP,
        TABLE_H,
        pad=PAD,
        v_anchor=MSO_ANCHOR.MIDDLE,
    )
    note(
        s,
        "范围变更：",
        "以书面变更单为准，须写明对交付物与进度的影响。配合事项延迟的，节点顺延。具体条款以合同及其附件为准。",
    )


def main() -> None:
    prs = Presentation()
    prs.slide_width = W
    prs.slide_height = H
    cover(prs)
    training_scope(prs)
    training_outline(prs)
    training_rules(prs)
    training_accept(prs)
    consult_items(prs)
    consult_scenes(prs)
    consult_work(prs)
    consult_deliver(prs)
    support_items(prs)
    support_flow(prs)
    support_duty(prs)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    prs.save(OUT_NEW)
    print(f"wrote {OUT} ({N_SLIDES} slides)")
    print(f"wrote {OUT_NEW}")


if __name__ == "__main__":
    main()
