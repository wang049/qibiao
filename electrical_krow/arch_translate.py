"""电驱需求拆解 · 外文条款中文翻译（同格「原文 / 中文译文」双语对照）。

原则：
1. 原文摘录一个字符不改；中文译文以「 / 中文译文」附在同一格内（多行整表以换行「/ 中文译文」附在后面）。
2. 所有数值、单位、标准号（ISO/IEC/GB/ECE/CISPR/ES/MS/AEC-Q 等）、信号与专有缩写（HMC/LDC/XCM/PCM/MCU/CAN/PWM/HVIL 等）原样保留，绝不换算或改写。
3. 有模型（ask）时按批请模型直译；无模型或模型未覆盖的条目，走车规电驱工程句式与术语词典规则翻译。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

Ask = Callable[[list[dict[str, str]]], str]

_CJK = re.compile(r"[\u4e00-\u9fff]")
_LATIN = re.compile(r"[A-Za-z\u00c0-\u024f]")
_LATIN_WORD = re.compile(r"[A-Za-z\u00c0-\u024f]{2,}")
_CYRILLIC_WORD = re.compile(r"[\u0400-\u04ff]{2,}")
_HANGUL = re.compile(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]")
_KANA = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff]")
_HANGUL_GAP = re.compile(r"(?<=[\uac00-\ud7af\u3130-\u318f])[ \t]+(?=[\uac00-\ud7af\u3130-\u318f])")

_BATCH_SIZE = 20

_TRANSLATE_PROMPT = (
    "你是汽车电驱系统（逆变器 Inverter、低压直流变换器 LDC、电机、减速器）需求规格书（SR/SOR）的专业多语种译中助手。"
    "原文可能是英文、韩文、日文、德文、法文、俄文或多语种混排，请将给出的每条非中文需求原文准确直译为简练、规范的中文工程表述。\n"
    "严格要求：\n"
    "1. 只翻译原文中实际存在的意思，绝不添加原文没有的结论（不要写“满足”“一致”“以评估为准”等评审意见）。\n"
    "2. 原文中的所有数值、公差、单位（如 15 years / 300,000 km、-40 ~ 105 °C、1mA↓、90%↑）、标准代号（如 ISO 26262、IEC 60664-1、CISPR 25、LV 124、ES95490-10、MS201-02、QC/T 895、GB/T 24347）、专有缩写（如 HMC、HKMC、LDC、Inverter、XCM、PCM、P1、P3、T-car、Proto、SOP、DV、PV、ESIR、ISIR、EOL、DFMEA、WCA、3DCS）必须原样保留，严禁换算或遗漏。\n"
    "3. 若条目是表格行（含「栏目：值 | 栏目：值」），请将栏目名与要求内容（无论英文、韩文、日文、德文等）一并译为清晰的中文。\n"
    "4. 原文有多行时，译文必须逐行对应，行数与原文相同，不要合并、不要重新编号，不要漏掉后面的行。\n"
    "5. 只输出 JSON 数组，每个元素形如 {\"序号\": 1, \"译文\": \"…\"}，不要输出任何额外说明。"
)

# 整句/常用子句级工程翻译（长短语优先匹配，不区分大小写）
_PHRASE_MAP: tuple[tuple[str, str], ...] = (
    # 概述与通用条款
    (
        "this document summarizes the requirements of the engineering design team of the research institute to select the ldc (low voltage dcdc converter) supplier",
        "本文件汇总了研究院工程设计团队针对 LDC（低压直流变换器）供应商选型的技术要求",
    ),
    (
        "including general requirements related to design and development, and performance requirements for each system unit and unit of parts",
        "涵盖设计与开发通用要求以及各系统单元与零部件的性能要求",
    ),
    (
        "it is about the part development procedure, role and responsibility",
        "规定了零部件开发流程、角色与职责（R&R）",
    ),
    (
        "the supplier participating in the bidding must present the specifications satisfying the contents of this document",
        "参与投标的供应商必须提交满足本文件内容的规格方案",
    ),
    (
        "all requirements apply equally for the entire vehicle operation period, including from the supplier selection stage to the discontinuation stage",
        "所有要求从供应商定点阶段至停产阶段的整个车辆运行周期内均同等适用",
    ),
    (
        "plans are for reference only , details may changed based on the specific h/kmc schedules",
        "计划仅供参考，具体细节可能根据 H/KMC 具体日程调整",
    ),
    (
        "plans are for reference only ， details may changed based on the specific h/kmc schedules",
        "计划仅供参考，具体细节可能根据 H/KMC 具体日程调整",
    ),
    (
        "investment cost should include development, test (function/performance, pre dv, dv and pv), sample production cost and mold cost",
        "投资费用应包含开发、测试（功能/性能、Pre-DV、DV 及 PV）、样件制作费及模具费",
    ),
    (
        "the number of t-car and proto evaluation/test samples is approximately",
        "T-car 与 Proto 评估/测试样件数量分别约为",
    ),
    (
        "before estimating development cost, hmc discuss is needed",
        "在估算开发费用前需与 HMC 协商确认",
    ),
    (
        "submit detailed plans including design, production and verification in the proposal",
        "在技术方案书中提交包含设计、生产及验证的详细计划",
    ),
    (
        "excluding processes jointly conducted with h/w",
        "不含与硬件（H/W）联合开展的流程",
    ),
    (
        "excluding functional safety processes",
        "不含功能安全流程",
    ),
    (
        "submit design specification for all sensing filter including hw filter from sensing point to input of micom . and sw filter for all sensing value",
        "提交所有采样滤波器的设计规范，包括从采样点到 MCU 输入端的硬件滤波器以及所有采样值的软件滤波器",
    ),
    (
        "although the test cases provided by hmc are representative of the various operating environment, they could not guarantee immunity to all worst conditions",
        "尽管 HMC 提供的测试用例代表了各种运行环境，但无法保证覆盖所有极限最坏工况",
    ),
    (
        "the supplier should derive and verify more severe test cases considering the characteristics of the application and external environmental factors",
        "供应商应结合应用特性与外部环境因素推导并验证更严苛的测试用例",
    ),
    (
        "submit design review results at every vehicle schedule.(the design review form should follow hmc’s form)",
        "在每个整车节点提交设计评审结果（设计评审表须采用 HMC 格式）",
    ),
    (
        "if the hmc requirements are not satisfied or the work products are not submitted by the due date, a countermeasure document including the following must be submitted",
        "若未满足 HMC 要求或未按期提交工作产物，必须提交包含以下内容的对策报告",
    ),
    (
        "schedule for submitting improvement plans and verification results for unsatisfactory requirements",
        "未满足项的整改计划与验证结果提交日程",
    ),
    (
        "reason for not submitting and future plans to ensure submission by the due date",
        "未按期提交的原因及确保后续按期提交的计划",
    ),
    (
        "s/w verification reports shall include s/w static testing and dynamic(unit/integration) testing reports required by hmc",
        "软件验证报告应包含 HMC 要求的软件静态测试及动态（单元/集成）测试报告",
    ),
    (
        "information on the specification operation plan of vehicle to set the ldc composition, production volume, and delivery conditions is as follows",
        "用于确定 LDC 构成、产量及交付条件的整车规格运营计划信息如下",
    ),
    (
        "detailed specification classification and structural design should be discussed and recorded in the proto approval request diagram",
        "详细规格分类与结构设计应协商确定并记录在 Proto 承认图申请图中",
    ),
    # 法规与认证
    (
        "the following requirements must be met in accordance with the applicable laws and regulations of each country where",
        "必须满足销售国家/地区的适用法律法规要求：",
    ),
    (
        "the applicable laws and regulations for each country of our",
        "必须满足我司车型各销售国家/地区的适用法律法规：",
    ),
    (
        "the regulation items in the table below are the minimum regulations of our company, and the laws and regulations of all countries/regions of sale must be satisfied",
        "下表所列法规项为我司最低法规要求，必须满足所有销售国家/地区的法律法规",
    ),
    (
        "the legal items in the table below are the minimum regulations, and the laws and regulations of all countries/regions of sale must be satisfied",
        "下表所列法规项为最低法规要求，必须满足所有销售国家/地区的法律法规",
    ),
    (
        "the relevant laws and regulations related to existing laws and regulations, revised laws and new legislation, notice, environmental regulations, etc. shall be identified at all times, and the results of the review of problems shall be submitted and reflected in the parts to ensure that there are no legal problems",
        "应随时掌握现行法规、修订法规、新立法、公告及环保法规等相关法律法规，提交问题点评审结果并反映到零件设计中，确保无法律法规问题",
    ),
    (
        "it is necessary to be always attentive to the relevant laws and regulations related to existing laws, changed laws, new laws, legal notices, environmental regulations, etc., and to submit the results of the review of whether there are any problems and to reflect them in the parts to ensure that there are no legal problems",
        "应随时关注现行法规、变更法规、新法规、法律公告及环保法规等相关规定，提交是否存在问题的评审结果并反映到零件中，确保无法律法规问题",
    ),
    (
        "in consideration of laws and regulations outside the sales area, it should be possible to respond to the expansion of the sales area",
        "考虑到销售区域以外的法律法规，应具备应对销售区域扩展的能力",
    ),
    (
        "laws and regulations should be considered to be able to respond when the sales area is expanded",
        "应考虑相关法律法规，以便在销售区域扩大时能够対応满足",
    ),
    (
        "it is the responsibility of the supplier in case of dissatisfaction with the regulations on the parts",
        "若零件不满足法规要求，相关责任由供应商承担",
    ),
    (
        "the responsibility for actions and compensation due to dissatisfaction with laws and regulations for systems and components lies with the supplier",
        "因系统或零部件不满足法律法规而产生的处置及赔偿责任由供应商承担",
    ),
    (
        "re-notification will be made when the following regulations are revised or changed, and suppliers must also submit their own confirmation",
        "当下列法规修订或变更时将另行通知，供应商亦须提交自查确认书",
    ),
    (
        "we will notify when the contents of the following laws and regulations are revised or changed, and supplier must also submit their response plan",
        "当下列法律法规内容修订或变更时我方将予以通知，供应商亦必须提交应对方案",
    ),
    (
        "the status of legal investigation/confirmation/compliance will be checked at the time of the inspection council in 4.4, and changes in sales areas will be notified by hmc",
        "法规调查/确认/合规状态将在第 4.4 节评审会时核查，销售区域变更将由 HMC 通知",
    ),
    (
        "prohibition of the use of lead in solder for auto parts within the scope of resource circulation",
        "资源循环范围内汽车零部件焊料禁止含铅要求",
    ),
    (
        "the following items shall be satisfied with respect to the certification requirements of each country of sale",
        "针对各销售国家/地区的认证要求，应满足以下事项",
    ),
    (
        "the following items shall be satisfied with respect to the national certification requirements for",
        "针对国家认证要求，应满足以下事项：",
    ),
    (
        "it must be certified by all countries/regions of sale",
        "必须获得所有销售国家/地区的认证",
    ),
    (
        "the certification matters related to the existing certification, change certification, new enactment certification, and notice shall be identified at all times, and the results of the review of problems shall be submitted and reflected in the parts to ensure that there is no certification problem",
        "应随时掌握现行认证、变更认证、新制定认证及公告相关事项，提交问题评审结果并落实到零件中，确保无认证问题",
    ),
    (
        "in consideration of certification outside the sales area, it should be possible to respond to the expansion of the sales area",
        "考虑到销售区域以外的认证要求，应能应对销售区域的扩展",
    ),
    (
        "it is the responsibility of the supplier in case of dissatisfaction with certification of parts",
        "若零件未能满足认证要求，责任由供应商承担",
    ),
    (
        "when revising or changing the existing certification contents, it will be notified again, and the supplier must also submit its own confirmation",
        "当既有认证内容修订或变更时将再次通知，供应商亦须提交自查确认结果",
    ),
    (
        "the certification plan and certificate after certification shall be submitted to the company before the certification is promoted, and the relevant expenses shall be reflected in the investment cost",
        "推进认证前应向我司提交认证计划，取证后提交认证证书，相关费用计入投资成本",
    ),
    # 市场性 / 寿命 / 质保
    (
        "the following requirements regarding the marketability of our",
        "关于我司车型的市场商品性（Marketability），应满足以下要求",
    ),
    (
        "maintain the single component and system performance, emi & emc, and nvh performance required by the vehicle for the entire vehicle operation period",
        "在整车全寿命运行周期内保持整车要求的单品及系统性能、EMI & EMC 以及 NVH 性能",
    ),
    (
        "the design shall be applied to ensure that the noise generated by the ldc during vehicle driving/charging/v2l is satisfied with the vehicle interior noise regulation",
        "设计应确保车辆行驶/充电/V2L 期间 LDC 产生的噪声满足车内噪声法规要求",
    ),
    (
        "maintain durability against corrosion, collision, flow, deterioration, etc. during the entire vehicle operation period",
        "在整车全寿命运行周期内保持抗腐蚀、碰撞、流体冲刷、老化劣化等耐久性",
    ),
    (
        "ensure as convenience when checking and replacing parts for general maintenance",
        "确保常规维护检查及更换零件时的售后（A/S）便利性",
    ),
    (
        "requirements for performance/quality reliability required by",
        "性能/质量可靠性要求如下：",
    ),
    (
        "the supplier shall predict the target durability through structural analysis and evaluation of the dht, and shall secure a service life of",
        "供应商应通过 DHT 结构分析与评估预测目标耐久性，并确保使用寿命达到",
    ),
    (
        "consent to our quality assurance policy",
        "同意我司质量保证（质保）政策",
    ),
    (
        "present the analysis/durability evaluation results reviewed for the above life assurance",
        "提交针对上述寿命保证所评审的分析/耐久评估结果",
    ),
    (
        "request / consult with hmc for data needed from the vehicle perspective",
        "整车视角所需数据可向 HMC 申请或协商",
    ),
    (
        "the target life of the component is the driving life (15 years) of the vehicle based on the time and driving distance until scrapping",
        "零部件目标寿命以车辆至报废为止的时间与行驶里程为基准（整车行驶寿命 15 年）",
    ),
    (
        "supplier are responsible for issues arising from all environmental conditions",
        "供应商对所有环境条件下发生的问题负责",
    ),
    (
        "regulations and marketability (durability, strength, driving stability, etc.) must be met within the warranty period",
        "质保期内必须满足法规及商品性要求（耐久性、强度、行驶稳定性等）",
    ),
    (
        "the durability mentioned in laws and regulations must be guaranteed",
        "必须保证法律法规中规定的耐久性",
    ),
    (
        "the performance requirements of the ldc and es/ms specifications must be met",
        "必须满足 LDC 性能要求及 ES/MS 标准规范",
    ),
    (
        "mechanical, electrical, corrosion resistance, and chemical resistance of all parts of the ldc shall satisfy the durability life",
        "LDC 所有零部件的机械、电气、耐腐蚀及耐化学性能均应满足耐久寿命要求",
    ),
    (
        "the specifications for hmc's reliability and safety tests must be met",
        "必须满足 HMC 可靠性与安全试验规范要求",
    ),
    (
        "the supplier shall reflect the evaluation from the vehicle perspective. the evaluation report shall be provided",
        "供应商应从整车视角开展评估并提交评估报告（由质量保证部门出具）",
    ),
    (
        "additional costs and weights are not accepted because they do not meet hmc's requirements",
        "因未满足 HMC 要求而增加的额外成本与重量不予认可",
    ),
    (
        "the requirement specification diagram delivered from the supplier expresses only the basic requirements. therefore, in order to guarantee the final quality, it is necessary to submit an approval request diagram containing details",
        "规格要求图仅表达基本要求，为保证最终质量，供应商须提交包含详细参数（尺寸、公差、电气规格等）的承认图申请图",
    ),
    (
        "depending on the internal and external environmental conditions of the ldc, the design should be carried out according to the requirements of",
        "根据 LDC 内外部环境条件，应按照相关标准要求进行防腐设计，且不得因外部腐蚀导致功能与性能异常：",
    ),
    # 机械与结构要求
    (
        "all components must use parts developed for automobiles",
        "所有元器件必须采用车规级开发零件",
    ),
    (
        "it must be designed to prevent water accumulation when mounted on a vehicle",
        "设计上必须防止装车状态下产生积水",
    ),
    (
        "the current-carrying parts and surrounding components must be designed for heat resistance",
        "载流部件及周边零件必须进行耐热设计（含镀层）",
    ),
    (
        "the total connection part must be designed with anti cross thread",
        "所有螺纹连接部位必须采用防错牙（Anti-cross thread）设计",
    ),
    (
        "all inverter components should be designed with 6 - dof constraints, but must not deform during operation",
        "逆变器所有零件应按六自由度（6-DOF）约束设计，且工作期间不得发生变形",
    ),
    (
        "all part designs shall be constrained to 6 degrees of freedom and shall be within the elastic zone of the product operation reference",
        "所有零件设计应满足六自由度约束，并处于产品工作基准的弹性变形范围内",
    ),
    (
        "when fastening plastic parts, the fastening area must use a bushing, and the press-in nut and bushing should protrude at least 0.5 mm above the plastic surface",
        "紧固塑料件时，紧固部位必须使用金属衬套（Bushing），且压入螺母和衬套应高出塑料表面至少 0.5 mm",
    ),
    (
        "when fastening plastic parts, a bushing shall be applied to the fastening part, and the press-fit nut and bushing shall be designed to protrude at least 0.5 mm from the plastic part",
        "紧固塑料件时，紧固部位应采用衬套（Bushing），且压入螺母与衬套设计应高出塑料件表面至少 0.5 mm",
    ),
    (
        "even if a fire occurs inside the inverter, it must be designed so that the fire does not spread to other components",
        "即使逆变器内部起火，其设计也必须防止火势蔓延至其他部件",
    ),
    (
        "it shall be designed mechanically to prevent the spread of fire to other parts in the event of a fire inside the ldc",
        "当 LDC 内部发生起火时，机械结构设计上应防止火势蔓延至其他零件",
    ),
    (
        "it shall be designed mechanically to prevent short circuit in the ldc even when the inside of the part condenses",
        "即使零件内部发生凝露，机械结构设计上也应防止 LDC 内部发生短路",
    ),
    (
        "the bolt spacing should be designed considering vibration, resonance, and sealing of the part",
        "螺栓间距设计应综合考虑零件的振动、共振及密封性能",
    ),
    (
        "the bolt-to-bolt distance fastening pitch should be designed in consideration of vibration, resonance, sealing, etc. of the component",
        "螺栓紧固间距设计应综合考虑部件的振动、共振及密封等因素",
    ),
    (
        "all fastening parts must be designed according to importance, and there should be no stripping",
        "所有紧固件必须按重要度等级进行设计，且不得发生滑牙（Stripping）",
    ),
    (
        "all fastening parts shall be designed to distinguish their importance, and free space for tool tools shall be secured during assembly",
        "所有紧固部位应区分重要度进行设计，并在装配时留出工具操作空间",
    ),
    (
        "connectors should be at least 10mm above the inverter floor and maintain a clearance of at least 25mm from other parts",
        "接插件距逆变器底部应至少 10mm，且与其他零件保持至少 25mm 的间隙",
    ),
    (
        "connectors shall be at least 10mm from the bottom of the ldc and at least 25mm from other parts, and there shall be no problem in maintaining and assembling them",
        "接插件距 LDC 底部应至少 10mm，距其他零件至少 25mm，且维修与装配无干涉问题",
    ),
    (
        "all component assemblies must consist of 2 guide pins",
        "所有部件装配必须设置 2 个导向销（Guide Pins）",
    ),
    (
        "the assembly between all parts shall consist of two guides",
        "所有零件之间的装配应包含两个导向结构",
    ),
    (
        "all fastening points must have sufficient clearance for tool access during assembly",
        "所有紧固点在装配时必须留有足够的工具操作空间",
    ),
    (
        "after installing the inverter in the vehicle, a lifting shape must be applied for the inverter's standalone after-sales service",
        "逆变器装车后，必须设置吊装结构以便于逆变器独立售后维修拆装",
    ),
    (
        "the label must be in a location visible by eye when mounted on the vehicle",
        "铭牌标签必须位于装车状态下肉眼可见的位置",
    ),
    (
        "the inlet/outlet nipple shape of the cooling circuit must be designed for our quick connector",
        "冷却回路进出水口水嘴（Nipple）形状必须按适配我司快插接头进行设计",
    ),
    (
        "the vehicle assembly part (connector/nipple) must be designed considering our vehicle packaging/assembly workability",
        "整车装配接口部位（接插件/水嘴）设计必须考虑我司整车布置与装配作业性",
    ),
    (
        "the vehicle package interface requirements shall be satisfied",
        "应满足整车布置（Package）接口要求",
    ),
    (
        "the weight and volume requirements of the vehicle mounting conditions shall be satisfied. the hmc warehousing weight tolerance shall be managed within",
        "应满足整车安装条件下的重量与体积要求，HMC 入库重量公差应控制在",
    ),
    (
        "in order to prevent a fire from occurring in the event of a collision, the connectors shall be located at the rear of the vehicle installation standard",
        "为防止碰撞时发生起火，接插件应布置在整车安装基准的后方",
    ),
    (
        "the high voltage current carrying part connector or the cover for fastening shall have an interlock design for safety",
        "高压载流部件接插件或紧固盖板应具备高压互锁（HVIL）安全设计",
    ),
    (
        "3d data and 2d drawing shall be submitted by catia or creo, and 2d drawings shall be prepared based on asme y14.5",
        "3D 数模与 2D 图纸应采用 CATIA 或 CREO 提交，2D 图纸应基于 ASME Y14.5 标准绘制",
    ),
    (
        "anti cross thread design should be applied to the design of the energized fastening part, and all fastening parts should not have stripping",
        "带电紧固部位应采用防错牙（Anti-cross thread）设计，所有紧固部位不得滑牙",
    ),
    (
        "if exposed to the outside, it is necessary to apply adc - hc3 high-corrosion-resistant aluminum alloy or the same level of alloy, and to prevent corrosion penetration between parts",
        "若暴露于外部，须采用 ADC-HC3 高耐蚀铝合金或同等级合金，并防止零件间腐蚀渗透",
    ),
    (
        "if exposed to the outside, it is necessary to apply adc-hc3 high-corrosion-resistant aluminum alloy or the same level of alloy, and to prevent corrosion penetration between parts",
        "若暴露于外部，须采用 ADC-HC3 高耐蚀铝合金或同等级合金，并防止零件间腐蚀渗透",
    ),
    (
        "appearance quality shall be controlled, and the management plan shall be determined in consultation with the hmc person in charge",
        "外观质量应受控，管理方案与 HMC 负责人协商确定",
    ),
    (
        "inside the product: a corrosion-resistant material for the interior shall be applied",
        "产品内部：应采用内部耐腐蚀材料",
    ),
    (
        "exterior of product: corrosion-resistant material for exterior shall be applied",
        "产品外部：应采用外部耐腐蚀材料",
    ),
    (
        "the material should be selected in consideration of galvanic corrosion and electrolysis",
        "材料选型应考虑电偶腐蚀与电解腐蚀",
    ),
    (
        "surface treatment of the exterior part of the part shall satisfy hmc design criteria",
        "零件外部表面处理应满足 HMC 设计标准",
    ),
    (
        "the flame retardancy rating shall satisfy v0",
        "阻燃等级应满足 UL94 V-0",
    ),
    (
        "the rti and cti of the material should take into account the durable life of the vehicle",
        "材料的相对温度指数（RTI）和相比漏电起痕指数（CTI）应考虑整车耐久寿命",
    ),
    (
        "insert bushing nut studs shall be corrosion-resistant depending on the mounting position, and galvanic corrosion shall be considered",
        "嵌件衬套、螺母、螺柱应根据安装位置具备耐腐蚀性，并考虑电偶腐蚀",
    ),
    (
        "surface treatment shall satisfy the corrosion resistance requirements of internal and external parts of hmc",
        "表面处理应满足 HMC 内外部零件耐腐蚀要求",
    ),
    # 电气、控制、EMC 与试验
    (
        "can must operate within the specified voltage range",
        "CAN 通信必须在规定的电压范围内正常工作",
    ),
    (
        "in the case of direct motor cooling (oil cooling), supplier shall review whether there is a problem in advance",
        "对于电机直接冷却（油冷）方案，供应商应预先核查 HMC 规范并评估是否存在问题",
    ),
    (
        "ldc must be protected without failure at no coolant, non-cooling and low temperature(<0℃) condition. (temperature margin is necessary)",
        "在无冷却液、不冷却及低温（<0℃）工况下，LDC 必须实施保护且不发生故障（需留有温度裕量）",
    ),
    (
        "shall not cause issues to emc regulations and radio reception performance (am, fm, dab, dmb etc..)",
        "不得对 EMC 法规及无线电接收性能（AM、FM、DAB、DMB 等）造成干扰问题",
    ),
    (
        "even if esas emc requirements are met, be responsible for improving the emc performance on vehicle level",
        "即使满足零部件（ESA）EMC 要求，仍有责任配合提升整车级 EMC 性能",
    ),
    (
        "test modes should be defined considering hvdc and output power min/max conditions",
        "测试模式定义应考虑高压直流（HVDC）及输出功率的最小/最大工况",
    ),
    (
        "emc development capability checklist must be submitted along with the development proposal",
        "必须随开发技术方案一并提交《EMC 开发能力检查表》",
    ),
    (
        "submit emc design & simulation check list documentation during the design review phase",
        "在设计评审（DR）阶段提交《EMC 设计与仿真检查表》文档",
    ),
    (
        "emc esir should be proceeded after emc test plan submission and conformation",
        "应在提交 EMC 测试计划并经确认后开展 EMC ESIR 测试",
    ),
    (
        "dv and pv emc tests should be conducted in a chamber recognized by hmg. (debugging tests and pre - dv tests are not required.)",
        "DV 和 PV 阶段的 EMC 测试应在 HMG 认可的暗室中进行（摸底调试与 Pre-DV 测试不作强制要求）",
    ),
    (
        "reliability requirements and verification methods can be discussed with hmc",
        "可靠性要求及验证方法可与 HMC 协商确认",
    ),
    (
        "reliability and durability should be reflected in the design (parts and manufacturing process, etc",
        "可靠性与耐久性应落实在设计中（含零件选型与制造工艺等）",
    ),
    (
        "the supplier needs to submit the basis for calculating the durability life in order to satisfy the durability level requested by hmc",
        "供应商需提交耐久寿命计算依据，以证明满足 HMC 要求的耐久水平",
    ),
    (
        "the es reliability test shall be conducted using at least three samples per test",
        "ES 可靠性试验每项测试应至少使用 3 件样件",
    ),
    (
        "measurements such as voltage, current, efficiency, power factor, and thd must be measured using a power meter",
        "电压、电流、效率、功率因数及总谐波失真（THD）等参数必须使用功率分析仪测量",
    ),
    (
        "the above equipment and measurement requirements apply to all tests",
        "上述设备与测量要求适用于所有测试（ES 测试、EOL、测试用例、原理测试等）",
    ),
    (
        "if the attached functional safety management (fsmr) is different from the standard, fsmr must be followed first",
        "若所附功能安全管理要求（FSMR）与标准存在差异，必须优先遵循 FSMR",
    ),
    (
        "review the attached dia (development interface agreement) and submit summary of the parts that need to be discussed",
        "审阅所附开发接口协议（DIA），并提交需协商事项的汇总说明",
    ),
    (
        "north american specifications must be satisfied",
        "必须满足北美规格要求",
    ),
    (
        "the supplier shall submit the design approval schedule and part verification approval plan for each release stage",
        "供应商应提交各发布阶段的设计批准日程与零件验证批准计划",
    ),
    (
        "the vendor is responsible for penalties for delays in vehicle schedules due to unapproval and non-submission",
        "因未获批准或未按期提交导致整车日程延误的处罚责任由供应商承担",
    ),
    (
        "all items of es/ms, and other standards below are our standards to be satisfied when developing ldc products",
        "以下所有 ES/MS 条目及其他标准均为开发 LDC 产品时必须满足的我司标准",
    ),
    (
        "if the performance goals of es/ms differ from those of this sr, the content of the sr takes precedence",
        "若 ES/MS 的性能目标与本 SR 不一致，以本 SR 内容优先为准",
    ),
    (
        "when submitting parts, the counterpart connector must be included",
        "提交样件时必须附带对插端接插件（Counterpart Connector）",
    ),
    (
        "control circuit current should be below 0.3a (during driving, @12v)",
        "控制电路工作电流应低于 0.3A（行驶工况，@12V）",
    ),
    (
        "need input fuse for safety",
        "为安全起见需配置输入保险丝",
    ),
    (
        "do not use current mlcc capacitors on hv output terminals",
        "高压输出端子上不得使用常规 MLCC 电容",
    ),
    (
        "if digital control method is used, primary ct and secondary shunt resistance should be added",
        "若采用数字控制方式，应增加原边电流互感器（CT）与副边分流电阻（Shunt）",
    ),
    (
        "at least two temperature sensors for measuring the temperature of the semiconductor devices should be included",
        "应至少包含 2 个用于测量功率半导体器件温度的温度传感器",
    ),
    (
        "circuit protection coating required",
        "电路板需涂覆三防保护漆（Conformal Coating）",
    ),
    (
        "meet pcb design review sheet (hkmc provided)",
        "满足 PCB 设计评审表要求（HKMC 提供）",
    ),
    (
        "pcb flatness must meet hmc standards (after assembly/before assembly)",
        "PCB 平整度必须满足 HMC 标准（装配前/装配后）",
    ),
)

# 表格栏目与高频工程词组（词组级替换，长词组在前）
_TERM_MAP: tuple[tuple[str, str], ...] = (
    # 章节与表格常见表头/键名
    ("Major Classification", "大类"),
    ("Sub Classification", "小类"),
    ("Classification", "分类"),
    ("Request Specifications", "要求规格"),
    ("Request Specification", "要求规格"),
    ("Verification results", "验证结果"),
    ("Settings for evaluation", "评估测试设置"),
    ("Related parts", "相关零件"),
    ("Related SPEC", "相关规范"),
    ("Role sharing", "职责分工"),
    ("Work Porducts", "工作产物"),
    ("Work Products", "工作产物"),
    ("Vehicle Schedule", "整车日程"),
    ("Vehicle schedule", "整车日程"),
    ("Development schedule", "开发日程"),
    ("Development plan", "开发计划"),
    ("Required quantity", "需求数量"),
    ("Supplied parts", "提交零件"),
    ("Warranty period", "质保期"),
    ("Document name", "文件名称"),
    ("NOTE Standard", "参考标准"),
    ("Sample Size", "样件数量"),
    ("Per lot", "每批次"),
    ("# of lots", "批次数"),
    ("Test items", "测试项目"),
    ("Detailed test items", "详细测试项目"),
    ("Lead company", "主导方"),
    ("Lead organization", "主导部门"),
    ("Major verification parts", "主要验证部件"),
    ("Acceptance Criteria", "验收准则"),
    ("Detailed Acceptance Criteria", "详细验收准则"),
    ("Test conditions", "测试条件"),
    ("Test equipment", "测试设备"),
    ("Test methods and criteria", "测试方法与判定准则"),
    ("Operation point", "工作点"),
    ("Approved Drawing", "承认图"),
    ("Approved drawing", "承认图"),
    ("Product drawing", "产品图"),
    # 环境与物理量
    ("Temperature (oper)", "工作温度"),
    ("Temperature (Stor)", "存储温度"),
    ("Operating environment", "工作环境"),
    ("Operating Environment", "工作环境"),
    ("Waterproof dustproof", "防水防尘"),
    ("IP grade", "防护等级(IP)"),
    ("Vibration /Mech.shock", "振动/机械冲击"),
    ("Vibration / Mech.shock", "振动/机械冲击"),
    ("Mechanical shock", "机械冲击"),
    ("Insulation distance", "绝缘距离"),
    ("Insulation Durability reference", "绝缘耐久参考标准"),
    ("Reinforced Insulation", "加强绝缘"),
    ("Basic Insulation", "基本绝缘"),
    ("Creepage", "爬电距离"),
    ("Clearance", "电气间隙"),
    ("CLEARANCE & CREEPAGE", "电气间隙与爬电距离"),
    ("pollution degree", "污染等级"),
    ("Auxiliary battery", "蓄电池(低压辅助电池)"),
    ("Cooling water temp.", "冷却水温"),
    ("Dark Current", "暗电流(静态电流)"),
    ("Dark current", "暗电流(静态电流)"),
    ("Natural discharge", "自然放电(被动放电)"),
    ("Active discharge", "主动放电"),
    ("Charging standard", "充电标准"),
    # 性能与控制
    ("Output voltage control", "输出电压控制"),
    ("Output voltage command generator", "输出电压指令生成"),
    ("Output voltage command range", "输出电压指令范围"),
    ("Rate limit of output voltage command", "输出电压指令变化率限制"),
    ("Initial startup Performance", "初始启动性能"),
    ("Output voltage control accuracy", "输出电压控制精度"),
    ("Output voltage ripple", "输出电压纹波"),
    ("Line regulation", "线性调整率(输入电压调整率)"),
    ("Load regulation", "负载调整率"),
    ("Output voltage command initialization", "输出电压指令初始化"),
    ("LDC non-operating output voltage command", "LDC 非工作状态输出电压指令"),
    ("Output current limit control", "输出限流控制"),
    ("Output current limit command generator", "输出限流指令生成"),
    ("Output current limit command (operation) range", "输出限流指令(工作)范围"),
    ("Output current limit control accuracy", "输出限流控制精度"),
    ("Current ripple at output current limit", "输出限流状态下的电流纹波"),
    ("Current-limited response performance", "限流响应性能"),
    ("Current overshoot", "电流超调量"),
    ("Control power source", "控制电源"),
    ("Protection/Diagnostic Functions", "保护与诊断功能"),
    ("Output Short Circuit", "输出短路"),
    ("Reverse Connection", "反接保护"),
    ("Over-voltage", "过压"),
    ("low-voltage", "欠压"),
    ("over-current", "过流"),
    ("low-current", "欠流"),
    ("undervoltage", "欠压"),
    ("overvoltage", "过压"),
    ("over-temperature", "过温"),
    ("over-current", "过流"),
    ("Switching frequency", "开关频率"),
    ("Task configuration", "任务配置"),
    ("MCU core load rate analysis", "MCU 核负载率分析"),
    ("MCU c ore load rate analysis", "MCU 核负载率分析"),
    ("Power circuit topology and detailed schematic", "功率电路拓扑与详细原理图"),
    ("Voltage / Current sensor location and specifications", "电压/电流传感器位置与规格"),
    ("Voltage / Current sensing circuit schematic", "电压/电流采样电路原理图"),
    ("Hardware and Software filter bandwidth for voltage / current sensing", "电压/电流采样软硬件滤波带宽"),
    ("AD Conversion timing Diagram with PWM signal (Including sampling Point)", "AD 转换与 PWM 信号时序图（含采样点）"),
    ("Application and methodology of sensing calibration", "采样标定应用与方法"),
    ("Voltage / Current analog control circuit schematic and bandwidth", "电压/电流模拟控制电路原理图与带宽"),
    ("Specialized control features and functional descriptions", "专用控制特性与功能说明"),
    ("Closed-loop feedback configuration and compensation design", "闭环反馈配置与补偿设计"),
    ("Voltage / Current control block diagram and bandwidth , Control algorithm flow", "电压/电流控制框图、带宽及控制算法流程"),
    ("Control block diagram for LDC limit signals from External Controllers", "外部控制器（如 VCMS）LDC 限制信号控制框图"),
    # EMC / 可靠性试验
    ("CE (Conducted Emission)", "CE（传导发射）"),
    ("RE (Radiated Emission)", "RE（辐射发射）"),
    ("TI (Transient Immunity)", "TI（瞬态抗扰度）"),
    ("TE (Transient Emission)", "TE（瞬态发射）"),
    ("RI (Radiated Immunity)", "RI（辐射抗扰度）"),
    ("BCI (Bulk Current Injection)", "BCI（大电流注入）"),
    ("Portable Transmitter", "便携式发射机抗扰度"),
    ("ESD (Electrostatic Discharge)", "ESD（静电放电）"),
    ("MI (Magnetic Field Immunity)", "MI（磁场抗扰度）"),
    ("ME (Magnetic Field Emission)", "ME（磁场发射）"),
    ("Coupling Attenuation", "耦合衰减"),
    ("Voltage Ripple on HV", "高压端电压纹波"),
    ("Surge/Burst", "浪涌/脉冲群(Surge/Burst)"),
    ("High temperature reverse bias(HTRB)", "高温反偏试验(HTRB)"),
    ("High temperature gate bias(HTGB)", "高温栅偏试验(HTGB)"),
    ("Temperature cycling(TC)", "温度循环试验(TC)"),
    ("Temperature cycling", "温度循环试验"),
    ("High temperature exposure", "高温存储/暴露试验"),
    ("Deflection humidity", "偏压温湿度试验"),
    ("Discrete semiconductor", "分立半导体器件"),
    ("Magnetic material", "磁性元器件"),
    # 研发职责与交付物
    ("SYSTEM Design", "系统设计"),
    ("Hardware Design", "硬件设计"),
    ("Software Development", "软件开发"),
    ("Part manufacturing", "零件制造"),
    ("Parts inspection and Quality assurance", "零件检验与质量保证"),
    ("Single component test", "单品测试"),
    ("Vehicle and system testing", "整车与系统测试"),
    ("Functional safety management Requirement", "功能安全管理要求"),
    ("Development interface agreement", "开发接口协议(DIA)"),
    ("Functional safety concept", "功能安全概念(FSC)"),
    ("Important safety requirements", "重要安全要求"),
    ("Approval/ Submission", "批准/提交"),
    ("Approval / Submission", "批准/提交"),
    ("Cooperation Submission", "协同提交"),
    ("Qualification Life", "认证寿命(设计寿命)"),
    ("Warran ty", "质保期"),
    ("Warranty", "质保期"),
    ("Corrosion resistance", "耐腐蚀性"),
    ("Quality responsibility", "质量责任"),
    ("Quality Liability", "质量责任"),
    ("Common Patent", "共有专利"),
    ("Evaluation facility", "评估试验设施"),
    ("New Technology", "新技术应用"),
    ("Marketability", "市场商品性"),
    ("AS convenience", "售后维修便利性"),
    ("CASTING PARTS", "压铸件"),
    ("HOUSING, COVER, PLATE, BRACKET, ETC.", "壳体、盖板、板件、支架等"),
    ("ELECTRICAL PARTS", "导电/电气部件"),
    ("BUSBAR BRACKETS, CONNECTORS, ETC.", "母排支架、接插件等"),
    ("BOLT, NUT, SCREW, STUD, ETC", "螺栓、螺母、螺钉、螺柱等"),
    ("THERMAL INTERFACE", "热界面设计"),
    ("WELDING INTERFACE", "焊接界面设计"),
    ("SEALING INTERFACE", "密封界面设计"),
    ("CLIPPING INTERFACE", "卡扣连接界面设计"),
    ("PRESS FIT INTERFACE", "压接界面设计"),
    ("FASTENING INTERFACE", "紧固连接界面设计"),
    ("MULTY LAYER ASSEMBLY", "多层装配公差分析"),
    ("COATING, CHEMICALS", "涂覆与化学品验证"),
    ("HEAT TREAT", "热处理件验证"),
)

# 单词级补充词典（用于短句和剩余词翻译）
_WORD_MAP: dict[str, str] = {
    "overview": "概述",
    "system": "系统",
    "requirements": "要求",
    "requirement": "要求",
    "specification": "规格",
    "specifications": "规格",
    "spec": "规格",
    "spec.": "规格",
    "contents": "内容",
    "content": "内容",
    "details": "详细内容",
    "items": "项目",
    "item": "项目",
    "category": "类别",
    "unit": "单位",
    "notes": "备注",
    "note": "注",
    "value": "数值",
    "values": "数值",
    "name": "名称",
    "department": "部门",
    "rate": "速率",
    "revision": "修订",
    "date": "日期",
    "author": "作者",
    "condition": "条件",
    "conditions": "条件",
    "water": "水",
    "temperature": "温度",
    "team": "团队",
    "generating": "发电",
    "generation": "发电",
    "remark": "备注",
    "remarks": "备注",
    "status": "状态",
    "target": "目标",
    "targets": "目标",
    "performance": "性能",
    "quality": "质量",
    "reliability": "可靠性",
    "durability": "耐久性",
    "environment": "环境",
    "humidity": "湿度",
    "altitude": "海拔",
    "vibration": "振动",
    "insulation": "绝缘",
    "cooling": "冷却",
    "voltage": "电压",
    "current": "电流",
    "output": "输出",
    "input": "输入",
    "efficiency": "效率",
    "power": "功率",
    "torque": "扭矩",
    "tq": "扭矩",
    "dyno": "测功机",
    "engine": "发动机",
    "parallel": "并联",
    "step": "步进",
    "speed": "转速",
    "noise": "噪声",
    "respectively": "分别",
    "weight": "重量",
    "volume": "体积",
    "size": "尺寸",
    "length": "长度",
    "width": "宽度",
    "height": "高度",
    "package": "布置/封装",
    "interface": "接口",
    "connector": "接插件",
    "connectors": "接插件",
    "material": "材料",
    "materials": "材料",
    "heavy": "重",
    "metal": "金属",
    "general": "通用",
    "hardware": "硬件",
    "software": "软件",
    "control": "控制",
    "functional": "功能",
    "safety": "安全",
    "regulations": "法规",
    "regulation": "法规",
    "certification": "认证",
    "patent": "专利",
    "recycle": "回收利用",
    "development": "开发",
    "plan": "计划",
    "schedule": "日程",
    "submission": "提交",
    "submit": "提交",
    "approval": "批准",
    "approved": "承认/批准",
    "drawing": "图纸",
    "drawings": "图纸",
    "report": "报告",
    "reports": "报告",
    "analysis": "分析",
    "simulation": "仿真",
    "verification": "验证",
    "validation": "确认/验证",
    "evaluation": "评估",
    "test": "测试",
    "tests": "测试",
    "testing": "测试",
    "supplier": "供应商",
    "suppliers": "供应商",
    "vehicle": "整车",
    "vehicles": "整车",
    "part": "零件",
    "parts": "零件",
    "component": "部件",
    "components": "部件",
    "assembly": "总成/装配",
    "design": "设计",
    "manufacturing": "制造",
    "production": "量产",
    "mass": "批量",
    "sample": "样件",
    "samples": "样件",
    "cost": "成本",
    "mold": "模具",
    "check": "检查/核对",
    "review": "评审/核查",
    "satisfy": "满足",
    "satisfied": "满足",
    "meet": "满足",
    "met": "满足",
    "must": "必须",
    "shall": "应",
    "should": "应",
    "within": "在…以内",
    "above": "以上",
    "below": "以下",
    "more": "以上",
    "less": "以下",
    "all": "所有",
    "each": "各",
    "between": "之间",
    "high": "高",
    "low": "低",
    "housing": "壳体",
    "signal": "信号",
    "nominal": "标称",
    "overall": "全范围",
    "range": "范围",
    "operation": "工作/运行",
    "operating": "工作/运行",
    "time": "时间",
    "hours": "小时",
    "times": "次",
    "years": "年",
    "all regions": "所有区域",
    "regions": "区域",
    "region": "区域",
    "including": "含",
    "charging": "充电",
    "driving": "行驶",
    "mechanical": "机械",
    "electrical": "电气",
    "electronic": "电子",
    "electronics": "电子件",
    "thermal": "热/温度",
    "sealing": "密封",
    "fastening": "紧固",
    "welding": "焊接",
    "leakage": "泄漏",
    "common": "通用",
    "modal": "模态",
    "shock": "冲击",
    "capacitor": "电容",
    "inductor": "电感",
    "transformer": "变压器",
    "resistor": "电阻",
    "sensor": "传感器",
    "sensors": "传感器",
    "relay": "继电器",
    "motor": "电机",
    "inverter": "逆变器",
    "gearbox": "减速器",
    "converter": "变换器",
    "battery": "电池",
    "confirm": "确认",
    "confirmed": "确认",
    "every": "每项",
    "of": "的",
    "max": "最大",
    "mode": "模式",
    "change": "变更",
    "changes": "变更",
    "this": "本",
    "document": "文件",
    "summarizes": "汇总",
    "information": "信息",
    "specification": "规格",
    "specifications": "规格",
    "managed": "管理",
    "applies": "适用",
    "apply": "适用",
    "ambient": "环境",
    "load": "负载",
    "criteria": "准则",
    "submitted": "提交",
    "during": "在…期间",
    "included": "含",
    "sub-parts": "子零件",
    "last": "耐久达",
    "the": "",
}

# 韩文车规电驱工程词典（长词优先匹配；支持原串与收紧拆字空格后双重匹配）
_HANGUL_MAP: tuple[tuple[str, str], ...] = (
    # 完整句式与长短语
    ("통합형 PE(모터/감속기/인버터) 승인도 EMC 해석 및 검증 항목", "集成式电驱 PE（电机/减速器/逆变器）承认图 EMC 仿真分析与验证项目"),
    ("모든 자료 제출 & 협력사 방문 리뷰시 모든 자료 열람", "提交全部资料且供应商现场评审时查阅全部资料"),
    ("요약 자료 제출 & 협력사 방문 리뷰시 모든 자료 열람", "提交摘要资料且供应商现场评审时查阅全部资料"),
    ("협력사 방문 리뷰시 모든 자료 열람", "供应商现场评审时查阅全部资料"),
    ("모든 자료 제출", "提交全部资料"),
    ("요약 자료 제출", "提交摘要资料"),
    ("고전압 - 저전압간 최소 이격거리", "高低压间最小间距"),
    ("고전압 커넥터 차폐부 - 하우징간 접촉저항 점검", "高压连接器屏蔽部与壳体间接触电阻检查"),
    ("저전압단 차폐부 유무 점검", "低压端屏蔽部有无检查"),
    ("소자 모델링", "器件建模"),
    ("소자모델링", "器件建模"),
    ("등가 회로 모델", "等效电路模型"),
    ("등가회로모델", "等效电路模型"),
    ("임피던스 측정결과", "阻抗测量结果"),
    ("임피던스측정결과", "阻抗测量结果"),
    ("최소 이격거리", "最小间距"),
    ("최소이격거리", "最小间距"),
    ("이격거리", "间距"),
    ("접촉저항", "接触电阻"),
    ("차폐부", "屏蔽部"),
    ("저전압단", "低压端"),
    ("고전압단", "高压端"),
    ("고전압", "高压"),
    ("저전압", "低压"),
    ("유무 확인", "有无确认"),
    ("유무확인", "有无确认"),
    ("유무 점검", "有无检查"),
    ("유무점검", "有无检查"),
    ("정보 확인", "信息确认"),
    ("정보확인", "信息确认"),
    ("점검", "检查"),
    ("기구", "结构"),
    ("구성", "构成"),
    ("소자", "器件"),
    ("모델링", "建模"),
    ("등가", "等效"),
    ("모델", "模型"),
    ("임피던스", "阻抗"),
    ("측정결과", "测量结果"),
    ("측정", "测量"),
    ("자료", "资料"),
    ("협력사", "供应商"),
    ("방문", "现场"),
    ("리뷰시", "评审时"),
    ("리뷰", "评审"),
    ("열람", "查阅"),
    ("요약", "摘要"),
    ("모든", "全部"),
    ("유무", "有无"),
    ("정보", "信息"),
    ("모터/감속기/인버터", "电机/减速器/逆变器"),
    ("인가가능최대전압", "可施加最大电压"),
    ("인가 가능 최대 전압", "可施加最大电压"),
    ("최대입력전압", "最大输入电压"),
    ("최소입력전압", "最小输入电压"),
    ("정격입력전압", "额定输入电压"),
    ("작동전압범위", "工作电压范围"),
    ("작동 전압 범위", "工作电压范围"),
    ("보관온도범위", "存储温度范围"),
    ("작동온도범위", "工作温度范围"),
    ("냉각수온도", "冷却液温度"),
    ("냉각수유량", "冷却液流量"),
    ("냉각수압력", "冷却液压力"),
    ("오일온도", "油温"),
    ("유량조건", "流量条件"),
    ("부하조건", "负载条件"),
    ("시험시간", "试验时间"),
    ("시험조건", "试验条件"),
    ("시험방법", "试验方法"),
    ("시험항목", "试验项目"),
    ("점검항목", "检查项目"),
    ("검증항목", "验证项目"),
    ("요구사항", "要求事项"),
    ("요구사양", "要求规格"),
    ("성능요구사항", "性能要求"),
    ("설계요구사항", "设计要求"),
    ("일반요구사항", "通用要求"),
    ("기능안전", "功能安全"),
    ("사이버보안", "网络安全"),
    ("전자파적합성", "电磁兼容"),
    ("절연저항", "绝缘电阻"),
    ("내전압", "耐压"),
    ("암전류", "暗电流"),
    ("정현반파", "半正弦波"),
    ("랜덤진동", "随机振动"),
    ("정현파진동", "正弦振动"),
    ("기계적충격", "机械冲击"),
    ("열충격", "热冲击"),
    ("고온방치", "高温存储"),
    ("저온방치", "低温存储"),
    ("고온작동", "高温工作"),
    ("저온작동", "低温工作"),
    ("온습도사이클", "温湿度循环"),
    ("염수분무", "盐雾"),
    ("방수방진", "防尘防水"),
    ("최고속도", "最高转速"),
    ("최고출력", "最大功率"),
    ("최대출력", "最大功率"),
    ("정격출력", "额定功率"),
    ("최대토크", "最大扭矩"),
    ("정격토크", "额定扭矩"),
    ("지속출력", "持续功率"),
    ("지속토크", "持续扭矩"),
    ("전류센서", "电流传感器"),
    ("온도센서", "温度传感器"),
    ("위치센서", "位置传感器"),
    ("레졸버", "旋变"),
    ("게이트드라이버", "门极驱动"),
    ("파워모듈", "功率模块"),
    ("평활커패시터", "母线支撑电容"),
    ("제어보드", "控制板"),
    ("파워보드", "功率板"),
    ("하우징", "壳体"),
    ("커넥터", "连接器"),
    ("버스바", "母排"),
    ("실드캔", "屏蔽罩"),
    ("페라이트코어", "铁氧体磁芯"),
    ("전구설3팀", "电驱设计3队"),
    ("전구설", "电驱设计"),
    ("컨버터설계팀", "变换器设计队"),
    ("인버터설계팀", "逆变器设计队"),
    ("모터설계팀", "电机设计队"),
    ("감속기설계팀", "减速器设计队"),
    ("샤시제어개발팀", "底盘控制开发队"),
    ("구동모터", "驱动电机"),
    ("고전압배터리", "高压电池"),
    ("저전압배터리", "低压电池"),
    # 常用双字/单字工程词汇
    ("통합형", "集成式"),
    ("분리형", "分体式"),
    ("승인도", "承认图"),
    ("해석", "仿真分析"),
    ("검증", "验证"),
    ("항목", "项目"),
    ("구분", "分类"),
    ("분류", "分类"),
    ("내역", "明细"),
    ("내용", "内容"),
    ("기준", "基准"),
    ("규격", "规格"),
    ("사양", "规格"),
    ("조건", "条件"),
    ("방법", "方法"),
    ("결과", "结果"),
    ("판정", "判定"),
    ("비고", "备注"),
    ("단위", "单位"),
    ("수량", "数量"),
    ("모터", "电机"),
    ("감속기", "减速器"),
    ("인버터", "逆变器"),
    ("컨버터", "变换器"),
    ("변환기", "变换器"),
    ("배터리", "电池"),
    ("제어기", "控制器"),
    ("센서", "传感器"),
    ("릴레이", "继电器"),
    ("퓨즈", "保险丝"),
    ("저항", "电阻"),
    ("용량", "容量"),
    ("커패시터", "电容"),
    ("인덕터", "电感"),
    ("코일", "线圈"),
    ("필터", "滤波器"),
    ("회로", "电路"),
    ("기판", "基板"),
    ("단자", "端子"),
    ("접지", "接地"),
    ("차폐", "屏蔽"),
    ("절연", "绝缘"),
    ("방열", "散热"),
    ("냉각수", "冷却液"),
    ("냉각", "冷却"),
    ("오일", "油"),
    ("온도", "温度"),
    ("습도", "湿度"),
    ("압력", "压力"),
    ("유량", "流量"),
    ("속도", "转速/速度"),
    ("회전수", "转速"),
    ("토크", "扭矩"),
    ("출력", "输出功率"),
    ("입력", "输入"),
    ("전압", "电压"),
    ("전류", "电流"),
    ("전력", "功率"),
    ("효율", "效率"),
    ("주파수", "频率"),
    ("시간", "时间"),
    ("주기", "周期"),
    ("횟수", "次数"),
    ("진동", "振动"),
    ("충격", "冲击"),
    ("소음", "噪声"),
    ("내구", "耐久"),
    ("수명", "寿命"),
    ("중량", "重量"),
    ("크기", "尺寸"),
    ("치수", "尺寸"),
    ("공차", "公差"),
    ("재질", "材质"),
    ("표면처리", "表面处理"),
    ("도금", "电镀"),
    ("도장", "涂装"),
    ("방수", "防水"),
    ("방진", "防尘"),
    ("기밀", "气密"),
    ("누설", "泄漏"),
    ("고장", "故障"),
    ("진단", "诊断"),
    ("보호", "保护"),
    ("경고", "告警"),
    ("통신", "通信"),
    ("신호", "信号"),
    ("제어", "控制"),
    ("작동", "工作"),
    ("동작", "动作"),
    ("정지", "停止"),
    ("대기", "待机"),
    ("충전", "充电"),
    ("방전", "放电"),
    ("최대", "最大"),
    ("최소", "最小"),
    ("정격", "额定"),
    ("평균", "平均"),
    ("연속", "连续"),
    ("순간", "瞬态"),
    ("이상", "以上"),
    ("이하", "以下"),
    ("초과", "超过"),
    ("미만", "小于"),
    ("이내", "以内"),
    ("동등", "同等"),
    ("만족", "满足"),
    ("적용", "适用"),
    ("확인", "确认"),
    ("제출", "提交"),
    ("협의", "协商"),
    ("추후", "后续"),
    ("미정", "待定"),
    ("해당없음", "不适用"),
    ("없음", "无"),
    ("있음", "有"),
    ("공진점", "共振点"),
    ("가속도", "加速度"),
    ("방향", "方向"),
    ("축", "轴"),
    ("상하", "上下"),
    ("좌우", "左右"),
    ("전후", "前后"),
    ("양산", "量产"),
    ("개발", "开发"),
    ("설계", "设计"),
    ("해석", "仿真"),
    ("시험", "试验"),
    ("평가", "评估"),
    ("및", "及"),
)

# 日文、德文、法文、俄文常见车规电驱工程词典（处理其他非英语种材料）
_OTHER_LANG_MAP: tuple[tuple[str, str], ...] = (
    # 日文（含假名与日文专有词）
    ("要求仕様", "要求规格"),
    ("試験条件", "试验条件"),
    ("試験方法", "试验方法"),
    ("試験時間", "试验时间"),
    ("動作電圧範囲", "工作电压范围"),
    ("動作温度範囲", "工作温度范围"),
    ("保存温度範囲", "存储温度范围"),
    ("最大出力", "最大输出功率"),
    ("定格出力", "额定输出功率"),
    ("最大トルク", "最大扭矩"),
    ("定格トルク", "额定扭矩"),
    ("最高回転数", "最高转速"),
    ("絶縁抵抗", "绝缘电阻"),
    ("耐電圧", "耐压"),
    ("暗電流", "暗电流"),
    ("冷却水温度", "冷却液温度"),
    ("冷却水流量", "冷却液流量"),
    ("インバータ", "逆变器"),
    ("コンバータ", "变换器"),
    ("モータ", "电机"),
    ("モーター", "电机"),
    ("ギヤボックス", "减速器"),
    ("減速機", "减速器"),
    ("バッテリー", "电池"),
    ("コネクタ", "连接器"),
    ("ハウジング", "壳体"),
    ("センサ", "传感器"),
    ("センサー", "传感器"),
    ("リレー", "继电器"),
    ("ヒューズ", "保险丝"),
    ("コンデンサ", "电容"),
    ("コイル", "线圈"),
    ("基板", "基板"),
    ("電圧", "电压"),
    ("電流", "电流"),
    ("電力", "功率"),
    ("効率", "效率"),
    ("回転数", "转速"),
    ("トルク", "扭矩"),
    ("周波数", "频率"),
    ("温度", "温度"),
    ("湿度", "湿度"),
    ("圧力", "压力"),
    ("流量", "流量"),
    ("振動", "振动"),
    ("衝撃", "冲击"),
    ("騒音", "噪声"),
    ("耐久", "耐久"),
    ("寿命", "寿命"),
    ("備考", "备注"),
    ("単位", "单位"),
    ("項目", "项目"),
    ("区分", "分类"),
    ("基準", "基准"),
    ("条件", "条件"),
    ("以上", "以上"),
    ("以下", "以下"),
    ("未満", "小于"),
    ("以内", "以内"),
    ("とする", ""),
    ("こと", ""),
    ("および", "及"),
    ("または", "或"),
    # 德文（OEM 规格书如 VW/BMW/Mercedes/Audi 常见词）
    ("betriebsspannungsbereich", "工作电压范围"),
    ("betriebsspannung", "工作电压"),
    ("nennspannung", "额定电压"),
    ("prüfspannung", "测试电压"),
    ("isolationswiderstand", "绝缘电阻"),
    ("ruhestrom", "暗电流/静态电流"),
    ("betriebstemperaturbereich", "工作温度范围"),
    ("betriebstemperatur", "工作温度"),
    ("lagertemperatur", "存储温度"),
    ("kühlmitteltemperatur", "冷却液温度"),
    ("kühlmitteldurchfluss", "冷却液流量"),
    ("maximalleistung", "最大功率"),
    ("nennleistung", "额定功率"),
    ("dauerleistung", "持续功率"),
    ("maximaldrehmoment", "最大扭矩"),
    ("nenndrehmoment", "额定扭矩"),
    ("höchstdrehzahl", "最高转速"),
    ("nenndrehzahl", "额定转速"),
    ("wirkungsgrad", "效率"),
    ("wechselrichter", "逆变器"),
    ("gleichspannungswandler", "直流变换器"),
    ("elektromotor", "电机"),
    ("getriebe", "减速器"),
    ("steuergerät", "控制器"),
    ("gehäuse", "壳体"),
    ("stecker", "连接器"),
    ("anforderungen", "要求"),
    ("anforderung", "要求"),
    ("prüf조건", "试验条件"),
    ("prüfbedingung", "试验条件"),
    ("prüfbedingungen", "试验条件"),
    ("prüfdauer", "试验时间"),
    ("prüfung", "试验"),
    ("spannung", "电压"),
    ("strom", "电流"),
    ("leistung", "功率"),
    ("drehmoment", "扭矩"),
    ("drehzahl", "转速"),
    ("frequenz", "频率"),
    ("temperatur", "温度"),
    ("druck", "压力"),
    ("durchfluss", "流量"),
    ("schwingung", "振动"),
    ("stoß", "冲击"),
    ("lebensdauer", "寿命"),
    ("gewicht", "重量"),
    ("einheit", "单位"),
    ("bemerkung", "备注"),
    ("hinweis", "说明"),
    ("mindestens", "至少"),
    ("höchstens", "至多"),
    ("maximal", "最大"),
    ("minimal", "最小"),
    ("gemäß", "依据"),
    ("muss", "应"),
    ("soll", "应"),
    # 俄文常见词
    ("требования", "要求"),
    ("требование", "要求"),
    ("рабочее напряжение", "工作电压"),
    ("напряжение", "电压"),
    ("ток", "电流"),
    ("мощность", "功率"),
    ("крутящий момент", "扭矩"),
    ("частота вращения", "转速"),
    ("температура", "温度"),
    ("инвертор", "逆变器"),
    ("двигатель", "电机"),
    ("редуктор", "减速器"),
    ("примечание", "备注"),
    ("единица", "单位"),
)


_UNIT_TOKEN = re.compile(
    r"^(?:rpm|r/min|nm|lpm|kw|kpa|mpa|db|dba|dc|ac|hz|khz|mhz|bar|mm|cm|kg)$",
    re.I,
)


def _kept_token(word: str) -> bool:
    """缩写和单位不译。"""
    if _UNIT_TOKEN.match(word):
        return True
    if word.isupper() and word.lower() not in _WORD_MAP and 2 <= len(word) <= 6:
        return True
    return False


def _proper_names_only(words: list[str]) -> bool:
    """词典里没有、又都大写开头的，当作译不出的专名。"""
    if not words:
        return False
    if any(word.lower() in _WORD_MAP for word in words):
        return False
    return all(word[:1].isupper() for word in words)


def _needs_trans_body(body: str) -> bool:
    cjk_count = len(_CJK.findall(body))
    hangul_count = len(_HANGUL.findall(body))
    kana_count = len(_KANA.findall(body))
    if hangul_count >= 2 or kana_count >= 2:
        return True
    words = [word for word in _LATIN_WORD.findall(body) + _CYRILLIC_WORD.findall(body) if not _kept_token(word)]
    if not words or _proper_names_only(words):
        return False
    return cjk_count < len(words) * 2


def needs_translation(text: str) -> bool:
    """判断一段摘录是否需要补充中文翻译：含任何非中文外文（英/韩/日/德/法/俄等），且尚未带中文译文。"""
    raw = (text or "").strip()
    if not raw:
        return False
    # 整页数值表、图表、表格块，以及按行抄录的整表（译文已写在各格后面），不再整段重译
    if raw.startswith(("本页为数值表", "本页图表", "本页表格块", "本页表格", "本页图片表格", "本页线框表格")):
        return False
    # 已经按「列名：内容」拆成多行的表格行，保留换行，不再压成一段
    labeled = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(labeled) >= 2 and sum(1 for line in labeled if re.match(r"^[^：]{1,40}：", line)) >= 2:
        return False
    return _needs_trans_body(raw)


def _cell_bilingual(cell: str) -> str:
    """一格对照：原文保留。译出了中文就写成「原文 / 中文」，单位和没译出的词留在译文里。"""
    raw = cell.strip()
    if not raw:
        return raw
    for table in (_PHRASE_MAP, _TERM_MAP):
        for english, chinese in table:
            if re.fullmatch(re.escape(english), raw, re.I):
                return f"{raw} / {chinese}"
    if not _needs_trans_body(raw):
        return raw
    zh = _translate_segment(raw)
    if not zh or zh == raw or not _CJK.search(zh):
        return raw
    return f"{raw} / {zh}"


def _split_grid_row(line: str) -> list[str]:
    return [part.strip() for part in line.split("|")]


_RPM_HEADER = re.compile(
    r"(?:转速\s*/\s*rpm|rpm)\s+(?:\d+\s*V\s*){2,}(?:(?:转速\s*/\s*rpm|rpm)\s+(?:\d+\s*V\s*){2,})*",
    re.IGNORECASE,
)
_TORQUE_HEADER = re.compile(r"(?:Torque\s+Nm\s+Power\s+kW\s*){2,}", re.IGNORECASE)


def strip_column_headers(text: str) -> str:
    """去掉外特性表里单独成行的列表头。转速、电压档和反复出现的 Torque/Nm/Power/kW 不是数据。"""
    kept: list[str] = []
    for line in (text or "").splitlines():
        cleaned = _TORQUE_HEADER.sub("", line)
        cleaned = _RPM_HEADER.sub("", cleaned).strip(" \t/")
        if cleaned:
            kept.append(cleaned)
    return "\n".join(kept).strip()


def _is_column_header(rows: list[list[str]]) -> bool:
    """首行多数格子是短列名（Item、Korea、China）时，按列名抄，避免空列把后面的标准挤错位。"""
    if not rows:
        return False
    first = rows[0]
    filled = [cell for cell in first if cell]
    if len(filled) < 3 or len(filled) * 2 < len(first):
        return False
    for cell in filled:
        if len(cell) > 40 or len(cell.split()) > 6 or re.search(r"\d", cell):
            return False
    return True


def _zh_only(bilingual: str, original: str) -> str:
    mark = " / "
    if bilingual.startswith(original + mark):
        return bilingual[len(original) + len(mark) :]
    return ""


_ROW_LINE = "─" * 42


def _join_table_blocks(blocks: list[str]) -> str:
    return f"\n{_ROW_LINE}\n".join(blocks)


def _phrase(english: str, chinese: str) -> str:
    """一句原文接译文。短句同一行「原文 / 中文」；较长的英文换行后再写「/ 中文」。"""
    if not chinese or chinese == english:
        return english
    if len(english) <= 48:
        return f"{english} / {chinese}"
    return f"{english}\n/ {chinese}"


def _template_block(cells: list[str], headers: list[str]) -> str:
    """一行表格：每个有字的格写成「原文 / 中文」。空列不写。"""
    shown = [(col, (headers[col].strip() if col < len(headers) else ""), cell) for col, cell in enumerate(cells) if cell]
    if not shown:
        return ""
    lines: list[str] = []
    for col, label, text in shown:
        if col == 0 and not label:
            lines.append(_phrase(text, _zh_only(_cell_bilingual(text), text)))
            continue
        english = f"{label}: {text}" if label else text
        label_zh = _zh_only(_cell_bilingual(label), label) if label else ""
        value_zh = _zh_only(_cell_bilingual(text), text)
        # 「Due 日期」「材料 marking」这种半截译文不写。栏目译完整、取值仍是原文的，照写对照。
        partial_label = bool(label_zh and re.search(r"[A-Za-z]{3,}", label_zh))
        partial_value = bool(value_zh and value_zh != text and re.search(r"[A-Za-z]{3,}", value_zh))
        if partial_label:
            label_zh = ""
        if partial_value:
            chinese = ""
        elif label_zh or (value_zh and value_zh != text):
            chinese = f"{label_zh or label}：{value_zh or text}"
        else:
            chinese = ""
        lines.append(_phrase(english, chinese))
    return "\n".join(lines)


def table_excerpt_blocks(text: str) -> list[str]:
    """整表摘录按表行拆开。每一块是表里的一行，后面写进 Excel 时各占一行，边框就是横线。"""
    raw = (text or "").strip()
    if "：\n" not in raw:
        return [raw] if raw else []
    _, body = raw.split("：\n", 1)
    parsed = [_split_grid_row(line) for line in body.splitlines()]
    if not any(any(cell for cell in row) for row in parsed):
        return []
    if _is_column_header(parsed):
        headers = parsed[0]
        return [block for cells in parsed[1:] if (block := _template_block(cells, headers))]
    blocks: list[str] = []
    for row in parsed:
        if len(row) == 1:
            cleaned = strip_column_headers(row[0])
            if not cleaned:
                continue
            row = [cleaned]
        cells = [_phrase(cell, _zh_only(_cell_bilingual(cell), cell)) for cell in row if cell]
        if cells:
            blocks.append("\n".join(cells))
    return blocks


def present_table_excerpt(text: str) -> str:
    """认不出栏目的整表。每行里的非空格写成「原文 / 中文」，行与行之间加横线。"""
    raw = (text or "").strip()
    blocks = table_excerpt_blocks(raw)
    if not blocks:
        return raw
    head = raw.split("：\n", 1)[0] if "：\n" in raw else raw
    return f"{head}：\n" + _join_table_blocks(blocks)


def rule_translate_text(text: str) -> str:
    """无模型或模型兜底时，按车规电驱工程句式与多语种术语词典将非中文条款译为中文。"""
    raw = (text or "").strip()
    if not raw:
        return ""
    if raw.startswith(("本页表格", "本页图片表格")) and "：\n" in raw:
        return present_table_excerpt(raw)
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) >= 2:
        translated = [_translate_segment(line) for line in lines]
        if any(line != zh and _CJK.search(zh) for line, zh in zip(lines, translated)):
            return "\n".join(zh if zh else line for line, zh in zip(lines, translated))
    flat = " ".join(lines)
    # 表格行：「项目名：栏目：值 | 栏目：值」
    if " | " in flat:
        parts = [_translate_segment(part) for part in flat.split(" | ")]
        return " | ".join(parts)
    return _translate_segment(flat)


def _apply_hangul_map(text: str) -> str:
    out = text
    for kr, zh in sorted(_HANGUL_MAP, key=lambda x: len(x[0]), reverse=True):
        if kr in out:
            out = out.replace(kr, zh)
    if _HANGUL.search(out):
        tight = _HANGUL_GAP.sub("", out)
        if tight != out:
            out = tight
            for kr, zh in sorted(_HANGUL_MAP, key=lambda x: len(x[0]), reverse=True):
                if kr in out:
                    out = out.replace(kr, zh)
    return out


def _translate_segment(seg: str) -> str:
    out = seg.strip()
    if not out:
        return ""
    # 1. 先替换韩文词汇（含 PDF 拆字空格收紧后二次匹配）
    if _HANGUL.search(out):
        out = _apply_hangul_map(out)
    # 2. 替换日文、德文、俄文等其他语种工程词汇
    for foreign, zh in sorted(_OTHER_LANG_MAP, key=lambda x: len(x[0]), reverse=True):
        if _KANA.search(foreign) or _CJK.search(foreign):
            if foreign in out:
                out = out.replace(foreign, zh)
        else:
            pattern = re.compile(r"(?<![A-Za-z\u00c0-\u024f\u0400-\u04ff])" + re.escape(foreign) + r"(?![A-Za-z\u00c0-\u024f\u0400-\u04ff])", re.I)
            if pattern.search(out):
                out = pattern.sub(zh, out)
    # 3. 匹配英文长句/子句（不区分大小写）
    for en_phrase, zh_phrase in _PHRASE_MAP:
        pattern = re.compile(re.escape(en_phrase), re.I)
        if pattern.search(out):
            out = pattern.sub(zh_phrase, out)
    # 4. 匹配英文专业术语词组
    for en_term, zh_term in sorted(_TERM_MAP, key=lambda x: len(x[0]), reverse=True):
        pattern = re.compile(r"(?<![A-Za-z])" + re.escape(en_term) + r"(?![A-Za-z])", re.I)
        if pattern.search(out):
            out = pattern.sub(zh_term, out)
    out = re.sub(r"\binput-dyno\b", "输入测功机", out, flags=re.I)
    out = re.sub(r"\bmax\s+tq\s*@\s*parallel\b", "并联最大扭矩", out, flags=re.I)
    out = re.sub(r"\bevery\s+(?=\d)", "每", out, flags=re.I)
    # 5. 对剩余常见英文单词按词边界替换（保留标准代号和全大写工程缩写）
    _keep_upper = {
        "HMC", "HKMC", "HMG", "LDC", "XCM", "PCM", "MCU", "VCU", "BMS", "OBC", "PFC", "EWP",
        "CAN", "LIN", "PWM", "ADC", "EMC", "EMI", "EMS", "RFI", "ESD", "BCI", "NVH", "THD",
        "HV", "LV", "DC", "AC", "HVDC", "HVIL", "PCB", "TIM", "WCA", "DFMEA", "PFMEA",
        "FMEA", "3DCS", "CAE", "FEA", "CATIA", "CREO", "ASME", "ISO", "IEC", "CISPR", "ECE",
        "SAE", "GB", "QC", "UL", "AEC", "JESD", "MIL", "STD", "IPC", "VDI", "ASTM", "IEEE",
        "ES", "MS", "ESIR", "ISIR", "DV", "PV", "EOL", "SOP", "PROTO", "PILOT", "TCAR",
        "ASIL", "FSM", "FSMR", "DIA", "FSC", "DTC", "UDS", "AUTOSAR", "HSM", "SW", "HW",
        "BSW", "ASW", "INCA", "ROM", "CPU", "IC", "FET", "MLCC", "CT", "LED", "IGN",
        "TBD", "TBC", "MAX", "MIN", "TYP", "NOM", "RMS", "PK", "PP", "VPP", "V0", "RTI", "CTI",
        "HEV", "EV", "PHEV", "SUV", "DHT", "PE", "PT", "P1", "P2", "P3", "V2L", "ALSE",
    }

    def _replace_word(match: re.Match[str]) -> str:
        word = match.group(0)
        if word.isupper() and word in _keep_upper:
            return word
        low = word.lower()
        return _WORD_MAP.get(low, word)

    out = re.sub(
        r"\b(\d+)(?:st|nd|rd|th)\b(?=\s+(?:noise|order|harmonic)\b)",
        r"\1阶",
        out,
        flags=re.I,
    )
    out = re.sub(r"(?<=\bmotor\s)(\d+)(?:st|nd|rd|th)\b", r"\1阶", out, flags=re.I)
    out = re.sub(r"\b[A-Za-z][A-Za-z.]*\b", _replace_word, out)
    # 清理多余空格（中文字之间的空格收紧）
    out = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", out)
    return out.strip()


def _parse_json_list(blob: str) -> list[dict]:
    text = (blob or "").strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def translate_excerpts(
    items: list[tuple[int, str]],
    ask: Ask | None = None,
    on_progress=None,
) -> tuple[dict[int, str], bool]:
    """对 (seq, excerpt) 列表生成中文译文，返回 ({seq: 中文译文}, 是否使用了模型)。"""
    pending = [(seq, text) for seq, text in items if needs_translation(text)]
    if not pending:
        return {}, False

    translations: dict[int, str] = {}
    model_used = False
    total = len(pending)

    def _tick(done: int) -> None:
        if on_progress is None:
            return
        try:
            on_progress(done, total)
        except Exception:  # noqa: BLE001
            return

    _tick(0)
    if ask is not None:
        for i in range(0, len(pending), _BATCH_SIZE):
            batch = pending[i : i + _BATCH_SIZE]
            lines = []
            for seq, text in batch:
                snippet = text[:4000] if len(text) > 4000 else text
                lines.append(f"序号 {seq}：{snippet}")
            messages = [
                {"role": "system", "content": _TRANSLATE_PROMPT},
                {"role": "user", "content": "\n\n".join(lines)},
            ]
            try:
                reply = ask(messages)
                parsed = _parse_json_list(reply)
                for entry in parsed:
                    if not isinstance(entry, dict):
                        continue
                    seq_val = entry.get("序号")
                    zh_val = str(entry.get("译文") or "").strip()
                    source = next((text for seq, text in batch if seq == seq_val), "")
                    if isinstance(seq_val, int) and zh_val and _translation_covers(source, zh_val):
                        translations[seq_val] = zh_val
                        model_used = True
            except Exception:  # noqa: BLE001
                pass
            _tick(min(i + len(batch), total))

    # 对未命中或离线情况使用规则词典兜底，确保每条外文需求都有中文对照
    for seq, text in pending:
        if seq not in translations:
            zh = rule_translate_text(text)
            if zh and zh != text and _CJK.search(zh):
                translations[seq] = zh
    _tick(total)

    return translations, model_used


def _translation_covers(source: str, zh: str) -> bool:
    """模型只译了第一句时，不能当成整段译文。"""
    if not zh or not _CJK.search(zh):
        return False
    lines = [line.strip() for line in source.splitlines() if _needs_trans_body(line.strip())]
    if len(lines) <= 1:
        return True
    zh_lines = [line.strip() for line in zh.splitlines() if line.strip()]
    return len(zh_lines) >= len(lines) and len(_CJK.findall(zh)) >= len(lines)


def format_bilingual_excerpt(excerpt: str, zh: str) -> str:
    """将原文摘录与中文译文拼接为同格双语对照格式：「英文原文 / 中文译文」。"""
    raw = (excerpt or "").strip()
    trans = (zh or "").strip()
    if not trans or trans == raw:
        return raw
    src_lines = [line for line in raw.splitlines() if line.strip()]
    zh_lines = [line for line in trans.splitlines() if line.strip()]
    if len(src_lines) > 1:
        # 模型若把多行收成一段，行数对不上，按行用词典补齐，避免译文被挤到格子底部显示不全。
        if len(zh_lines) != len(src_lines):
            zh_lines = [_translate_segment(line) for line in src_lines]
        paired = []
        for src, line in zip(src_lines, zh_lines):
            line = line.strip().lstrip("/").strip()
            paired.append(f"{src} / {line}" if line and line != src and _CJK.search(line) else src)
        return "\n".join(paired)
    trans = re.sub(r"\s*\n\s*(?=[。，、；：）)])", "", trans)
    trans = re.sub(r"\s*\n\s*", " ", trans)
    trans = re.sub(r" {2,}", " ", trans).strip()
    return f"{raw} / {trans}"
