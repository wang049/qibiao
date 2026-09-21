# -*- coding: utf-8 -*-
"""把已发布的条款知识库编译成公司知识中枢「轨 A」结构化知识包（bundle.json + domain_pack.json）。

对齐《SimLab 领域包与编译：实现原理》：
- 零 LLM、确定性。只读 docs/knowledge/published/ 与 docs/clause_lexicon.json，重跑结果逐字节一致（version 时间戳除外）。
- bundle 顶层：id / version / space / meta / entities / relations / wiki_pages。
  同一 id 现场重导视为新版本（upsert + 删孤儿），所以实体 id 必须稳定：清单序号就是稳定号。
- 只有 CLAUSE 实体带 category（对应 SimLab 里只有 CAPABILITY 带功能域）；分类来自清单「分组」，
  层序只有一层 list_group，未知分组直接报错，不允许出现 uncategorized。
- identity 全部 distinct / decided_by=rule：清单序号唯一，不存在同名待裁定。
- wiki_pages 是图的投影：每条 CLAUSE 一页 + 两篇 essay（索引、物理关系）。
- domain_pack.json 是薄 manifest，键集合卡死（MANIFEST_ALLOWED_KEYS）。
- 空间 compile_policy 必须 off（写进 meta 提醒，导入脚本自行落实）。

治理约束照旧：fill_from_kb=false、leave_site=false；不带 notes / split_harm / unverified /
reject_patterns / 弱别名；保密一级来源只出条款号、标题、方法标准与清单对照并标 cloud_generate=false；
已删除项不出现；不带 .insights / .krow / 合同双方称谓。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KNOW = ROOT / "docs" / "knowledge"
PUB = KNOW / "published"
LEX = ROOT / "docs" / "clause_lexicon.json"
EXPORT = KNOW / "export"

BUNDLE_ID = "electrical-xcm-clauses"
SPACE = "electrical"
PACK_ID = "electrical"
LIST_TITLE = "电机控制需求清单 20260821V1"

ENTITY_TYPES = ("CLAUSE", "PHYSICS_LAW", "STD_CLAUSE", "TERM")
RELATION_TYPES = ("related", "not", "same_slot", "interprets", "verifies", "term_of")
UI_GROUPING = {
    "CLAUSE": "清单条目",
    "PHYSICS_LAW": "物理关系",
    "STD_CLAUSE": "企标条款",
    "TERM": "术语",
}
DETECTION_KEYWORDS = [
    "电机控制器", "逆变器", "电控", "DPR", "XCM", "MCU", "Inverter", "PEU",
    "耐电压", "绝缘电阻", "主动短路", "ASC", "升压", "Boost", "P1", "P3",
    "相电流", "母线电压", "开关频率", "冷却液",
]
# SDK DomainPackManifest 只认这些键；多一个编译器直接拒绝写出
MANIFEST_ALLOWED_KEYS = frozenset(
    {
        "id", "display_name", "description", "version",
        "entity_kinds_extend", "relation_kinds_extend", "detection_keywords", "ui_grouping",
    }
)

# 分类 SSOT：清单「分组」→ 功能域。order 即侧栏顺序（按清单出现顺序）。
TAXONOMY: tuple[tuple[str, str], ...] = (
    ("scope", "设计范围"),
    ("hv_dc", "直流高压"),
    ("hv_safety", "高压安全"),
    ("lv", "低压"),
    ("p1", "P1"),
    ("p3", "P3"),
    ("boost", "升压"),
    ("cooling", "冷却"),
    ("environment", "环境与材料"),
    ("sensing_control", "采样与控制"),
    ("assembly", "整机"),
    ("safety_function", "安全与功能"),
)
_CAT_BY_LABEL = {label: (cid, order + 1) for order, (cid, label) in enumerate(TAXONOMY)}

_PRIVATE_FIELDS = ("notes", "split_harm", "unverified", "reject_patterns", "weak_aliases")
_LEAK = re.compile(r"\.insights|\.krow|AGENTS\.md|甲方|乙方|8000\s*小时|通常\s*15\s*年")


def _legacy():
    """复用 export_kb_bundle 的加载、清洗与泄漏检查，两条产物线共用同一套守门。"""
    path = ROOT / "scripts" / "export_kb_bundle.py"
    spec = importlib.util.spec_from_file_location("export_kb_bundle", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _clean(items: object) -> list[str]:
    return [str(x).strip() for x in (items or []) if str(x).strip()]


def _category(group: str) -> dict:
    label = (group or "").strip()
    if label not in _CAT_BY_LABEL:
        raise SystemExit(f"清单分组「{label}」不在 TAXONOMY 里；分类是封闭集合，先补 compile_kb_bundle.TAXONOMY")
    cid, order = _CAT_BY_LABEL[label]
    return {"id": cid, "label": label, "order": order, "basis": "list_group", "signals": [f"list:{label}"]}


def _identity() -> dict:
    return {"resolution": "distinct", "decided_by": "rule", "rules_fired": ["list_seq_unique"]}


def _definition_text(*parts: str) -> str:
    """词条定义只用来自当份卡片的原词，不另写。"""
    seen: list[str] = []
    for raw in parts:
        text = " ".join(str(raw or "").split())
        if text and text not in seen:
            seen.append(text)
    return "；".join(seen)


def _clause_entity(row: dict, version: str, retrieve_seqs: set[int]) -> dict:
    seq = int(row["seq"])
    name = str(row.get("name") or "").strip()
    src = f"{LIST_TITLE} #{seq}"
    names = [{"text": name, "ns": "list_name", "src": src, "evidence": "list"}]
    for alias in _clean(row.get("aliases")):
        names.append({"text": alias, "ns": "alias_strong", "src": "clause_lexicon", "evidence": "lexicon"})
    retrieve = seq in retrieve_seqs
    if retrieve:
        for alias in _clean(row.get("retrieve_aliases")):
            names.append({"text": alias, "ns": "alias_retrieve", "src": "clause_lexicon", "evidence": "lexicon"})
    category = _category(row.get("group") or "")
    gloss = (row.get("gloss") or "").strip()
    definition = _definition_text(gloss)
    return {
        "id": f"clause:{seq}",
        "type": "CLAUSE",
        "name": name,
        "label": name,
        "definition": definition,
        "names": names,
        "uuids": [],
        "identity": _identity(),
        "category": category,
        "data": {
            "seq": seq,
            "group": (row.get("group") or "").strip(),
            "gloss": gloss,
            "definition": definition,
            "category": category,
            "unit_cues": _clean(row.get("unit_cues")),
            "exclude": _clean(row.get("exclude")),
            "std": _clean(row.get("std")),
            "see_seq": [int(x) for x in (row.get("see") or [])],
            "status": str(row.get("status") or "draft"),
            "retrieve": retrieve,
            "conflict": (row.get("conflict") or "").strip(),
            "source": f"{src}；知识库 {version}",
            "classification": "内部",
            "fill_from_kb": False,
            "leave_site": False,
            "cloud_generate": True,
            "knowledge_version": version,
        },
    }


def _physics_entity(card: dict, version: str) -> dict:
    cid = str(card.get("id") or "").strip()
    title = str(card.get("title") or cid).strip()
    law = (card.get("law") or "").strip()
    gloss = (card.get("gloss") or "").strip()
    definition = _definition_text(gloss, law)
    return {
        "id": f"physics:{cid}",
        "type": "PHYSICS_LAW",
        "name": title,
        "label": title,
        "definition": definition,
        "names": [{"text": title, "ns": "physics", "src": "docs/knowledge/physics.yaml", "evidence": "card"}],
        "uuids": [],
        "identity": _identity(),
        "data": {
            "law": law,
            "gloss": gloss,
            "definition": definition,
            "derive": bool(card.get("derive")),
            "fill": False,
            "see_seq": [int(x) for x in (card.get("see_seq") or [])],
            "source": f"电机控制器物理关系 {cid}；知识库 {version}",
            "classification": "内部",
            "fill_from_kb": False,
            "leave_site": False,
            "cloud_generate": True,
            "knowledge_version": version,
        },
    }


def _enterprise_entities(enterprise: dict, version: str) -> list[dict]:
    std_id = str(enterprise.get("std_id") or "").strip()
    if not std_id:
        return []
    classification = str(enterprise.get("classification") or "内部")
    secret = classification != "内部"
    out: list[dict] = []
    for clause in enterprise.get("clauses") or []:
        cid = str(clause.get("id") or "").strip()
        if not cid:
            continue
        title = f"{std_id} {cid} {clause.get('title') or ''}".strip()
        data = {
            "std_id": std_id,
            "clause": cid,
            "kind": str(clause.get("kind") or ""),
            "method_std": _clean(clause.get("method_std")),
            "see_seq": [int(x) for x in (clause.get("see_seq") or [])],
            "source": f"{std_id} {cid}；知识库 {version}",
            "classification": classification,
            "fill_from_kb": False,
            "leave_site": False,
            "cloud_generate": not secret,
            "knowledge_version": version,
        }
        if not secret:
            data["gloss"] = (clause.get("gloss") or "").strip()
            data["look_in_dpr"] = _clean(clause.get("look_in_dpr"))
        definition = _definition_text(data.get("gloss") or "")
        data["definition"] = definition
        out.append(
            {
                "id": f"std:{cid}",
                "type": "STD_CLAUSE",
                "name": title,
                "label": title,
                "definition": definition,
                "names": [{"text": title, "ns": "std_clause", "src": std_id, "evidence": "standard"}],
                "uuids": [],
                "identity": _identity(),
                "data": data,
            }
        )
    for term in enterprise.get("terms") or []:
        name = str(term.get("name") or "").strip()
        if not name:
            continue
        data = {
            "std_id": std_id,
            "see_seq": [int(x) for x in (term.get("see_seq") or [])],
            "source": f"{std_id} 第3章；知识库 {version}",
            "classification": classification,
            "fill_from_kb": False,
            "leave_site": False,
            "cloud_generate": not secret,
            "knowledge_version": version,
        }
        if not secret:
            data["gloss"] = (term.get("gloss") or "").strip()
        definition = _definition_text(data.get("gloss") or "")
        data["definition"] = definition
        out.append(
            {
                "id": f"term:{name}",
                "type": "TERM",
                "name": name,
                "label": name,
                "definition": definition,
                "names": [{"text": name, "ns": "std_term", "src": f"{std_id} 第3章", "evidence": "standard"}],
                "uuids": [],
                "identity": _identity(),
                "data": data,
            }
        )
    return out


def _relation(rel: str, src: str, dst: str) -> dict:
    """治理台 Bundle 认 source_id / target_id / relation_type；from / to / type 留给本仓闸门。"""
    return {
        "id": f"rel:{rel}:{src}->{dst}",
        "type": rel,
        "relation_type": rel,
        "from": src,
        "to": dst,
        "source_id": src,
        "target_id": dst,
        "data": {"basis": "published_graph"},
    }


def _first_plain_paragraph(markdown: str) -> str:
    for line in (markdown or "").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or text.startswith("---") or text.startswith("- "):
            continue
        return text
    return ""


def _wiki_page(page: dict, definition: str = "") -> dict:
    """治理台 wiki 页认 body / markdown / source_id；摘要用当份 definition。"""
    out = dict(page)
    body = out.get("content") or ""
    out["body"] = body
    out["markdown"] = body
    out["source_id"] = out.get("entity_id") or out.get("id") or ""
    summary = (definition or "").strip() or _first_plain_paragraph(body)
    out["summary"] = summary
    out["definition"] = summary
    return out


def _relations(graph: dict, entities: list[dict], dropped: set[int]) -> list[dict]:
    ids = {e["id"] for e in entities}
    out: dict[str, dict] = {}
    for edge in graph.get("edges") or []:
        rel = str(edge.get("rel") or "")
        src, dst = str(edge.get("from") or ""), str(edge.get("to") or "")
        if rel not in RELATION_TYPES or src not in ids or dst not in ids:
            continue
        r = _relation(rel, src, dst)
        out[r["id"]] = r
    for ent in entities:
        if ent["type"] == "STD_CLAUSE":
            rel = "verifies"
        elif ent["type"] == "TERM":
            rel = "term_of"
        else:
            continue
        for seq in ent["data"].get("see_seq") or []:
            dst = f"clause:{int(seq)}"
            if int(seq) in dropped or dst not in ids:
                continue
            r = _relation(rel, ent["id"], dst)
            r["data"]["basis"] = "enterprise_see_seq"
            out[r["id"]] = r
    return [out[k] for k in sorted(out)]


def _clause_page(ent: dict, by_id: dict[str, dict], version: str) -> dict:
    d = ent["data"]
    seq = d["seq"]
    lines = [
        "---",
        f"title: \"#{seq} {ent['name']}\"",
        f"category: {ent['category']['id']}",
        f"seq: {seq}",
        f"knowledge_version: {version}",
        "---",
        "",
        f"# #{seq} {ent['name']}",
        "",
    ]
    if ent.get("definition") or d.get("gloss"):
        lines += [str(ent.get("definition") or d.get("gloss") or "").strip(), ""]
    lines += [
        f"- 分组：{d['group']}（{ent['category']['id']}）",
        f"- 状态：{d['status']}" + ("，已开通选段检索" if d["retrieve"] else ""),
    ]
    if d["gloss"]:
        lines.append(f"- 释义：{d['gloss']}")
    if d["unit_cues"]:
        lines.append("- 单位形态：" + "；".join(d["unit_cues"]))
    strong = [n["text"] for n in ent["names"] if n["ns"] == "alias_strong"]
    if strong:
        lines += ["", "## 规格常见写法（强别名）", "", "、".join(strong)]
    if d["exclude"]:
        lines += ["", "## 不得配入本条", ""] + [f"- {x}" for x in d["exclude"]]
    if d["see_seq"]:
        lines += ["", "## 参见", ""]
        for s in d["see_seq"]:
            other = by_id.get(f"clause:{s}")
            lines.append(f"- [#{s} {other['name']}](clause-{s})" if other else f"- #{s}")
    if d["std"]:
        lines += ["", "## 试验方法对照", ""] + [f"- {x}" for x in d["std"]]
    lines += [
        "",
        "## 使用边界",
        "",
        "抽出值只来自当份规格书；本条只提供条目号、释义、别名与出处，不提供取值。",
        f"出处：{d['source']}",
        "",
    ]
    return {
        "id": f"wikipage:{SPACE}/clause-{seq}",
        "title": f"#{seq} {ent['name']}",
        "entity_id": ent["id"],
        "page_type": "entity",
        "tier": "entity",
        "category": ent["category"]["id"],
        "content": "\n".join(lines),
    }


def _index_page(entities: list[dict], version: str) -> dict:
    clauses = [e for e in entities if e["type"] == "CLAUSE"]
    lines = [
        "---",
        f"title: \"{LIST_TITLE} 条目索引\"",
        f"knowledge_version: {version}",
        "---",
        "",
        f"# {LIST_TITLE} 条目索引",
        "",
        f"共 {len(clauses)} 条，按分组列出。抽出值只来自当份规格书；本索引与各条目页只提供条目号与出处。",
    ]
    for cid, label in TAXONOMY:
        rows = [e for e in clauses if e["category"]["id"] == cid]
        if not rows:
            continue
        lines += ["", f"## {label}", ""]
        lines += [f"- [#{e['data']['seq']} {e['name']}](clause-{e['data']['seq']})" for e in rows]
    lines.append("")
    return {
        "id": f"wikipage:{SPACE}/index",
        "title": f"{LIST_TITLE} 条目索引",
        "page_type": "essay",
        "tier": "essay",
        "content": "\n".join(lines),
    }


def _physics_page(entities: list[dict], version: str) -> dict:
    laws = [e for e in entities if e["type"] == "PHYSICS_LAW"]
    lines = [
        "---",
        "title: \"电机控制器物理关系\"",
        f"knowledge_version: {version}",
        "---",
        "",
        "# 电机控制器物理关系",
        "",
        "只用于读表与校验。标「可推算」的关系，只在当份规格书已出现输入量时按公式推算缺项并标局部对应；其余不得推算取值。",
        "",
        "| 关系 | 公式 | 可推算 | 解释清单条目 |",
        "|---|---|---|---|",
    ]
    for e in laws:
        d = e["data"]
        see = "、".join(f"#{s}" for s in d["see_seq"]) or "—"
        lines.append(f"| {e['name']} | {d['law'] or '—'} | {'是' if d['derive'] else '否'} | {see} |")
    lines.append("")
    return {
        "id": f"wikipage:{SPACE}/physics",
        "title": "电机控制器物理关系",
        "page_type": "essay",
        "tier": "essay",
        "content": "\n".join(lines),
    }


def domain_pack_manifest(version: str) -> dict:
    manifest = {
        "id": PACK_ID,
        "display_name": "电机控制器条款知识包",
        "description": (
            f"XCM 电控前期设计输入清单 116 条认条词典、物理关系与企标试验条款对照；"
            f"确定性编译，不提供取值。知识库 {version}"
        ),
        "version": "1.0.0",
        "entity_kinds_extend": list(ENTITY_TYPES),
        "relation_kinds_extend": list(RELATION_TYPES),
        "detection_keywords": list(DETECTION_KEYWORDS),
        "ui_grouping": dict(UI_GROUPING),
    }
    extra = set(manifest) - MANIFEST_ALLOWED_KEYS
    if extra:
        raise RuntimeError(f"domain_pack manifest 含 SDK 不认的键：{sorted(extra)}")
    return manifest


def build_bundle(now: datetime | None = None) -> dict:
    legacy = _legacy()
    manifest = legacy._load_json(PUB / "manifest.json")
    graph = legacy._load_json(PUB / "graph.json")
    lex = legacy._load_json(LEX)
    version = str(manifest.get("version") or "").strip()
    if not version:
        raise SystemExit("manifest.json 缺少 version")
    if manifest.get("fill_from_kb") is not False or manifest.get("leave_site") is not False:
        raise SystemExit("manifest 必须 fill_from_kb=false 且 leave_site=false")
    lex_version = str((lex.get("meta") or {}).get("knowledge_version") or "").strip()
    if lex_version and lex_version != version:
        raise SystemExit(f"clause_lexicon.json 版本 {lex_version} 与 manifest {version} 不一致，先重新发布")

    dropped = {int(x) for x in (manifest.get("dropped_seqs") or [])}
    retrieve_seqs = {int(x) for x in (manifest.get("retrieve_seqs") or [])}
    frames = [row for row in (lex.get("frames") or []) if int(row["seq"]) not in dropped]

    entities: list[dict] = [_clause_entity(row, version, retrieve_seqs) for row in frames]
    entities.extend(_physics_entity(card, version) for card in (manifest.get("physics_cards") or []))
    entities.extend(_enterprise_entities(manifest.get("enterprise") or {}, version))
    relations = _relations(graph, entities, dropped)

    by_id = {e["id"]: e for e in entities}
    wiki_pages = [
        _wiki_page(_clause_page(e, by_id, version), e.get("definition") or "")
        for e in entities
        if e["type"] == "CLAUSE"
    ]
    wiki_pages.append(_wiki_page(_index_page(entities, version)))
    wiki_pages.append(_wiki_page(_physics_page(entities, version)))

    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    stats = {t: sum(1 for e in entities if e["type"] == t) for t in ENTITY_TYPES}
    stats["relations"] = len(relations)
    stats["wiki_pages"] = len(wiki_pages)
    stats["uncategorized"] = 0
    bundle = {
        "id": BUNDLE_ID,
        "version": stamp,
        "space": SPACE,
        "meta": {
            "knowledge_version": version,
            "compiler": "electrical-krow/scripts/compile_kb_bundle.py（确定性，零 LLM）",
            "generated_from": "docs/knowledge/published + docs/clause_lexicon.json",
            "list": LIST_TITLE,
            "citation": manifest.get("citation") or {},
            "domain_pack": PACK_ID,
            "compile_policy": "off",
            "fill_from_kb": False,
            "leave_site": False,
            "retrieve_seqs": sorted(retrieve_seqs),
            "dropped_seqs": sorted(dropped),
            "taxonomy": [
                {"id": cid, "label": label, "order": i + 1} for i, (cid, label) in enumerate(TAXONOMY)
            ],
            "taxonomy_layers": ["list_group"],
            "stats": stats,
        },
        "entities": entities,
        "relations": relations,
        "wiki_pages": wiki_pages,
    }
    validate(bundle)
    return bundle


def validate(bundle: dict) -> None:
    """结构与治理双闸。任何一条不过直接 SystemExit，不出半个包。"""
    for key in ("id", "version", "space", "meta", "entities", "relations", "wiki_pages"):
        if key not in bundle:
            raise SystemExit(f"bundle 缺顶层键 {key}")
    ids: set[str] = set()
    cat_ids = {cid for cid, _ in TAXONOMY}
    for ent in bundle["entities"]:
        if ent["id"] in ids:
            raise SystemExit(f"实体 id 重复：{ent['id']}")
        ids.add(ent["id"])
        if ent["type"] not in ENTITY_TYPES:
            raise SystemExit(f"实体类型不在领域包声明里：{ent['id']} {ent['type']}")
        for key in ("name", "names", "uuids", "identity", "data"):
            if key not in ent:
                raise SystemExit(f"实体缺字段 {key}：{ent['id']}")
        if "definition" not in ent:
            raise SystemExit(f"实体缺 definition：{ent['id']}")
        gloss = (ent["data"].get("gloss") or "").strip()
        if gloss and gloss not in (ent.get("definition") or ""):
            raise SystemExit(f"实体 definition 必须含当份 gloss：{ent['id']}")
        if ent["identity"]["resolution"] not in {"merged", "distinct", "unresolved"}:
            raise SystemExit(f"identity.resolution 非法：{ent['id']}")
        if ent["type"] == "CLAUSE":
            if ent.get("category", {}).get("id") not in cat_ids:
                raise SystemExit(f"CLAUSE 缺合法 category：{ent['id']}")
        elif "category" in ent:
            raise SystemExit(f"非 CLAUSE 实体不得带 category：{ent['id']}")
        data = ent["data"]
        if data.get("fill_from_kb") is not False or data.get("leave_site") is not False:
            raise SystemExit(f"实体治理标记不对：{ent['id']}")
        for field in _PRIVATE_FIELDS:
            if field in data:
                raise SystemExit(f"实体 data 不得含 {field}：{ent['id']}")
        if data.get("classification") != "内部":
            if data.get("cloud_generate") is not False or "gloss" in data or "look_in_dpr" in data:
                raise SystemExit(f"保密来源不得带释义且必须 cloud_generate=false：{ent['id']}")
        if any(n["ns"] == "alias_weak" for n in ent["names"]):
            raise SystemExit(f"弱别名不得导出：{ent['id']}")
    rel_ids: set[str] = set()
    for rel in bundle["relations"]:
        if rel["id"] in rel_ids:
            raise SystemExit(f"关系 id 重复：{rel['id']}")
        rel_ids.add(rel["id"])
        kind = rel.get("relation_type") or rel.get("type")
        if kind not in RELATION_TYPES:
            raise SystemExit(f"关系类型不在领域包声明里：{rel['id']}")
        for key in ("source_id", "target_id", "relation_type", "from", "to", "type"):
            if not rel.get(key):
                raise SystemExit(f"关系缺字段 {key}：{rel['id']}")
        if rel["source_id"] != rel["from"] or rel["target_id"] != rel["to"]:
            raise SystemExit(f"关系端点别名不一致：{rel['id']}")
        if rel["relation_type"] != rel["type"]:
            raise SystemExit(f"关系类型别名不一致：{rel['id']}")
        if rel["source_id"] not in ids or rel["target_id"] not in ids:
            raise SystemExit(f"关系端点不存在：{rel['id']}")
    page_ids: set[str] = set()
    for page in bundle["wiki_pages"]:
        if page["id"] in page_ids:
            raise SystemExit(f"wiki 页 id 重复：{page['id']}")
        page_ids.add(page["id"])
        if page["page_type"] not in {"entity", "essay"} or page["tier"] not in {"entity", "essay"}:
            raise SystemExit(f"wiki 页类型非法：{page['id']}")
        if page["page_type"] == "entity" and page.get("entity_id") not in ids:
            raise SystemExit(f"wiki 实体页指向不存在的实体：{page['id']}")
        if page["page_type"] == "essay" and "category" in page:
            raise SystemExit(f"独立 essay 不得带 category：{page['id']}")
        if (page.get("body") or "") != (page.get("content") or ""):
            raise SystemExit(f"wiki 页 body 与 content 不一致：{page['id']}")
        if not page.get("source_id"):
            raise SystemExit(f"wiki 页缺 source_id：{page['id']}")
    for d in ("dropped_seqs",):
        for seq in bundle["meta"].get(d) or []:
            if f"clause:{seq}" in ids:
                raise SystemExit(f"已删除条目不得出现：clause:{seq}")
    if bundle["meta"]["stats"]["uncategorized"] != 0:
        raise SystemExit("清单条目分类是封闭集合，uncategorized 必须为 0")
    blob = json.dumps(bundle, ensure_ascii=False)
    hit = _LEAK.search(blob)
    if hit:
        raise SystemExit(f"编译包含禁止外泄字段：{hit.group(0)}")


def compile_pack(out_dir: Path | None = None, now: datetime | None = None) -> Path:
    bundle = build_bundle(now)
    version = bundle["meta"]["knowledge_version"]
    target = out_dir or (EXPORT / version)
    target.mkdir(parents=True, exist_ok=True)
    (target / "bundle.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (target / "domain_pack.json").write_text(
        json.dumps(domain_pack_manifest(version), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    s = bundle["meta"]["stats"]
    print(
        f"compiled {bundle['id']} {bundle['version']} (知识库 {version}) → {target} | "
        + " ".join(f"{t}={s[t]}" for t in ENTITY_TYPES)
        + f" relations={s['relations']} wiki_pages={s['wiki_pages']} uncategorized={s['uncategorized']} | schema VALID"
    )
    return target


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="编译条款知识库为公司知识中枢轨 A bundle + 领域包 manifest")
    parser.add_argument("--out", metavar="DIR", default="", help="输出目录，默认 docs/knowledge/export/<version>")
    args = parser.parse_args(argv)
    compile_pack(Path(args.out) if args.out else None)


if __name__ == "__main__":
    main()
