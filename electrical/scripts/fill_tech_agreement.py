"""填写《智能体开发技术协议》模板中的青色栏（乙方填写）。

黄色栏（吉利写）、项目名称、合同编号、签订时间、甲方名称、联络人电话邮箱不填写。
灰色填写说明填完后删除。
空白模板若不在 Downloads，则在已填稿上替换各节正文（不重复插入）。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from docx.text.paragraph import Paragraph
from lxml import etree

SRC_TEMPLATE = Path("/Users/wwj/Downloads/AI -智能体开发技术协议模板-研发域AI_260825.docx")
FILLED_SRC = Path("/Users/wwj/电子电器项目/electrical/docs/电子电器-智能体开发技术协议-乙方填写稿.docx")
OUT_DESKTOP = Path("/Users/wwj/Desktop/电子电器-智能体开发技术协议-乙方填写稿.docx")
OUT_REPO = FILLED_SRC
OUT_MATERIALS = Path("/Users/wwj/电子电器项目/资料/电子电器-智能体开发技术协议-乙方填写稿.docx")

PARTY_B = "kMind"  # 工商全称以合同签署页为准，此处不杜撰

# 填写原则：①按须满足的十一项功能写技术要求；②按实际项目要求写，立项不以 9 月需求拆解是否验收通过为卡点。
# 本期（至 2026-12-31）验收短期五项；中期 2027、长期 2028 不纳入本期验收。
# 不写院方、不点名咨询/方案汇报材料、不编造电话邮箱合同编号。
# 9 月无 31 日，协议写 9 月 30 日。
CONTENT: dict[str, list[str]] = {
    "项目背景": [
        "甲方电子电器开发需开展客户规格书（SOR）参数提取、架构文档处理、IO 口规划、企标测试、CE BOM 编制、原理图与布局检查、方案比对、架构图绘制及软件建模求解等工作。上述工作目前主要依靠人工完成，作业周期较长，口径难以统一。",
        "本项目由乙方分短期、中期、长期三个阶段实施，实现下列十一项功能。",
        "短期功能：",
        "第 1 项：参数提取。自多语言 PDF、Word、Excel 客户规格书（SOR）提取参数，填入 Excel。现行人工填报约需三至五个工作日；该项已具备实施基础。",
        "第 2 项：架构文档处理。现行文档无统一固定模板，需参考过往文档填报；架构规则由甲方确认。",
        "第 3 项：IO 口规划。以 TC499 等型号为例，对照 PDF 数据手册生成初始配置表，供人工确认修改。",
        "第 4 项：企标测试项提取、按项目调整及测试清单对比；有固定规则的测试用例可辅助生成；测试报告、方案按甲方确认的阶段模板填报。",
        "第 5 项：CE BOM 输出。自物料手册提取长、宽、高、重量等信息，按甲方确认的表格式以 Excel 输出。",
        "中期功能：",
        "第 6 项：原理图检查。对照标准电路库排查漏接、短路等，输出原理图检查单（checklist）。",
        "第 7 项：布局检查（Layout）。将甲方提供的经验规则转化为自动校验，仅异常项提交人工核查。",
        "第 8 项：方案比对与筛选，并按甲方确认的权重输出推荐方案。",
        "第 9 项：根据方案编制比较报告。",
        "长期功能：",
        "第 10 项：架构图绘制。",
        "第 11 项：软件建模求解。对接 Maxwell 等甲方指定软件及求解器，辅助生成报告，对照指标判断，并按预设权重筛选。",
    ],
    "工作内容原则": [
        "按项目背景所列十一项功能，分短期、中期、长期实施，按节点交付，由甲方确认。",
        "各功能分别提交交付物，不得在项目末期一次性交付。范围变更须经书面确认后执行。",
        "交付物须有依据。程序及甲方提供的材料仅在甲方指定场所使用，不得调用公网识别服务，不得用于本项目以外用途。",
    ],
    "甲方": [
        "指定固定接口人，确认十一项功能的范围、各节点交付形态及验收口径。",
        "按照第五节，于对应节点前提供所需材料。",
        "组织试用与复核，按约定时点确认交付物。双方每周同步进度；需求对接密集阶段配合乙方驻场。",
        "提供一至两台 Windows 工位计算机及必要安装权限。",
    ],
    "乙方": [
        "按十一项功能实施本项目，并按节点提交交付物。",
        "在甲方指定场所完成部署、试装及培训；需求对接密集阶段可安排驻场。",
        "在约定服务期内提供版本维护、样例回归、缺陷响应及使用答疑。",
        "甲方提供的材料仅用于本项目，不得上传公网。按周通报进度及需甲方配合的事项。",
    ],
    "三、主要工作计划": [
        "2026 年 9 月 30 日：完成第 1 项参数提取、第 2 项架构文档处理。",
        "2026 年 10 月 31 日：完成第 3 项 IO 口规划，提交 IO 口初始配置表。",
        "2026 年 11 月 30 日：完成第 4 项，提交测试清单、对比表及测试用例。",
        "2026 年 12 月 31 日：完成第 5 项，按甲方确认的表格式以 Excel 输出 CE BOM。",
        "2027 年 12 月 31 日：完成第 6 项至第 9 项，提交原理图检查单（checklist）、布局检查单（Layout）及异常项、推荐方案及比较报告。",
        "2028 年 12 月 31 日：完成第 10 项架构图绘制、第 11 项软件建模求解（对接 Maxwell 等甲方指定软件）。",
    ],
    "四、乙方主要工作内容": [
        "第 1 项：自 PDF、Word、Excel 客户规格书（SOR）提取参数，输出 Excel 核对表。字段以甲方确认的模板为准。",
        "第 2 项：参考甲方过往架构文档辅助填报。现行文档无统一固定模板，架构规则由甲方确认后迭代。",
        "第 3 项：对照芯片数据手册（如 TC499 等）生成 IO 口初始配置表，供人工确认修改。端口命名及约束由甲方确认。",
        "第 4 项：从企标提取测试项并按项目调整，一周内建立清单结构，与甲方指定供应商沟通后迭代，输出测试清单及对比表。有固定规则的测试用例可辅助生成；测试报告、方案按甲方确认的阶段模板填报。",
        "第 5 项：自物料手册提取长、宽、高、重量等信息，按甲方确认的表格式以 Excel 输出 CE BOM。",
        "第 6 项：对照标准电路库排查漏接、短路等，输出原理图检查单（checklist）。",
        "第 7 项：将甲方 Layout 经验规则转化为自动校验规则，输出布局检查单及异常项，供人工核查。",
        "第 8 项：开展方案比对与筛选，按甲方确认的权重输出推荐方案。",
        "第 9 项：根据方案编制比较报告。",
        "第 10 项：按甲方确认的绘制口径编制架构图。",
        "第 11 项：对接 Maxwell 等甲方指定软件及求解器，辅助生成报告；求解结果对照甲方指标判断，并按预设权重筛选。脚本接口、指标及求解边界由甲方确认。",
        "服务期内的维护、回归、缺陷响应及答疑。",
    ],
    "五、相关附件": [
        "甲方应当于对应节点前提供下列材料。",
        "第 1 项：现行核对表、目标出表模板、代表性规格书及脱敏口径。",
        "第 2 项：过往架构文档、填报口径及已有规则（如有）。",
        "第 3 项：芯片数据手册（含 TC499 等型号）、端口命名及约束。",
        "第 4 项：企标、既有测试项、测试用例规则，以及测试报告、方案模板。",
        "第 5 项：物料手册或器件说明、甲方确认的 CE BOM 表格式。",
        "第 6 项：标准电路库及原理图检查规则。",
        "第 7 项：Layout 检查经验规则。",
        "第 8 项、第 9 项：方案比对样本、筛选权重及报告模板。",
        "第 10 项：架构图绘制口径及样例。",
        "第 11 项：Maxwell 等软件环境、脚本接口、求解指标及权重。",
        "乙方交付物见第六节。",
    ],
    "基础要求": [
        "十一项功能以各节点输出物为交付形态，具体见输出物要求。",
        "运行环境为 Windows 10 或 Windows 11 工位计算机。程序部署于甲方指定场所，可不连接公网运行。试装一至两台。",
        "第 1 项支持 PDF、Word、Excel；单份规格书处理一种语言（中文、英文或德文）；核对表表头为中文。数字化文稿每份约五分钟，以工位实测为准。扫描件是否纳入及处理时效，由双方书面确认后实施。",
        "范围不含调用公网识别服务、接入甲方既有业务系统，以及原理图、布局的完全自动出图。",
    ],
    "项目要求": [
        "交付物按照第三节节点按时提交，由甲方确认。不得在项目末期一次性交付。预计不能按期的，乙方应提前书面说明原因及调整建议，经甲方确认后执行。",
        "双方每周同步一次进度。乙方按周通报进展、风险及需甲方配合事项。",
        "驻场地点为甲方指定场所。驻场人员为实施与培训 1 人（可由开发人员兼任）；需求对接密集阶段可增派开发人员。驻场安排在需求对接、工位试装、试用及各节点验收期间。",
        "甲方指定固定接口人 1 人，并安排业务人员、试用人员配合口径确认、试用与复核。",
        "程序在甲方指定场所试装一至两台。甲方提供 Windows 工位计算机及必要安装权限。",
        "范围变更须经双方书面确认后实施。",
    ],
    "输出物要求": [
        "（一）功能实现交付物",
        "为实现十一项功能，乙方交付下列程序及文档。",
        "1. 工位部署程序（含可运行程序、必要配置及对应功能模块），按第三节节点分项交付。",
        "2. 使用说明，含智能体架构说明、主要任务流程、操作步骤、工位部署及注意事项。",
        "3. 服务期内的版本更新说明及样例回归报告。",
        "（二）功能输出物",
        "各项功能运行后形成的业务文件为功能输出物。其格式、表结构、字段及填写口径须完全符合甲方确认的模板；甲方调整模板的，乙方按确认结果更新。",
        "第 1 项：规格书参数核对表（Excel）。",
        "第 2 项：架构文档填报稿。",
        "第 3 项：IO 口初始配置表。",
        "第 4 项：企标测试清单、测试项对比表、测试用例，以及按阶段模板填报的测试报告、方案。",
        "第 5 项：CE BOM（Excel）。",
        "第 6 项：原理图检查单（checklist）。",
        "第 7 项：布局检查单（Layout）及异常项。",
        "第 8 项：推荐方案。",
        "第 9 项：比较报告。",
        "第 10 项：架构图。",
        "第 11 项：软件建模求解结果，以及对照指标、按权重筛选形成的报告。",
    ],
    "交付和验收要求": [
        "（一）交付与验收节点",
        "按第三节节点分阶段交付，由甲方确认。",
        "2026 年 9 月 30 日完成第 1 项、第 2 项；10 月 31 日完成第 3 项；11 月 30 日完成第 4 项；12 月 31 日完成第 5 项。",
        "2027 年 12 月 31 日完成第 6 项至第 9 项；2028 年 12 月 31 日完成第 10 项、第 11 项。",
        "输出物质量标准及量化通过阈值由甲方按照第七节确定。第七节未确定前，量化指标不作为本协议的通过条件。",
        "（二）智能体架构与验收",
        "本项目按十一项功能交付智能体能力，分模块、分节点实施。短期、中期、长期功能在同一工位环境登录和使用，按功能模块分别交付、分别验收。智能体验收按下列六类进行。",
        "技术架构与模型能力：工位部署采用接入、识别、处理、输出四层架构。接入层提供工位登录与使用权限。识别层在甲方指定场所完成本机识别，读取 PDF、Word、Excel 等材料。处理层按各功能分别实现提取、填报、检查、比对或求解，并结合本机大模型辅助。输出层按甲方确认的模板生成输出物，供人工确认。乙方书面说明本机大模型名称及版本，更换须经双方书面确认。乙方随各节点工位部署提交该节点功能模块说明、总体架构说明、主要任务流程，以及固定流程与模型辅助的区分说明，作为验收依据之一。各功能按既定步骤执行；识别或提取失败、依据不足时，应提示并留空或标为待确认，不得静默填写，由人工确认后继续。",
        "知识库与记忆能力：依据甲方按第五节提供的规格书、企标、手册、规则及过往文档等，在指定场所形成对应功能的知识库，经甲方确认后使用。知识库内容、模板及规则变更，经甲方确认后更新。第 1 项核对表应能回溯至规格书页码及原文摘录，并标示供人工确认的项。",
        "任务执行效果：各功能按既定步骤生成对应输出物，由人工确认。任务成功率、召回率等以第七节及双方确认的样例为准。第 1 项处理时效见基础要求，以工位实测为准。",
        "安全与合规：甲方材料及运行数据仅在指定场所使用，不调用公网识别服务，不上传公网，不用于模型训练，不得用于本项目以外用途。项目结束或甲方提出时，按甲方要求删除或交还。经工位登录后使用，并保留任务起止、输入文件及输出文件记录，供甲方查阅；保存期限由双方确认。",
        "工程成熟度：服务期内提供版本维护、缺陷响应及样例回归。甲方可提供样例，用于回归确认。乙方在工位交付时完成使用培训。",
        "成本与商务：本机部署运行，不向公网模型服务支付调用费用。价款、部署及维护费用以主合同及报价为准；更换模型或调整范围的，按主合同或书面变更执行。",
        "（三）监督机制",
        "甲方有权对项目进度、驻场情况、工位部署及交付物进行监督。乙方应按项目要求报送周进度，并参加双方每周同步。",
        "各节点交付后由甲方组织验收。验收采用问询、文档审查、工位演示及样例实测。验收不合格的，甲方书面提出整改意见，乙方在限期内完成整改并申请复验。",
        "甲方发现程序或材料的使用不符合本协议约定的，有权要求乙方立即纠正。",
        "（四）违约处理",
        "乙方未按约定节点交付，或功能输出物不符合甲方确认模板的，甲方有权要求限期整改；逾期未完成整改的，按照主合同约定处理。",
        "乙方违反指定场所使用、不得调用公网识别或材料不得用于本项目以外用途等约定的，甲方有权要求停止相关使用，并按照主合同及保密约定追究责任。",
        "因甲方未按第五节及时提供材料或未按约定确认，导致乙方无法按期交付的，相应节点顺延，乙方不因此承担迟延责任。",
        "本技术协议未约定的违约事项，适用主合同；本技术协议与主合同不一致的，以主合同为准。",
        "（五）功能输出物量化验收",
        "甲方按验收记录表对功能输出物逐项记录实测值。记录栏目可包括：第 3 项 IO 口规划的匹配、降额及安全相关项；第 6 项原理图检查单的类别覆盖、强制项及 EMC 相关项；第 7 项布局检查单的强制项、综合评分及 N/A 项依据；第 5 项 CE BOM 的一致性、禁用物料及认证覆盖等。具体通过阈值由甲方按第七节确定。",
        "第 1 项以核对表可追溯、无依据不填为验收方式；如甲方将需求覆盖、双向追溯等列入第七节，从其规定。",
    ],
    "人员要求": [
        "乙方投入项目负责人 1 人，开发人员不少于 2 人，实施与培训 1 人（可由开发人员兼任）。驻场安排见项目要求。",
        "甲方指定固定接口人 1 人，业务人员不少于 1 人参与口径确认与复核，并指定试用人员。",
    ],
}

# 替换已填稿时，删到下一标题为止（含空段）
NEXT_HEADING: dict[str, str] = {
    "项目背景": "工作内容原则",
    "工作内容原则": "二、甲乙双方基础职责",
    "甲方": "乙方",
    "乙方": "三、主要工作计划",
    "三、主要工作计划": "四、乙方主要工作内容",
    "四、乙方主要工作内容": "五、相关附件",
    "五、相关附件": "六、项目及输出物要求",
    "基础要求": "项目要求",
    "项目要求": "输出物要求",
    "输出物要求": "交付和验收要求",
    "交付和验收要求": "人员要求",
    "人员要求": "项目履行地点",
}


def _clear_highlight(paragraph: Paragraph) -> None:
    for el in paragraph._p.iter(qn("w:highlight")):
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)


def _set_run_font(run) -> None:
    run.font.name = "宋体"
    run.font.size = Pt(10.5)
    run.bold = False
    run.font.color.rgb = None
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = etree.SubElement(rPr, qn("w:rFonts"))
    rFonts.set(qn("w:ascii"), "宋体")
    rFonts.set(qn("w:hAnsi"), "宋体")
    rFonts.set(qn("w:eastAsia"), "宋体")
    rFonts.set("hint", "eastAsia")
    for tag in ("w:b", "w:bCs", "w:highlight", "w:i"):
        for node in rPr.findall(qn(tag)):
            if tag in ("w:b", "w:bCs"):
                node.set(qn("w:val"), "0")
            elif tag == "w:highlight":
                rPr.remove(node)


def insert_after(paragraph: Paragraph, text: str) -> Paragraph:
    new_p = OxmlElement("w:p")
    paragraph._p.addnext(new_p)
    new_para = Paragraph(new_p, paragraph._parent)
    run = new_para.add_run(text)
    _set_run_font(run)
    pf = new_para.paragraph_format
    pf.first_line_indent = Cm(0.74)
    pf.line_spacing = 1.5
    pf.space_after = Pt(0)
    pf.space_before = Pt(0)
    return new_para


def insert_block(heading: Paragraph, paragraphs: list[str]) -> None:
    last = heading
    for text in paragraphs:
        last = insert_after(last, text)


def delete_until_heading(heading: Paragraph, stop: str) -> None:
    """删除 heading 之后、下一标题之前的正文（含空段）。"""
    to_remove = []
    el = heading._p.getnext()
    while el is not None:
        nxt = el.getnext()
        if el.tag == qn("w:p"):
            text = "".join(el.itertext()).strip()
            if text == stop or text.startswith(stop):
                break
            to_remove.append(el)
        el = nxt
    parent = heading._p.getparent()
    for el in to_remove:
        parent.remove(el)


def find_para(doc: Document, *, exact: str | None = None, startswith: str | None = None) -> Paragraph:
    for p in doc.paragraphs:
        t = p.text.strip()
        if exact is not None and t == exact:
            return p
        if startswith is not None and t.startswith(startswith):
            return p
    raise KeyError(exact or startswith)


def set_plain_heading(paragraph: Paragraph, text: str) -> None:
    if paragraph.runs:
        paragraph.runs[0].text = text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(text)
    _clear_highlight(paragraph)


def fill_party_b(doc: Document) -> None:
    p = find_para(doc, startswith="乙")
    # 「乙  方： XX公司」→ 「乙  方： kMind」
    if len(p.runs) >= 3:
        p.runs[1].text = PARTY_B
        p.runs[2].text = ""
    elif len(p.runs) >= 2:
        p.runs[1].text = PARTY_B
    else:
        p.add_run(PARTY_B)
    _clear_highlight(p)


def numbered_body(key: str, paras: list[str]) -> list[str]:
    numbered_heads = {
        "工作内容原则",
        "甲方",
        "乙方",
        "三、主要工作计划",
        "基础要求",
        "项目要求",
        "人员要求",
    }
    if key == "五、相关附件":
        return paras
    if key in numbered_heads:
        return [f"{i}. {t}" for i, t in enumerate(paras, 1)]
    return paras


def apply_content(doc: Document, *, replace_existing: bool) -> None:
    fill_party_b(doc)

    set_plain_heading(find_para(doc, startswith="五、相关附件"), "五、相关附件")
    set_plain_heading(find_para(doc, startswith="人员要求"), "人员要求")

    for key, paras in CONTENT.items():
        heading = find_para(doc, exact=key)
        _clear_highlight(heading)
        if replace_existing:
            delete_until_heading(heading, NEXT_HEADING[key])
        insert_block(heading, numbered_body(key, paras))

    for title in ("一、项目背景及原则", "二、甲乙双方基础职责", "六、项目及输出物要求"):
        _clear_highlight(find_para(doc, exact=title))


def save_all(doc: Document) -> None:
    OUT_DESKTOP.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPO.parent.mkdir(parents=True, exist_ok=True)
    OUT_MATERIALS.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = Path("/tmp/tech-agreement-out.docx")
    doc.save(str(tmp_out))
    shutil.copy2(tmp_out, OUT_DESKTOP)
    shutil.copy2(tmp_out, OUT_REPO)
    shutil.copy2(tmp_out, OUT_MATERIALS)
    print(f"wrote {OUT_DESKTOP}")
    print(f"wrote {OUT_REPO}")
    print(f"wrote {OUT_MATERIALS}")


def main() -> None:
    tmp = Path("/tmp/tech-agreement-src.docx")
    if SRC_TEMPLATE.is_file():
        shutil.copy2(SRC_TEMPLATE, tmp)
        replace_existing = False
    elif FILLED_SRC.is_file():
        shutil.copy2(FILLED_SRC, tmp)
        replace_existing = True
    else:
        raise FileNotFoundError(f"missing template {SRC_TEMPLATE} and filled {FILLED_SRC}")

    doc = Document(str(tmp))
    apply_content(doc, replace_existing=replace_existing)
    save_all(doc)


if __name__ == "__main__":
    main()
