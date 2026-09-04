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
        ohm = next(c for c in (manifest.get("physics_cards") or []) if c.get("id") == "ohm")
        self.assertTrue(ohm.get("derive"))
        hipot = next(c for c in (manifest.get("physics_cards") or []) if c.get("id") == "hipot_2u")
        self.assertFalse(hipot.get("derive"))

    def test_retrieve_only_published_dielectric(self) -> None:
        frames = {f.seq: f for f in load_frames()}
        self.assertTrue(frames[14].retrieve)
        self.assertTrue(frames[19].retrieve)
        self.assertFalse(frames[22].retrieve)
        self.assertTrue(retrieve_enabled_for_name("高压安全-耐电压"))
        self.assertEqual(load_manifest().get("retrieve_seqs"), [14, 19])

    def test_keyword_and_citation(self) -> None:
        hits = keyword_hits("hipot dielectric 耐压", retrieve_only=True)
        seqs = {int(h["seq"]) for h in hits}
        self.assertTrue({14, 19} & seqs)
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
        rels = {e.get("rel") for e in neighbors(14)}
        self.assertIn("same_slot", rels)

    def test_browse_looks_like_catalog_not_files(self) -> None:
        data = browse_catalog()
        self.assertFalse(data.get("fill_from_kb"))
        self.assertFalse(data.get("leave_site"))
        self.assertEqual(data.get("version"), load_manifest().get("version"))
        self.assertGreaterEqual(data["stats"]["clauses"], 120)
        self.assertGreaterEqual(data["stats"]["physics"], 8)
        hipot = next(c for c in data["clauses"] if c["seq"] == 14)
        self.assertTrue(hipot["retrieve"])
        self.assertEqual(hipot["status_label"], "已开通检索")
        titles = [s["title"] for s in data["sources"]]
        self.assertTrue(any("清单" in t for t in titles))
        self.assertIn("条款词典", titles)
        self.assertIn("电机控制器物理关系", titles)
        leak = re.compile(
            r"(?i)(?:docs/)?[\w./-]+\.(?:ya?ml|json|md)\b|clause_lexicon|physics\.yaml"
        )
        dumped = json.dumps(data, ensure_ascii=False)
        hit = leak.search(dumped)
        self.assertIsNone(hit, hit.group(0) if hit else "")
        ohm = next(p for p in data["physics"] if p["id"] == "ohm")
        self.assertFalse(ohm.get("fill"))
        self.assertTrue(ohm.get("law"))
        self.assertTrue(ohm.get("gloss"))


if __name__ == "__main__":
    unittest.main()
