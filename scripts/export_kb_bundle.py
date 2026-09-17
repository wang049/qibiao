# -*- coding: utf-8 -*-
"""把已发布的条款知识库导出成公司知识库（SimLab KB 一类）能吃的 Record / bundle。

只读 docs/knowledge/published/ 与 docs/clause_lexicon.json，不改真源，不重新发布。
产物写到 docs/knowledge/export/<version>/：

- records.jsonl        每行一条 Record：kind / title / symbol / source / content / payload（ingest 三库用）
- query_aliases.yaml   强别名与已开通选段别名；弱别名不导出

轨 A 结构化知识包（bundle.json + domain_pack.json，entities / relations / wiki_pages 契约）
由 scripts/compile_kb_bundle.py 编译，本脚本的 build_bundle() 只是 Record 视图的内存汇总，不再落盘为 bundle.json。

治理约束（导出时机器守住）：
- fill_from_kb=false、leave_site=false 写进每条 payload，下游不得用库内值填格。
- 不导出 .insights / .krow / notes / split_harm / unverified / reject_patterns。
- 保密一级来源（企标）只导出条款号、标题、方法标准与清单对照，并标 cloud_generate=false。
- 已删除项（dropped_seqs）不出现在任何产物里。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("需要 PyYAML：pip install pyyaml\n")
    raise

ROOT = Path(__file__).resolve().parents[1]
KNOW = ROOT / "docs" / "knowledge"
PUB = KNOW / "published"
LEX = ROOT / "docs" / "clause_lexicon.json"
EXPORT = KNOW / "export"

SCHEMA = "electrical-kb-bundle/0.1"
ALIAS_SCHEMA = "electrical-kb-aliases/0.1"
LIST_TITLE = "电机控制需求清单 20260821V1"

# 不得进入导出内容的内部字段与文本
_PRIVATE_FIELDS = ("notes", "split_harm", "unverified", "reject_patterns", "weak_aliases")
_LEAK = re.compile(r"\.insights|\.krow|AGENTS\.md|甲方|乙方|8000\s*小时|通常\s*15\s*年")


def _load_json(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"找不到 {path}，先运行 python scripts/publish_knowledge.py")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _clean(items: object) -> list[str]:
    return [str(x).strip() for x in (items or []) if str(x).strip()]


def _clause_content(row: dict) -> str:
    parts = [f"#{row['seq']} {row.get('name') or ''}".strip()]
    if (row.get("group") or "").strip():
        parts.append(f"分组：{row['group'].strip()}")
    if (row.get("gloss") or "").strip():
        parts.append(f"释义：{row['gloss'].strip()}")
    cues = _clean(row.get("unit_cues"))
    if cues:
        parts.append("单位形态：" + "；".join(cues))
    aliases = _clean(row.get("aliases"))
    if aliases:
        parts.append("强别名：" + "、".join(aliases))
    exclude = _clean(row.get("exclude"))
    if exclude:
        parts.append("排除：" + "；".join(exclude))
    std = _clean(row.get("std"))
    if std:
        parts.append("试验方法对照：" + "；".join(std))
    see = [int(x) for x in (row.get("see") or [])]
    if see:
        parts.append("参见：" + "、".join(f"#{n}" for n in see))
    parts.append("抽出值只来自当份规格书；本条只提供条目号与出处，不提供取值。")
    return "\n".join(parts)


def _clause_record(row: dict, version: str, retrieve_seqs: set[int]) -> dict:
    seq = int(row["seq"])
    status = str(row.get("status") or "draft")
    retrieve = seq in retrieve_seqs
    return {
        "kind": "clause",
        "title": f"#{seq} {row.get('name') or ''}".strip(),
        "symbol": str(seq),
        "source": f"{LIST_TITLE} #{seq}；知识库 {version}",
        "content": _clause_content(row),
        "payload": {
            "id": f"clause:{seq}",
            "seq": seq,
            "group": row.get("group") or "",
            "status": status,
            "retrieve": retrieve,
            "conflict": row.get("conflict") or "",
            "see_seq": [int(x) for x in (row.get("see") or [])],
            "aliases_strong": _clean(row.get("aliases")),
            "aliases_retrieve": _clean(row.get("retrieve_aliases")) if retrieve else [],
            "exclude": _clean(row.get("exclude")),
            "std": _clean(row.get("std")),
            "classification": "内部",
            "fill_from_kb": False,
            "leave_site": False,
            "cloud_generate": True,
            "knowledge_version": version,
        },
    }


def _physics_record(card: dict, version: str) -> dict:
    cid = str(card.get("id") or "").strip()
    title = str(card.get("title") or cid)
    see = [int(x) for x in (card.get("see_seq") or [])]
    parts = [title]
    if (card.get("law") or "").strip():
        parts.append(f"关系：{card['law'].strip()}")
    if (card.get("gloss") or "").strip():
        parts.append(f"说明：{card['gloss'].strip()}")
    if see:
        parts.append("解释清单：" + "、".join(f"#{n}" for n in see))
    parts.append(
        "只用于读表与校验；"
        + ("当份已出现输入量时可按公式推算缺项并标局部对应。" if card.get("derive") else "不得推算取值。")
    )
    return {
        "kind": "physics",
        "title": title,
        "symbol": cid,
        "source": f"电机控制器物理关系 {cid}；知识库 {version}",
        "content": "\n".join(parts),
        "payload": {
            "id": f"physics:{cid}",
            "law": card.get("law") or "",
            "derive": bool(card.get("derive")),
            "see_seq": see,
            "classification": "内部",
            "fill_from_kb": False,
            "leave_site": False,
            "cloud_generate": True,
            "knowledge_version": version,
        },
    }


def _enterprise_records(enterprise: dict, version: str) -> list[dict]:
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
        see = [int(x) for x in (clause.get("see_seq") or [])]
        methods = _clean(clause.get("method_std"))
        parts = [f"{std_id} {cid} {clause.get('title') or ''}".strip()]
        if methods:
            parts.append("方法标准：" + "、".join(methods))
        if see:
            parts.append("对照清单：" + "、".join(f"#{n}" for n in see))
        if not secret:
            if (clause.get("gloss") or "").strip():
                parts.append(f"说明：{clause['gloss'].strip()}")
            look = _clean(clause.get("look_in_dpr"))
            if look:
                parts.append("当份 DPR 查看：" + "；".join(look))
        parts.append("只提供试验方法与认条对照；评价与抽出值看当份 DPR。")
        out.append(
            {
                "kind": "enterprise_std",
                "title": f"{std_id} {cid} {clause.get('title') or ''}".strip(),
                "symbol": f"{std_id} {cid}",
                "source": f"{std_id} {cid}；知识库 {version}",
                "content": "\n".join(parts),
                "payload": {
                    "id": f"std:{cid}",
                    "std_id": std_id,
                    "clause": cid,
                    "kind": str(clause.get("kind") or ""),
                    "method_std": methods,
                    "see_seq": see,
                    "classification": classification,
                    "fill_from_kb": False,
                    "leave_site": False,
                    "cloud_generate": not secret,
                    "knowledge_version": version,
                },
            }
        )
    for term in enterprise.get("terms") or []:
        name = str(term.get("name") or "").strip()
        if not name:
            continue
        see = [int(x) for x in (term.get("see_seq") or [])]
        parts = [f"{std_id} 定义：{name}"]
        if not secret and (term.get("gloss") or "").strip():
            parts.append(term["gloss"].strip())
        if see:
            parts.append("对照清单：" + "、".join(f"#{n}" for n in see))
        out.append(
            {
                "kind": "enterprise_term",
                "title": f"{std_id} 定义 {name}",
                "symbol": name,
                "source": f"{std_id} 第3章；知识库 {version}",
                "content": "\n".join(parts),
                "payload": {
                    "id": f"term:{name}",
                    "std_id": std_id,
                    "see_seq": see,
                    "classification": classification,
                    "fill_from_kb": False,
                    "leave_site": False,
                    "cloud_generate": not secret,
                    "knowledge_version": version,
                },
            }
        )
    return out


def _aliases(frames: list[dict], retrieve_seqs: set[int], version: str) -> dict:
    """强别名 → hint；已开通选段的 retrieve_aliases → retrieve。弱别名不导出。"""
    rows: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for row in frames:
        seq = int(row["seq"])
        symbol = str(seq)
        pairs = [(alias, "hint") for alias in _clean(row.get("aliases"))]
        if seq in retrieve_seqs:
            pairs.extend((alias, "retrieve") for alias in _clean(row.get("retrieve_aliases")))
        for alias, kind in pairs:
            key = (alias, symbol, kind)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"alias": alias, "symbol": symbol, "kind": kind})
    rows.sort(key=lambda r: (int(r["symbol"]), r["kind"], r["alias"]))
    return {
        "schema": ALIAS_SCHEMA,
        "knowledge_version": version,
        "target_kind": "clause",
        "rule": (
            "hint：强别名，整词、跨条目唯一，可直接计分；"
            "retrieve：已开通选段的条目别名，允许参与选段召回；"
            "弱别名与裸词不导出，不得由下游补回。"
        ),
        "aliases": rows,
    }


def _check_no_leak(records: list[dict]) -> None:
    for rec in records:
        blob = json.dumps(rec, ensure_ascii=False)
        hit = _LEAK.search(blob)
        if hit:
            raise SystemExit(f"导出内容含禁止外泄字段：{rec.get('title')} → {hit.group(0)}")
        for field in _PRIVATE_FIELDS:
            if field in (rec.get("payload") or {}):
                raise SystemExit(f"导出 payload 不得含 {field}：{rec.get('title')}")


def build_bundle() -> dict:
    manifest = _load_json(PUB / "manifest.json")
    graph = _load_json(PUB / "graph.json")
    lex = _load_json(LEX)
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

    records: list[dict] = [_clause_record(row, version, retrieve_seqs) for row in frames]
    records.extend(_physics_record(card, version) for card in (manifest.get("physics_cards") or []))
    records.extend(_enterprise_records(manifest.get("enterprise") or {}, version))
    _check_no_leak(records)

    nodes = [n for n in (graph.get("nodes") or []) if int(n.get("seq") or 0) not in dropped]
    edges = [
        e
        for e in (graph.get("edges") or [])
        if not any(f"clause:{d}" in (e.get("from"), e.get("to")) for d in dropped)
    ]
    aliases = _aliases(frames, retrieve_seqs, version)
    return {
        "schema": SCHEMA,
        "knowledge_version": version,
        "generated_from": "docs/knowledge/published + docs/clause_lexicon.json",
        "fill_from_kb": False,
        "leave_site": False,
        "citation": manifest.get("citation") or {},
        "retrieve_seqs": sorted(retrieve_seqs),
        "dropped_seqs": sorted(dropped),
        "records": records,
        "graph": {"nodes": nodes, "edges": edges},
        "aliases": aliases,
    }


def export(out_dir: Path | None = None) -> Path:
    bundle = build_bundle()
    version = bundle["knowledge_version"]
    target = out_dir or (EXPORT / version)
    target.mkdir(parents=True, exist_ok=True)
    with (target / "records.jsonl").open("w", encoding="utf-8") as fh:
        for rec in bundle["records"]:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    (target / "query_aliases.yaml").write_text(
        yaml.safe_dump(bundle["aliases"], allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    kinds: dict[str, int] = {}
    for rec in bundle["records"]:
        kinds[rec["kind"]] = kinds.get(rec["kind"], 0) + 1
    print(
        f"exported {version} → {target} | records={len(bundle['records'])} {kinds} | "
        f"aliases={len(bundle['aliases']['aliases'])} | edges={len(bundle['graph']['edges'])}"
    )
    return target


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="导出条款知识库为 Record / bundle")
    parser.add_argument("--out", metavar="DIR", default="", help="输出目录，默认 docs/knowledge/export/<version>")
    args = parser.parse_args(argv)
    export(Path(args.out) if args.out else None)


if __name__ == "__main__":
    main()
