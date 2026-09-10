"""知识库发布：确认后才进检索，物理关系不填数。"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from electrical_krow.knowledge import (
    browse_catalog,
    citation_for_seq,
    fill_from_kb_allowed,
    keyword_hits,
    knowledge_version,
    load_graph,
    load_manifest,
    neighbors,
)
from electrical_krow.clause_lexicon import load_frames, retrieve_enabled_for_name


ROOT = Path(__file__).resolve().parents[1]


class KnowledgePublishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        manifest = ROOT / "docs" / "knowledge" / "published" / "manifest.json"
        if not manifest.is_file():
            raise unittest.SkipTest("先运行 python scripts/publish_knowledge.py")

    def test_kb_never_fills_cells(self) -> None:
        self.assertFalse(fill_from_kb_allowed())
        manifest = load_manifest()
        self.assertFalse(manifest.get("fill_from_kb"))
        self.assertFalse(manifest.get("leave_site"))
        for card in manifest.get("physics_cards") or []:
            self.assertFalse(card.get("fill"))
        for row in (manifest.get("enterprise") or {}).get("clauses") or []:
            self.assertFalse(row.get("fill"))
        for row in (manifest.get("enterprise") or {}).get("terms") or []:
            self.assertFalse(row.get("fill"))
        self.assertFalse((manifest.get("enterprise") or {}).get("fill", True))
        ohm = next(c for c in (manifest.get("physics_cards") or []) if c.get("id") == "ohm")
        self.assertTrue(ohm.get("derive"))
        hipot = next(c for c in (manifest.get("physics_cards") or []) if c.get("id") == "hipot_2u")
        self.assertFalse(hipot.get("derive"))

    def test_retrieve_only_published_dielectric(self) -> None:
        frames = {f.seq: f for f in load_frames()}
        self.assertTrue(frames[14].retrieve)
        self.assertNotIn(19, frames)
        self.assertFalse(frames[22].retrieve)
        self.assertTrue(retrieve_enabled_for_name("高压安全-耐电压"))
        self.assertEqual(load_manifest().get("retrieve_seqs"), [14])
        self.assertEqual(load_manifest().get("dropped_seqs"), [18, 19, 26, 27])

    def test_keyword_and_citation(self) -> None:
        hits = keyword_hits("hipot dielectric 耐压", retrieve_only=True)
        seqs = {int(h["seq"]) for h in hits}
        self.assertTrue({14} & seqs)
        self.assertNotIn(19, seqs)
        text = citation_for_seq(14, "高压安全-耐电压")
        self.assertIn("#14", text)
        self.assertIn("知识库", text)
        self.assertEqual(knowledge_version(), load_manifest().get("version"))
        self.assertTrue(knowledge_version())

    def test_graph_has_physics_and_conflicts(self) -> None:
        graph = load_graph()
        ids = {n.get("id") for n in graph.get("nodes") or []}
        self.assertIn("physics:p_ui", ids)
        self.assertIn("physics:ohm", ids)
        self.assertIn("physics:kirchhoff", ids)
        self.assertIn("physics:p_ac3", ids)
        self.assertIn("physics:rc_discharge", ids)
        self.assertIn("physics:eta", ids)
        self.assertIn("physics:idc", ids)
        self.assertIn("physics:ploss_eta", ids)
        self.assertIn("physics:hipot_2u", ids)
        self.assertIn("clause:14", ids)
        self.assertNotIn("clause:18", ids)
        self.assertNotIn("clause:19", ids)
        rels = {e.get("rel") for e in neighbors(14)}
        self.assertTrue({"related", "interprets"} & rels)

    def test_browse_looks_like_catalog_not_files(self) -> None:
        data = browse_catalog()
        self.assertFalse(data.get("fill_from_kb"))
        self.assertFalse(data.get("leave_site"))
        self.assertEqual(data.get("version"), load_manifest().get("version"))
        self.assertGreaterEqual(data["stats"]["clauses"], 116)
        self.assertEqual(data["stats"]["clauses"], 116)
        self.assertGreaterEqual(data["stats"]["physics"], 8)
        hipot = next(c for c in data["clauses"] if c["seq"] == 14)
        self.assertTrue(hipot["retrieve"])
        self.assertEqual(hipot["status_label"], "已开通检索")
        seqs = {c["seq"] for c in data["clauses"]}
        self.assertNotIn(18, seqs)
        self.assertNotIn(19, seqs)
        self.assertNotIn(26, seqs)
        self.assertNotIn(27, seqs)
        titles = [s["title"] for s in data["sources"]]
        self.assertTrue(any("清单" in t for t in titles))
        self.assertIn("条款词典", titles)
        self.assertIn("电机控制器物理关系", titles)
        self.assertTrue(any("030602" in t or "电机控制器设计验证规范" in t for t in titles))
        leak = re.compile(
            r"(?i)(?:docs/)?[\w./-]+\.(?:ya?ml|json|md)\b|clause_lexicon|physics\.yaml|enterprise_std"
        )
        dumped = json.dumps(data, ensure_ascii=False)
        hit = leak.search(dumped)
        self.assertIsNone(hit, hit.group(0) if hit else "")
        ohm = next(p for p in data["physics"] if p["id"] == "ohm")
        self.assertFalse(ohm.get("fill"))
        self.assertTrue(ohm.get("law"))
        self.assertTrue(ohm.get("gloss"))

    def test_browse_hides_contract_parties_on_sources(self) -> None:
        data = browse_catalog()
        scope = json.dumps(data.get("scope") or {}, ensure_ascii=False)
        self.assertNotIn("甲方", scope)
        self.assertNotIn("乙方", scope)
        self.assertIn("口径经确认后使用", data["scope"]["owner"])
        self.assertIn("业务系统数据", " ".join(data["scope"]["does_not"]))
        self.assertFalse(any("甲方" in x or "乙方" in x for x in data["scope"]["does_not"]))
        by_id = {s["id"]: s for s in data["sources"]}
        self.assertEqual(by_id["list-120"]["status"], "已确认")
        self.assertEqual(by_id["clause-yaml"]["status"], "待确认")
        self.assertEqual(by_id["physics"]["status"], "待确认")
        self.assertEqual(by_id["enterprise-std"]["status"], "待确认")
        self.assertEqual(by_id["manuals"]["status"], "待确认")
        for src in data["sources"]:
            blob = json.dumps(src, ensure_ascii=False)
            self.assertNotIn("甲方", blob, src["id"])
            self.assertNotIn("乙方", blob, src["id"])
            self.assertNotIn("provided_by", src)

    def test_enterprise_std_is_method_not_fill(self) -> None:
        import yaml

        path = ROOT / "docs" / "knowledge" / "enterprise_std.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertIs(raw.get("fill"), False)
        blob = json.dumps(raw, ensure_ascii=False)
        self.assertNotRegex(blob, r"8000\s*小时")
        self.assertNotRegex(blob, r"通常\s*15\s*年")
        c62 = next(c for c in raw["clauses"] if c["id"] == "6.2")
        self.assertEqual(c62["see_seq"], [13])
        c63 = next(c for c in raw["clauses"] if c["id"] == "6.3")
        self.assertEqual(c63["see_seq"], [14])
        c622 = next(c for c in raw["clauses"] if c["id"] == "6.22")
        self.assertIn(100, c622["see_seq"])
        self.assertNotIn(71, c622["see_seq"])
        self.assertNotIn(72, c622["see_seq"])
        self.assertTrue(any("J7111029" in x and "5.3.10" in x for x in c622["method_std"]))
        ids = [c["id"] for c in raw["clauses"]]
        self.assertIn("6.36", ids)
        self.assertIn("7", ids)
        self.assertIn("7.9", ids)
        self.assertNotIn("7.10", ids)

        data = browse_catalog()
        self.assertFalse(data.get("fill_from_kb"))
        self.assertGreaterEqual(data["stats"]["enterprise"], 40)
        hipot = next(c for c in data["clauses"] if c["seq"] == 14)
        self.assertTrue(any("030602" in s and "6.3" in s for s in hipot["std"]))
        self.assertFalse(any("不提供抽出值" in s or "评价看当份" in s for s in hipot["std"]))
        ins = next(c for c in data["clauses"] if c["seq"] == 13)
        self.assertTrue(any("030602" in s and "6.2" in s for s in ins["std"]))
        humid = next(e for e in data["enterprise"] if e["id"] == "6.22")
        self.assertFalse(humid.get("fill"))
        self.assertIn(100, humid["see_seq"])
        self.assertNotIn(71, humid["see_seq"])
        life = next(e for e in data["enterprise"] if e["id"] == "6.32")
        self.assertIn("寿命周期运行时间", life.get("look_in_dpr") or [])
        src = next(s for s in data["sources"] if s["id"] == "enterprise-std")
        self.assertIn("030602", src["version"] + src["title"] + src["used_for"])
        self.assertIn("不得填抽出值", src["used_for"])
        dumped = json.dumps(data, ensure_ascii=False)
        self.assertNotIn("8000", dumped)
        self.assertNotRegex(dumped, r"通常\s*15\s*年")

    def test_clause_gloss_is_current_meaning_not_rename(self) -> None:
        data = browse_catalog()
        item4 = next(c for c in data["clauses"] if c["seq"] == 4)
        self.assertEqual(item4["name"], "设计范围是否包含行车升压功能")
        self.assertNotIn("将正式名", item4["gloss"])
        self.assertNotIn("甲方将本条正式名", item4["gloss"])
        self.assertNotIn("原充电升压", item4["gloss"])
        self.assertIn("115", item4["gloss"])
        frames = {f.seq: f for f in load_frames()}
        self.assertNotRegex(frames[3].split_harm, r"现为\s*#4\s*正式名")
        self.assertNotIn("将正式名", frames[4].split_harm)


if __name__ == "__main__":
    unittest.main()
