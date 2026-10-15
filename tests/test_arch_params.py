from __future__ import annotations

import json
import unittest

from electrical_krow.arch_contrast import COLUMNS
from electrical_krow.arch_params import (
    CONSIST_COND,
    CONSIST_DIFF,
    CONSIST_SAME,
    CONSIST_SINGLE,
    PARAM_COLUMNS,
    SOURCE_MODEL,
    SOURCE_RULE,
    SOURCE_TABLE,
    Param,
    canonicalize,
    check_consistency,
    collect_params,
    model_split,
    param_rows,
    rule_split,
    split_rows,
)

_COL = {name: index for index, name in enumerate(COLUMNS)}


def _row(seq: int, page: int, text: str, qty: str = "", item: str = "", cond: str = "", section: str = "2 Spec") -> list[object]:
    row: list[object] = [""] * len(COLUMNS)
    row[_COL["序号"]] = seq
    row[_COL["对象"]] = "LDC"
    row[_COL["文件"]] = "ldc.pdf"
    row[_COL["PDF页码"]] = page
    row[_COL["章节"]] = section
    row[_COL["项目（表格栏目）"]] = item
    row[_COL["原文摘录"]] = text
    row[_COL["数值与单位"]] = qty
    row[_COL["适用条件（原文括注）"]] = cond
    return row


_ROWS = [
    _row(1, 1, "LDC Revision history 2.5kW LDC", "2.5kW", section=""),  # 封面前的修订页，不算
    _row(2, 13, "Classification：Environment | Humidity：90 %", "90 %", item="Environment / Humidity / Max"),
    _row(3, 16, "Classification：Reliability | Content：Must satisfy the durability life. (15 years / 300,000 km) Must meet 99.85% reliability.",
         "durability life. (15 years / 300,000 km)；Must meet 99.85%", item="Reliability"),
    _row(4, 26, "Items：Reliability | Request Specifications：Must meet durability performance. (15 years/ 300,000km) Must meet the 99.80% reliability",
         "durability performance. (15 years/ 300,000km)；Must meet the 99.80%", item="Reliability"),
    _row(5, 19, "Classification：DESIGN | Contents：Use DFMEA", "Use DFMEA", item="DESIGN"),
    _row(6, 19, "Classification：DESIGN | Contents：Use worst case analysis", "Use worst case analysis", item="DESIGN"),
    _row(7, 22, "Connectors shall be at least 10mm from the bottom of the LDC and at least 25mm from other parts.",
         "Connectors shall be at least 10mm；the LDC and at least 25mm"),
    _row(8, 29, "Classification：Dark Current | Specification：1mA↓(in all cases, such as IG off)", "1mA↓", item="Dark Current", cond="in all cases, such as IG off"),
    _row(9, 30, "本页表格（3 行 × 2 列），整表见「整表附件」", "3 行 × 2 列"),
    _row(10, 31, "Classification：Materials | Spec：Satisfy HMC Spec. MS 201-01 and all the long sentences about surface treatment that go on and on and on", "Satisfy HMC Spec. MS 201-01 and all the long sentences about surface treatment that go on and on and on", item="Materials"),
]


class ArchParamsTests(unittest.TestCase):
    def test_split_rows_keeps_simple_cells_and_hands_multi_value_cells_to_splitting(self) -> None:
        simple, targets = split_rows(_ROWS)
        self.assertEqual([(p.name, p.value, p.cond, p.source) for p in simple],
                         [("Environment / Humidity / Max", "90 %", "", SOURCE_TABLE), ("Dark Current", "1mA↓", "in all cases, such as IG off", SOURCE_TABLE)])
        self.assertEqual([(t.seq, t.base) for t in targets], [(3, "Reliability"), (4, "Reliability"), (7, "")])
        # 封面前的页、清单表（同一栏目多行且没有数）、本页索引行、整句要求都不进参数清单
        self.assertNotIn(1, [t.seq for t in targets])
        self.assertNotIn("DESIGN", [p.name for p in simple])

    def test_rule_split_names_by_lead_words(self) -> None:
        _, targets = split_rows(_ROWS)
        params = rule_split(targets)
        names = [(p.name, p.value) for p in params]
        self.assertIn(("Connectors shall be at least", "10mm"), names)
        self.assertIn(("the LDC and at least", "25mm"), names)
        self.assertTrue(all(p.source == SOURCE_RULE for p in params))
        self.assertTrue(any(p.name.startswith("Reliability / ") and p.value.startswith("15 years") for p in params))

    def test_model_split_verifies_values_against_source_text(self) -> None:
        _, targets = split_rows(_ROWS)
        calls: list[str] = []

        def ask(messages):
            calls.append(messages[1]["content"])
            return json.dumps([
                {"序号": 3, "参数": [
                    {"参数": "耐久寿命", "取值": "15 years / 300,000 km", "条件": ""},
                    {"参数": "可靠度", "取值": "99.85%", "条件": "not in text"},
                    {"参数": "编造", "取值": "88%", "条件": ""},
                ]},
                {"序号": 4, "参数": [
                    {"参数": "耐久寿命", "取值": "15 years/ 300,000km", "条件": ""},
                    {"参数": "可靠度", "取值": "99.80%", "条件": ""},
                ]},
            ], ensure_ascii=False)

        params, notes = model_split(targets, ask)
        self.assertEqual(len(calls), 1)
        self.assertIn("序号 3（表格栏目：Reliability）", calls[0])
        by_name = {(p.row_seq, p.name): p for p in params}
        self.assertEqual(by_name[(3, "Reliability / 耐久寿命")].value, "15 years / 300,000 km")
        self.assertEqual(by_name[(3, "Reliability / 可靠度")].cond, "")  # 条件不在原文里就清空
        self.assertNotIn((3, "Reliability / 编造"), by_name)  # 原文没有的取值丢弃
        self.assertTrue(any("找不到原字串" in n for n in notes))
        # 模型没回答的序号 7 按规则兜底
        self.assertTrue(any(p.row_seq == 7 and p.source == SOURCE_RULE for p in params))
        self.assertTrue(all(p.source == SOURCE_MODEL for p in params if p.row_seq in (3, 4)))

    def test_canonicalize_merges_by_rule_then_by_model(self) -> None:
        params = [
            Param("Output / Voltage", "13.9V", "", "LDC", "f", 1, "", 1, SOURCE_TABLE),
            Param("output voltage", "13.9V", "", "LDC", "f", 2, "", 2, SOURCE_TABLE),
            Param("Vout nominal", "13.9V", "", "LDC", "f", 3, "", 3, SOURCE_TABLE),
        ]
        used, _ = canonicalize(params, None)
        self.assertFalse(used)
        self.assertEqual(params[0].canon, params[1].canon)
        self.assertNotEqual(params[0].canon, params[2].canon)

        def ask(messages):
            return json.dumps({"Output / Voltage": "输出电压", "output voltage": "输出电压", "Vout nominal": "输出电压"}, ensure_ascii=False)

        used, notes = canonicalize(params, ask)
        self.assertTrue(used)
        self.assertEqual({p.canon for p in params}, {"输出电压"})
        self.assertEqual(notes, [])

    def test_consistency_compares_quantities_and_respects_conditions(self) -> None:
        def p(name, value, cond, page, seq=None):
            param = Param(name, value, cond, "LDC", "f", page, "", seq or page, SOURCE_TABLE)
            param.canon = name
            return param

        params = [
            p("耐久寿命", "durability life. (15 years / 300,000 km)", "", 16),
            p("耐久寿命", "15 years/ 300,000km", "", 26),
            p("可靠度", "99.85%", "", 16),
            p("可靠度", "99.80%", "", 26),
            p("可靠度", "99.85%", "50% confidence level", 29),
            p("效率", "90%↑", "@Vin=180V", 29, 291),
            p("效率", "91%↑", "@Iout=30A", 29, 292),
            p("暗电流", "1mA↓", "", 29),
            p("输出电流", "2% (400W ↑)", "", 15),  # 精度，不是电流：单位不同不比
            p("输出电流", "180A", "", 29),
            p("效率", "Principle test", "", 42),  # 没有数的验证方法，不和 90%↑ 比
        ]
        conflicts = check_consistency(params)
        self.assertEqual((params[8].consistency, params[9].consistency, params[10].consistency), (CONSIST_SINGLE, CONSIST_SINGLE, CONSIST_SINGLE))
        same_row = [p("最大输出", "2.30kW", "", 29, 300), p("最大输出", "2.72kW", "", 29, 300)]  # 一格里按工况列的两个值
        self.assertEqual(check_consistency(same_row), 0)
        self.assertEqual(same_row[0].consistency, CONSIST_SINGLE)
        self.assertEqual(params[0].consistency, CONSIST_SAME)
        self.assertEqual(params[1].consistency, CONSIST_SAME)
        self.assertEqual(params[2].consistency, CONSIST_DIFF)
        self.assertIn("第 26 页「可靠度」：99.80%", params[2].others)
        self.assertEqual(params[3].consistency, CONSIST_DIFF)
        # 同值的另一处即使条件不同也算一致；取值不同但条件不同的只标「条件不同」
        self.assertEqual(params[4].consistency, CONSIST_SAME)
        self.assertEqual(params[5].consistency, CONSIST_COND)
        self.assertEqual(params[6].consistency, CONSIST_COND)
        self.assertEqual(params[7].consistency, CONSIST_SINGLE)
        self.assertEqual(conflicts, 2)

    def test_collect_params_without_model_is_rule_only_and_annotates_conflict_rows(self) -> None:
        rows = _ROWS + [_row(11, 40, "Classification：Dark Current | Specification：2mA↓(in all cases, such as IG off)", "2mA↓", item="Dark Current", cond="in all cases, such as IG off")]
        result = collect_params(rows, None)
        self.assertFalse(result.model_used)
        # 暗电流 1mA/2mA 同条件不同值；可靠度 99.85%/99.80%（引导词都是 must meet）；耐久寿命两处引导词不同，各自唯一
        self.assertEqual(result.conflicts, 4)
        self.assertEqual(set(result.conflict_rows), {3, 4, 8, 11})
        self.assertEqual([p.value for p in result.params if p.row_seq == 3], ["15 years / 300,000 km", "99.85%"])
        self.assertIn("与别处不一致：第 ", result.conflict_rows[8])  # 备注里直接写别处页码和取值
        sheet = param_rows(result)
        self.assertEqual(len(sheet[0]), len(PARAM_COLUMNS))
        self.assertTrue(all(r[PARAM_COLUMNS.index("状态")] == "待确认" for r in sheet))
        self.assertEqual([r[PARAM_COLUMNS.index("PDF页码")] for r in sheet], sorted(r[PARAM_COLUMNS.index("PDF页码")] for r in sheet))


if __name__ == "__main__":
    unittest.main()
