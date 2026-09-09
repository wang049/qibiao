"""条款词典：正别名进认条，禁配不进取值。"""
from __future__ import annotations

import re
import unittest

from electrical_krow.clause_lexicon import (
    aliases_for_seq,
    conflict_for_name,
    format_prompt_field,
    load_frames,
    prompt_aliases,
    reject_patterns_for_name,
    retrieve_aliases_for_name,
    retrieve_enabled_for_name,
)


class ClauseLexiconTests(unittest.TestCase):
    def test_loads_active_frames_without_dropped_duplicates(self) -> None:
        frames = load_frames()
        seqs = [item.seq for item in frames]
        self.assertEqual(len(frames), 116)
        self.assertEqual(frames[0].seq, 1)
        self.assertEqual(frames[-1].seq, 120)
        self.assertNotIn(18, seqs)
        self.assertNotIn(19, seqs)
        self.assertNotIn(26, seqs)
        self.assertNotIn(27, seqs)
        by_seq = {item.seq: item for item in frames}
        self.assertEqual(by_seq[13].name, "高压安全-绝缘电阻")
        self.assertEqual(by_seq[14].name, "高压安全-耐电压")
        self.assertEqual(by_seq[15].name, "高压安全-主动放电功能")
        self.assertEqual(by_seq[16].name, "高压安全-被动放电功能")
        self.assertIn("主动放电时间", aliases_for_seq(15, by_seq[15].name))
        self.assertIn("被动放电时间", aliases_for_seq(16, by_seq[16].name))
        self.assertTrue(by_seq[14].retrieve)
        self.assertFalse(by_seq[13].retrieve)

    def test_item_4_renamed_to_traction_boost(self) -> None:
        frames = {item.seq: item for item in load_frames()}
        self.assertEqual(frames[4].name, "设计范围是否包含行车升压功能")
        self.assertNotIn("行车升压", aliases_for_seq(3, frames[3].name))
        self.assertIn("行车升压", aliases_for_seq(4, frames[4].name))
        self.assertNotIn("将正式名", frames[4].gloss)
        self.assertNotIn("甲方将本条正式名", frames[4].gloss)
        self.assertNotIn("将正式名", frames[4].split_harm)
        self.assertIn("充电", frames[4].gloss)

    def test_dielectric_aliases_are_whole_words(self) -> None:
        aliases = aliases_for_seq(14, "高压安全-耐电压")
        self.assertIn("耐压", aliases)
        self.assertIn("hipot", aliases)
        self.assertNotIn("电压", aliases)
        self.assertTrue(retrieve_enabled_for_name("高压安全-耐电压"))
        retrieved = retrieve_aliases_for_name("高压安全-耐电压")
        self.assertIn("耐压", retrieved)
        self.assertIn("hipot", retrieved)
        self.assertNotIn("漏电流", retrieved)
        self.assertNotIn("withstand", retrieved)

    def test_other_aliases_are_prompt_only(self) -> None:
        self.assertFalse(retrieve_enabled_for_name("静态电流"))
        self.assertEqual(retrieve_aliases_for_name("静态电流"), ())
        aliases = aliases_for_seq(22, "静态电流")
        self.assertIn("未唤醒电流", aliases)
        self.assertIn("暗电流", aliases)
        self.assertIn("dark current", [item.lower() for item in aliases])

    def test_unverified_and_numeric_aliases_stay_out(self) -> None:
        od = {item.lower() for item in aliases_for_seq(1, "设计范围是否包含OD本体物理集成")}
        self.assertNotIn("oil distribution", od)
        ycap = aliases_for_seq(17, "高压安全-Y电容指标")
        self.assertNotIn("X", ycap)
        self.assertTrue(any("Y电容" == item or item.startswith("Y-") for item in ycap))
        discharge = {item.lower() for item in aliases_for_seq(25, "主动放电电阻")}
        self.assertNotIn("bleeder resistor", discharge)
        temp = {item.lower() for item in aliases_for_seq(97, "工作温度范围")}
        self.assertNotIn("surface temperature", temp)
        slip = aliases_for_seq(117, "滑膜起步功能")
        self.assertTrue(any("滑摩" in item for item in slip))

    def test_prompt_drops_example_like_aliases(self) -> None:
        shown = prompt_aliases(("耐压", "hipot", "kg", "5000m", "IP67", "Vpp"))
        self.assertIn("耐压", shown)
        self.assertIn("hipot", shown)
        self.assertIn("IP67", shown)
        self.assertNotIn("kg", shown)
        self.assertNotIn("5000m", shown)
        self.assertNotIn("Vpp", shown)
        label = format_prompt_field(14, "高压安全-耐电压")
        self.assertIn("14.高压安全-耐电压（规格常见：", label)
        self.assertIn("耐压", label)
        self.assertIn("hipot", label)
        self.assertNotIn("2828", label)

    def test_weak_aliases_are_not_prompt_aliases(self) -> None:
        self.assertEqual(aliases_for_seq(73, "控制器重量"), ())
        self.assertNotIn("weight", aliases_for_seq(28, "P1峰值功率"))
        self.assertIn("P1峰值功率", aliases_for_seq(28, "P1峰值功率"))

    def test_ripple_and_weight_conflicts_are_split(self) -> None:
        self.assertEqual(conflict_for_name("直流母线纹波电压要求"), "bus_ripple")
        self.assertEqual(conflict_for_name("高压安全-纹波电压"), "hv_safety_ripple")
        self.assertEqual(conflict_for_name("升压纹波电压"), "boost_ripple")
        self.assertNotEqual(
            conflict_for_name("控制器重量"),
            conflict_for_name("重量要求"),
        )

    def test_od_upshift_excludes_cooling_with_od(self) -> None:
        frames = {item.seq: item for item in load_frames()}
        reject = " ".join(frames[2].reject_patterns)
        self.assertIn("冷却流阻", reject)
        self.assertIn("with OD", reject)

    def test_p3_efficiency_excludes_p1_average(self) -> None:
        frames = {item.seq: item for item in load_frames()}
        p3_reject = " ".join(frames[56].reject_patterns)
        self.assertIn("P1平均效率", p3_reject)
        self.assertIn("Average efficiency", p3_reject)
        self.assertNotIn("综合效率", p3_reject)
        p3_cues = " ".join(frames[56].unit_cues)
        self.assertIn("综合效率", p3_cues)
        p1_reject = " ".join(frames[41].reject_patterns)
        self.assertIn("P3综合效率", p1_reject)

    def test_boost_power_split_harm_writes_kw_point(self) -> None:
        frames = {item.seq: item for item in load_frames()}
        harm = frames[68].split_harm
        self.assertIn("kW 点值", harm)
        self.assertIn("电压区间", harm)
        self.assertNotIn("不把 P=UI 算成 kW 区间", harm)

    def test_dielectric_reject_patterns(self) -> None:
        patterns = reject_patterns_for_name("高压安全-耐电压")
        blob = (
            "The unit must withstand continuous supply voltages of maximum 500V "
            "on the HVDC bus without any permanent"
        )
        self.assertTrue(any(re.search(pat, blob, re.I) for pat in patterns))
        device = "SiC MOSFET 器件耐压等级 1200V，按耐压选型"
        self.assertTrue(any(re.search(pat, device, re.I) for pat in patterns))
