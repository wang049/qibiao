# -*- coding: utf-8 -*-
"""发布电控条款知识库：卡片 → 关键词索引 + 图谱 + 版本快照。

未在 registry.published_retrieve 中的条目不进选段检索。
物理卡片只连边，不提供抽出值。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("需要 PyYAML：pip install pyyaml\n")
    raise

ROOT = Path(__file__).resolve().parents[1]
KNOW = ROOT / "docs" / "knowledge"
JSON_PATH = ROOT / "docs" / "clause_lexicon.json"
PUB = KNOW / "published"
REL = KNOW / "releases"


def _load_builder():
    path = Path(__file__).with_name("build_clause_lexicon.py")
    spec = importlib.util.spec_from_file_location("build_clause_lexicon", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"找不到 {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"找不到 {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _fold(text: str) -> str:
    return re.sub(r"[\s,，;；~～\-—–]", "", (text or "")).lower()


def _keyword_index(frames: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for row in frames:
        seq = int(row["seq"])
        name = str(row.get("name") or "")
        retrieve = bool(row.get("retrieve"))
        pairs = [(alias, "strong") for alias in row.get("aliases") or []]
        pairs.append((name, "name"))
        if retrieve:
            pairs.extend((alias, "retrieve") for alias in row.get("retrieve_aliases") or [])
        for alias, kind in pairs:
            key = _fold(str(alias))
            if len(key) < 2:
                continue
            bucket = index.setdefault(key, [])
            hit = {"seq": seq, "name": name, "kind": kind, "retrieve": retrieve}
            if hit not in bucket:
                bucket.append(hit)
    return dict(sorted(index.items(), key=lambda item: item[0]))


def _graph(frames: list[dict], physics: dict) -> dict:
    nodes = [
        {
            "id": f"clause:{row['seq']}",
            "seq": row["seq"],
            "name": row.get("name") or "",
            "group": row.get("group") or "",
            "conflict": row.get("conflict") or "",
        }
        for row in frames
    ]
    edges: list[dict] = []
    seen: set[tuple] = set()

    def add_edge(src: str, dst: str, rel: str) -> None:
        key = (src, dst, rel)
        if src == dst or key in seen:
            return
        seen.add(key)
        edges.append({"from": src, "to": dst, "rel": rel})

    conflict_groups: dict[str, list[int]] = {}
    for row in frames:
        seq = int(row["seq"])
        src = f"clause:{seq}"
        for other in row.get("see") or []:
            add_edge(src, f"clause:{int(other)}", "related")
        for raw in row.get("exclude") or []:
            found = re.findall(r"#(\d+)", str(raw))
            for num in found:
                add_edge(src, f"clause:{int(num)}", "not")
        group = str(row.get("conflict") or "").strip()
        if group:
            conflict_groups.setdefault(group, []).append(seq)
    for seqs in conflict_groups.values():
        uniq = sorted(set(seqs))
        for i, left in enumerate(uniq):
            for right in uniq[i + 1 :]:
                add_edge(f"clause:{left}", f"clause:{right}", "same_slot")
                add_edge(f"clause:{right}", f"clause:{left}", "same_slot")

    phys_nodes = []
    for card in physics.get("cards") or []:
        cid = str(card.get("id") or "").strip()
        if not cid:
            continue
        if card.get("fill") is not False:
            raise SystemExit(f"物理卡片 {cid} 必须 fill: false")
        nid = f"physics:{cid}"
        phys_nodes.append(
            {
                "id": nid,
                "title": card.get("title") or cid,
                "law": card.get("law") or "",
                "fill": False,
                "derive": bool(card.get("derive")),
            }
        )
        for seq in card.get("see_seq") or []:
            add_edge(nid, f"clause:{int(seq)}", "interprets")
    nodes.extend(phys_nodes)
    return {"nodes": nodes, "edges": edges}


_ENTERPRISE_FILL_LEAK = re.compile(r"8000\s*小时|通常\s*15\s*年")
_PROCESS_COPY = re.compile(
    r"将正式名|甲方将本条正式名|现为\s*#\d+\s*正式名|原充电升压"
)


def _assert_no_process_copy(frames: list[dict]) -> None:
    """条款卡给对表的人看：写当前语义，不写改名过程。"""
    for row in frames:
        seq = row.get("seq")
        parts = [
            str(row.get("gloss") or ""),
            str(row.get("split_harm") or ""),
            *[str(x) for x in (row.get("notes") or [])],
        ]
        blob = "\n".join(parts)
        hit = _PROCESS_COPY.search(blob)
        if hit:
            raise SystemExit(f"#{seq} 卡片不要写改名过程（{hit.group(0)}）")


def _enterprise_cite_parts(clause: dict) -> str:
    cid = str(clause.get("id") or "").strip()
    methods = [str(x).strip() for x in (clause.get("method_std") or []) if str(x).strip()]
    if not cid:
        return ""
    if methods:
        return f"{cid}→{'、'.join(methods)}"
    return cid


def _apply_enterprise_std(
    frames: list[dict], enterprise: dict, dropped: set[int] | None = None
) -> dict:
    """把企标条款号和方法标准挂到清单 std 栏。禁止把企标当成抽出值来源。"""
    skip = dropped or set()
    if not enterprise:
        raise SystemExit("找不到 docs/knowledge/enterprise_std.yaml")
    if enterprise.get("fill") is not False:
        raise SystemExit("企标卡片必须 fill: false")
    blob = json.dumps(enterprise, ensure_ascii=False)
    leak = _ENTERPRISE_FILL_LEAK.search(blob)
    if leak:
        raise SystemExit(f"企标卡片含禁止写入抽出值的举例口径：{leak.group(0)}")
    std_id = str(enterprise.get("std_id") or "").strip()
    if not std_id:
        raise SystemExit("企标卡片缺少 std_id")
    by_seq: dict[int, list[dict]] = {}
    public_clauses: list[dict] = []
    for clause in enterprise.get("clauses") or []:
        if clause.get("fill") is True:
            raise SystemExit(f"企标条款 {clause.get('id')} 不得 fill: true")
        cid = str(clause.get("id") or "").strip()
        see_seq = [int(x) for x in (clause.get("see_seq") or [])]
        for seq in see_seq:
            if seq < 1 or seq > 120:
                raise SystemExit(f"企标 {cid} 的 see_seq 超出 1–120：{seq}")
            if seq in skip:
                raise SystemExit(f"企标 {cid} 的 see_seq 指向已删除项：#{seq}")
            by_seq.setdefault(seq, []).append(clause)
        public_clauses.append(
            {
                "id": cid,
                "title": str(clause.get("title") or cid),
                "kind": str(clause.get("kind") or ""),
                "method_std": [str(x).strip() for x in (clause.get("method_std") or []) if str(x).strip()],
                "gloss": str(clause.get("gloss") or "").strip(),
                "look_in_dpr": [str(x).strip() for x in (clause.get("look_in_dpr") or []) if str(x).strip()],
                "see_seq": see_seq,
                "fill": False,
            }
        )
    frame_by = {int(row["seq"]): row for row in frames}
    for seq, clauses in by_seq.items():
        row = frame_by.get(seq)
        if not row:
            raise SystemExit(f"企标 see_seq 对不上清单：#{seq}")
        parts = [p for p in (_enterprise_cite_parts(c) for c in clauses) if p]
        cite = f"{std_id} {'；'.join(parts)}"
        existing = [str(x).strip() for x in (row.get("std") or []) if str(x).strip()]
        row["std"] = [cite] + [item for item in existing if item != cite]
    public_terms = []
    for term in enterprise.get("terms") or []:
        if term.get("fill") is True:
            raise SystemExit(f"企标定义 {term.get('name')} 不得 fill: true")
        public_terms.append(
            {
                "name": str(term.get("name") or "").strip(),
                "gloss": str(term.get("gloss") or "").strip(),
                "see_seq": [int(x) for x in (term.get("see_seq") or [])],
                "fill": False,
            }
        )
    return {
        "std_id": std_id,
        "title": str(enterprise.get("title") or std_id),
        "classification": str(enterprise.get("classification") or "内部"),
        "coverage": str(enterprise.get("coverage") or "").strip(),
        "rule": str(enterprise.get("rule") or "").strip(),
        "fill": False,
        "terms": public_terms,
        "clauses": public_clauses,
    }


def _apply_registry(frames: list[dict], registry: dict) -> list[int]:
    allowed = {int(x) for x in (registry.get("published_retrieve") or [])}
    for row in frames:
        seq = int(row["seq"])
        row["retrieve"] = seq in allowed
        if seq not in allowed:
            row["retrieve_aliases"] = []
        row["status"] = "published" if seq in allowed else str(
            registry.get("default_status") or "draft"
        )
        if seq in {int(x) for x in (registry.get("confirmed") or [])}:
            row["status"] = "confirmed" if seq not in allowed else "published"
    return sorted(allowed)


def publish() -> dict:
    builder = _load_builder()
    catalog = _read_yaml(KNOW / "catalog.yaml")
    registry = _read_yaml(KNOW / "registry.yaml")
    physics = _read_yaml(KNOW / "physics.yaml")
    enterprise = _read_yaml(KNOW / "enterprise_std.yaml")
    payload = yaml.safe_load(builder.YAML_PATH.read_text(encoding="utf-8"))
    dropped = builder.dropped_seqs(payload)
    frames = builder.build_frames(payload)
    expected = set(range(1, 121)) - dropped
    got = {int(row["seq"]) for row in frames}
    if got != expected:
        raise SystemExit(
            f"条目序号对不上：缺 {sorted(expected - got)} 多 {sorted(got - expected)}"
        )
    retrieve_seqs = _apply_registry(frames, registry)
    _assert_no_process_copy(frames)
    if any(seq in dropped for seq in retrieve_seqs):
        raise SystemExit(f"已删除项不得开通选段：{sorted(set(retrieve_seqs) & dropped)}")
    enterprise_pub = _apply_enterprise_std(frames, enterprise, dropped)
    for card in physics.get("cards") or []:
        for seq in card.get("see_seq") or []:
            if int(seq) in dropped:
                raise SystemExit(
                    f"物理卡片 {card.get('id')} 的 see_seq 指向已删除项：#{seq}"
                )
    version = str(registry.get("version") or date.today().isoformat())

    meta = dict(payload.get("meta") or {})
    meta["generated_from"] = "docs/clause_lexicon.yaml"
    meta["knowledge_version"] = version
    meta["retrieve"] = (
        "只开 registry.published_retrieve："
        + ",".join(f"#{n}" for n in retrieve_seqs)
        + "；弱别名不计分、不进选段"
    )
    meta["fill_from_kb"] = False
    lex = {"meta": meta, "frames": frames}
    JSON_PATH.write_text(
        json.dumps(lex, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    PUB.mkdir(parents=True, exist_ok=True)
    keyword = _keyword_index(frames)
    graph = _graph(frames, physics)
    sources = []
    for row in catalog.get("sources") or []:
        item = dict(row)
        sid = str(item.get("id") or "").strip()
        if sid == "clause-yaml":
            item["title"] = "条款词典"
        elif sid == "physics":
            item["title"] = "电机控制器物理关系"
        item["leave_site"] = False
        sources.append(item)
    citation = {
        "list": "电机控制需求清单 20260821V1",
        "knowledge_version": version,
        "rule": "抽出值只来自当份规格书；库只提供条目号与出处，不提供取值",
    }
    manifest = {
        "version": version,
        "retrieve_seqs": retrieve_seqs,
        "dropped_seqs": sorted(dropped),
        "fill_from_kb": False,
        "leave_site": False,
        "scope": catalog.get("scope") or {},
        "sources": sources,
        "citation": citation,
        "enterprise": enterprise_pub,
        "physics_cards": [
            {
                "id": c.get("id"),
                "title": c.get("title"),
                "law": c.get("law"),
                "fill": False,
                "derive": bool(c.get("derive")),
                "gloss": str(c.get("gloss") or "").strip(),
                "see_seq": [int(x) for x in (c.get("see_seq") or [])],
            }
            for c in (physics.get("cards") or [])
        ],
    }
    (PUB / "keyword_index.json").write_text(
        json.dumps(keyword, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (PUB / "graph.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (PUB / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (KNOW / "CURRENT").write_text(version + "\n", encoding="utf-8")

    snap = REL / version
    snap.mkdir(parents=True, exist_ok=True)
    shutil.copy2(JSON_PATH, snap / "clause_lexicon.json")
    for name in ("keyword_index.json", "graph.json", "manifest.json"):
        shutil.copy2(PUB / name, snap / name)
    print(
        f"published {version} | frames={len(frames)} | dropped={sorted(dropped)} | "
        f"retrieve={retrieve_seqs} | "
        f"aliases={len(keyword)} | edges={len(graph['edges'])}"
    )
    return manifest


def rollback(version: str) -> None:
    snap = REL / version.strip()
    lex = snap / "clause_lexicon.json"
    if not lex.is_file():
        raise SystemExit(f"没有该版本快照：{snap}")
    shutil.copy2(lex, JSON_PATH)
    PUB.mkdir(parents=True, exist_ok=True)
    for name in ("keyword_index.json", "graph.json", "manifest.json"):
        src = snap / name
        if src.is_file():
            shutil.copy2(src, PUB / name)
    (KNOW / "CURRENT").write_text(version.strip() + "\n", encoding="utf-8")
    print(f"rolled back to {version.strip()}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="发布或回滚电控条款知识库")
    parser.add_argument("--rollback", metavar="VERSION", default="")
    args = parser.parse_args(argv)
    if args.rollback:
        rollback(args.rollback)
        return
    publish()


if __name__ == "__main__":
    main()
