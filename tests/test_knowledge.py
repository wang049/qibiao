"""知识库发布：确认后才进检索，物理关系不填数。"""
from __future__ import annotations

import importlib.util
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


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
        does_not = " ".join(manifest.get("scope", {}).get("does_not") or [])
        self.assertIn(".insights", does_not)
        self.assertIn("wiki", does_not)
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

    def test_method_standard_is_note_not_extracted_value(self) -> None:
        guide = (ROOT / "docs" / "清单与规格常见写法.md").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("抽出值可写「参考 方法标准号」", guide)
        self.assertNotIn("可把「参考 方法标准号」写入抽出值", guide)
        self.assertIn("方法号只写复核备注", guide)
        self.assertIn("抽出值仍标未检索到", guide)

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

    def test_short_latin_alias_needs_whole_word(self) -> None:
        """RE/CE/IR/IM/STO/NTC 这类缩写不得靠子串把普通英文句子认成条目。"""
        noise = keyword_hits("Requirements based on performance range")
        self.assertEqual(noise, [])
        seqs = {h["seq"] for h in keyword_hits("Insulation resistance 100MΩ")}
        self.assertIn(13, seqs)
        self.assertNotIn(76, seqs)
        seqs = {h["seq"] for h in keyword_hits("Req based on 8 poles and 16000 Rpm")}
        self.assertFalse({35, 52, 76} & seqs)
        self.assertIn(76, {h["seq"] for h in keyword_hits("EMC RE CE 辐射发射")})
        self.assertIn(93, {h["seq"] for h in keyword_hits("NTC 温度传感器")})
        self.assertIn(10, {h["seq"] for h in keyword_hits("Idc 母线电流检测")})


class KnowledgeEvalTests(unittest.TestCase):
    """认条召回题集：本仓 keyword_hits 与导出给公司知识库的检索层共用。"""

    @classmethod
    def setUpClass(cls) -> None:
        if not (ROOT / "docs" / "knowledge" / "published" / "manifest.json").is_file():
            raise unittest.SkipTest("先运行 python scripts/publish_knowledge.py")
        cls.runner = _load_script("eval_knowledge")
        cls.cases = cls.runner.load_cases()

    def test_eval_set_is_well_formed(self) -> None:
        self.assertGreaterEqual(len(self.cases), 30)
        ids = [c["id"] for c in self.cases]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(self.runner.lesson_refs_exist(self.cases), [])
        dumped = json.dumps(self.cases, ensure_ascii=False)
        for seq in (18, 19, 26, 27):
            for case in self.cases:
                self.assertNotIn(seq, case["must_hit"], case["id"])
        self.assertNotRegex(dumped, r"8000\s*小时|通常\s*15\s*年")

    def test_eval_set_passes_on_keyword_hits(self) -> None:
        results = self.runner.run_eval(self.cases, keyword_hits)
        failed = [(r["id"], r["problems"]) for r in results if not r["ok"]]
        self.assertEqual(failed, [])
        by_id = {r["id"]: r for r in results}
        self.assertEqual(by_id["hipot-retrieve-only"]["got"], [14])
        self.assertEqual(by_id["connector-not-charge"]["got"], [])
        self.assertIn(67, by_id["hv-booster-modes-67"]["got"])
        self.assertEqual(by_id["continuous-hvdc-caution"]["caution"], [14])


class KnowledgeExportTests(unittest.TestCase):
    """导出给公司知识库的 Record / bundle：不带取值、不带内部字段、不带保密原文。"""

    @classmethod
    def setUpClass(cls) -> None:
        if not (ROOT / "docs" / "knowledge" / "published" / "manifest.json").is_file():
            raise unittest.SkipTest("先运行 python scripts/publish_knowledge.py")
        cls.exporter = _load_script("export_kb_bundle")
        cls.bundle = cls.exporter.build_bundle()

    def test_bundle_shape_and_governance_flags(self) -> None:
        b = self.bundle
        self.assertEqual(b["schema"], "electrical-kb-bundle/0.1")
        self.assertEqual(b["knowledge_version"], load_manifest().get("version"))
        self.assertFalse(b["fill_from_kb"])
        self.assertFalse(b["leave_site"])
        self.assertEqual(b["retrieve_seqs"], [14])
        self.assertEqual(b["dropped_seqs"], [18, 19, 26, 27])
        kinds = {}
        for rec in b["records"]:
            kinds[rec["kind"]] = kinds.get(rec["kind"], 0) + 1
            for key in ("kind", "title", "symbol", "source", "content", "payload"):
                self.assertIn(key, rec, rec.get("title"))
            self.assertFalse(rec["payload"]["fill_from_kb"])
            self.assertFalse(rec["payload"]["leave_site"])
            self.assertEqual(rec["payload"]["knowledge_version"], b["knowledge_version"])
        self.assertEqual(kinds["clause"], 116)
        self.assertGreaterEqual(kinds["physics"], 8)
        self.assertGreaterEqual(kinds["enterprise_std"], 40)
        self.assertGreaterEqual(kinds["enterprise_term"], 5)

    def test_clause_records_drop_internal_fields_and_deleted_items(self) -> None:
        clauses = {int(r["symbol"]): r for r in self.bundle["records"] if r["kind"] == "clause"}
        for seq in (18, 19, 26, 27):
            self.assertNotIn(seq, clauses)
        hipot = clauses[14]
        self.assertTrue(hipot["payload"]["retrieve"])
        self.assertEqual(hipot["payload"]["status"], "published")
        self.assertIn("hipot", hipot["payload"]["aliases_retrieve"])
        self.assertIn("#14", hipot["source"])
        self.assertIn("知识库", hipot["source"])
        self.assertIn("不提供取值", hipot["content"])
        item4 = clauses[4]
        self.assertFalse(item4["payload"]["retrieve"])
        self.assertEqual(item4["payload"]["aliases_retrieve"], [])
        for rec in clauses.values():
            for field in ("notes", "split_harm", "unverified", "reject_patterns", "weak_aliases"):
                self.assertNotIn(field, rec["payload"], rec["title"])
        dumped = json.dumps(self.bundle["records"], ensure_ascii=False)
        self.assertNotIn(".insights", dumped)
        self.assertNotIn(".krow", dumped)
        self.assertNotIn("甲方", dumped)
        self.assertNotIn("乙方", dumped)
        self.assertNotIn("6.5.4 写明", dumped)

    def test_secret_enterprise_std_has_no_gloss_and_no_cloud_generate(self) -> None:
        stds = [r for r in self.bundle["records"] if r["kind"] in {"enterprise_std", "enterprise_term"}]
        self.assertTrue(stds)
        for rec in stds:
            self.assertEqual(rec["payload"]["classification"], "保密一级")
            self.assertFalse(rec["payload"]["cloud_generate"], rec["title"])
            self.assertNotIn("说明：", rec["content"])
            self.assertNotIn("当份 DPR 查看", rec["content"])
        c63 = next(r for r in stds if r["payload"].get("clause") == "6.3")
        self.assertEqual(c63["payload"]["see_seq"], [14])
        self.assertIn("6.3", c63["symbol"])
        self.assertTrue(any("J7110218" in m for m in c63["payload"]["method_std"]))
        for rec in self.bundle["records"]:
            if rec["kind"] in {"clause", "physics"}:
                self.assertTrue(rec["payload"]["cloud_generate"])

    def test_aliases_export_strong_and_retrieve_only(self) -> None:
        aliases = self.bundle["aliases"]
        self.assertEqual(aliases["schema"], "electrical-kb-aliases/0.1")
        rows = aliases["aliases"]
        kinds = {r["kind"] for r in rows}
        self.assertEqual(kinds, {"hint", "retrieve"})
        retrieve_symbols = {r["symbol"] for r in rows if r["kind"] == "retrieve"}
        self.assertEqual(retrieve_symbols, {"14"})
        exported = {(r["alias"], r["symbol"]) for r in rows}
        self.assertIn(("耐电压", "14"), exported)
        self.assertIn(("行车升压", "4"), exported)
        # 弱别名不导出：#4 的「充电升压」、#35/#52 共享的「最高工作转速」
        self.assertNotIn(("充电升压", "4"), exported)
        self.assertNotIn(("最高工作转速", "35"), exported)
        self.assertNotIn(("最高工作转速", "52"), exported)
        self.assertNotIn(("ASC电流能力", "40"), exported)

    def test_graph_keeps_relations_without_dropped_items(self) -> None:
        graph = self.bundle["graph"]
        rels = {e["rel"] for e in graph["edges"]}
        self.assertEqual(rels, {"related", "not", "same_slot", "interprets"})
        for edge in graph["edges"]:
            for end in (edge["from"], edge["to"]):
                self.assertNotIn(end, {"clause:18", "clause:19", "clause:26", "clause:27"})
        ids = {n["id"] for n in graph["nodes"]}
        self.assertIn("clause:14", ids)
        self.assertIn("physics:hipot_2u", ids)
        self.assertNotIn("clause:18", ids)

    def test_export_writes_record_files_only(self) -> None:
        """bundle.json 归轨 A 编译器（compile_kb_bundle）写，Record 导出不再落同名文件。"""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = self.exporter.export(Path(tmp))
            names = sorted(p.name for p in out.iterdir())
            self.assertEqual(names, ["query_aliases.yaml", "records.jsonl"])
            lines = (out / "records.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), len(self.bundle["records"]))
            first = json.loads(lines[0])
            self.assertEqual(first["kind"], "clause")


class KnowledgeCompileTests(unittest.TestCase):
    """轨 A 结构化知识包：确定性、零 LLM，entities / relations / wiki_pages 契约 + 薄 domain_pack。"""

    @classmethod
    def setUpClass(cls) -> None:
        if not (ROOT / "docs" / "knowledge" / "published" / "manifest.json").is_file():
            raise unittest.SkipTest("先运行 python scripts/publish_knowledge.py")
        from datetime import datetime, timezone

        cls.compiler = _load_script("compile_kb_bundle")
        cls.now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
        cls.bundle = cls.compiler.build_bundle(cls.now)

    def test_top_level_contract(self) -> None:
        b = self.bundle
        self.assertEqual(sorted(b), ["entities", "id", "meta", "relations", "space", "version", "wiki_pages"])
        self.assertEqual(b["id"], "electrical-xcm-clauses")
        self.assertEqual(b["space"], "electrical")
        self.assertRegex(b["version"], r"^\d{8}T\d{6}Z$")
        self.assertEqual(b["meta"]["knowledge_version"], load_manifest().get("version"))
        self.assertEqual(b["meta"]["compile_policy"], "off")
        self.assertFalse(b["meta"]["fill_from_kb"])
        self.assertFalse(b["meta"]["leave_site"])
        stats = b["meta"]["stats"]
        self.assertEqual(stats["CLAUSE"], 116)
        self.assertEqual(stats["uncategorized"], 0)
        self.assertEqual(stats["relations"], len(b["relations"]))
        self.assertEqual(stats["wiki_pages"], len(b["wiki_pages"]))

    def test_deterministic(self) -> None:
        again = self.compiler.build_bundle(self.now)
        self.assertEqual(json.dumps(again, ensure_ascii=False, sort_keys=True),
                         json.dumps(self.bundle, ensure_ascii=False, sort_keys=True))

    def test_entities_identity_category_and_governance(self) -> None:
        ents = {e["id"]: e for e in self.bundle["entities"]}
        for seq in (18, 19, 26, 27):
            self.assertNotIn(f"clause:{seq}", ents)
        hipot = ents["clause:14"]
        self.assertEqual(hipot["type"], "CLAUSE")
        self.assertEqual(hipot["identity"], {"resolution": "distinct", "decided_by": "rule", "rules_fired": ["list_seq_unique"]})
        self.assertEqual(hipot["category"]["id"], "hv_safety")
        self.assertEqual(hipot["category"]["basis"], "list_group")
        self.assertEqual(hipot["uuids"], [])
        ns = {n["ns"] for n in hipot["names"]}
        self.assertEqual(ns, {"list_name", "alias_strong", "alias_retrieve"})
        self.assertTrue(hipot["data"]["retrieve"])
        self.assertEqual({n["ns"] for n in ents["clause:4"]["names"]}, {"list_name", "alias_strong"})
        texts = {n["text"] for n in ents["clause:4"]["names"]}
        self.assertIn("行车升压", texts)
        self.assertNotIn("充电升压", texts)  # 弱别名
        # 只有 CLAUSE 带 category；PHYSICS / STD / TERM 走类型桶
        for e in ents.values():
            self.assertEqual("category" in e, e["type"] == "CLAUSE", e["id"])
            self.assertFalse(e["data"]["fill_from_kb"])
            self.assertFalse(e["data"]["leave_site"])
            for f in ("notes", "split_harm", "unverified", "reject_patterns", "weak_aliases"):
                self.assertNotIn(f, e["data"])
        std = ents["std:6.3"]
        self.assertEqual(std["type"], "STD_CLAUSE")
        self.assertEqual(std["data"]["classification"], "保密一级")
        self.assertFalse(std["data"]["cloud_generate"])
        self.assertNotIn("gloss", std["data"])
        self.assertTrue(ents["physics:ohm"]["data"]["cloud_generate"])
        cats = {e["category"]["id"] for e in ents.values() if e["type"] == "CLAUSE"}
        self.assertEqual(len(cats), 12)

    def test_relations_and_wiki_pages(self) -> None:
        ids = {e["id"] for e in self.bundle["entities"]}
        types = {r["type"] for r in self.bundle["relations"]}
        self.assertEqual(types, {"related", "not", "same_slot", "interprets", "verifies", "term_of"})
        for r in self.bundle["relations"]:
            self.assertIn(r["from"], ids)
            self.assertIn(r["to"], ids)
        self.assertIn("rel:verifies:std:6.3->clause:14", {r["id"] for r in self.bundle["relations"]})
        pages = {p["id"]: p for p in self.bundle["wiki_pages"]}
        self.assertEqual(len([p for p in pages.values() if p["page_type"] == "entity"]), 116)
        idx = pages["wikipage:electrical/index"]
        self.assertEqual((idx["page_type"], idx["tier"]), ("essay", "essay"))
        self.assertNotIn("category", idx)
        p14 = pages["wikipage:electrical/clause-14"]
        self.assertEqual(p14["entity_id"], "clause:14")
        self.assertEqual(p14["category"], "hv_safety")
        self.assertIn("category: hv_safety", p14["content"])
        self.assertIn("不提供取值", p14["content"])
        dumped = json.dumps(self.bundle, ensure_ascii=False)
        for bad in (".insights", ".krow", "甲方", "乙方", "xlsx.example"):
            self.assertNotIn(bad, dumped)

    def test_domain_pack_manifest_keys_are_closed(self) -> None:
        m = self.compiler.domain_pack_manifest("x")
        self.assertEqual(set(m), self.compiler.MANIFEST_ALLOWED_KEYS)
        self.assertEqual(m["id"], "electrical")
        self.assertEqual(m["entity_kinds_extend"], ["CLAUSE", "PHYSICS_LAW", "STD_CLAUSE", "TERM"])
        self.assertEqual(set(m["ui_grouping"]), set(m["entity_kinds_extend"]))
        rel_types = {r["type"] for r in self.bundle["relations"]}
        self.assertTrue(rel_types <= set(m["relation_kinds_extend"]))

    def test_validate_rejects_unknown_group_and_leak(self) -> None:
        import copy

        bad = copy.deepcopy(self.bundle)
        bad["entities"][0]["category"]["id"] = "meshing"
        with self.assertRaises(SystemExit):
            self.compiler.validate(bad)
        bad = copy.deepcopy(self.bundle)
        bad["entities"][0]["data"]["gloss"] += " 见 .insights"
        with self.assertRaises(SystemExit):
            self.compiler.validate(bad)
        with self.assertRaises(SystemExit):
            self.compiler._category("网格")

    def test_compile_writes_bundle_and_manifest(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = self.compiler.compile_pack(Path(tmp), self.now)
            self.assertEqual(sorted(p.name for p in out.iterdir()), ["bundle.json", "domain_pack.json"])
            b = json.loads((out / "bundle.json").read_text(encoding="utf-8"))
            self.assertEqual(b["version"], "20260916T120000Z")


if __name__ == "__main__":
    unittest.main()
