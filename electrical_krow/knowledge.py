"""已发布的条款知识库：认条、出处、图谱。禁止用库里的值填核对表。"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from electrical_krow.paths import PROJECT_ROOT

_PUB = PROJECT_ROOT / "docs" / "knowledge" / "published"
_FOLD = re.compile(r"[\s,，;；~～\-—–]")


def _fold(text: str) -> str:
    return _FOLD.sub("", (text or "")).lower()


def published_dir() -> Path:
    return _PUB


@lru_cache(maxsize=1)
def load_manifest() -> dict:
    path = _PUB / "manifest.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=1)
def load_keyword_index() -> dict[str, list[dict]]:
    path = _PUB / "keyword_index.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=1)
def load_graph() -> dict:
    path = _PUB / "graph.json"
    if not path.is_file():
        return {"nodes": [], "edges": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {"nodes": [], "edges": []}


def fill_from_kb_allowed() -> bool:
    """知识库不得提供抽出值。"""
    return False


def knowledge_version() -> str:
    """当前已发布知识库版本。未发布则空。"""
    manifest = load_manifest()
    cite = manifest.get("citation") if isinstance(manifest.get("citation"), dict) else {}
    version = str(cite.get("knowledge_version") or manifest.get("version") or "").strip()
    if version:
        return version
    lex = PROJECT_ROOT / "docs" / "clause_lexicon.json"
    if not lex.is_file():
        return ""
    try:
        data = json.loads(lex.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    meta = data.get("meta") if isinstance(data, dict) else {}
    if not isinstance(meta, dict):
        return ""
    return str(meta.get("knowledge_version") or "").strip()


def citation_for_seq(seq: int, name: str = "") -> str:
    manifest = load_manifest()
    cite = manifest.get("citation") or {}
    version = cite.get("knowledge_version") or manifest.get("version") or knowledge_version()
    listing = cite.get("list") or "电机控制需求清单"
    label = f"{listing} #{int(seq)}"
    if (name or "").strip():
        label += f" {name.strip()}"
    if version:
        label += f"；知识库 {version}"
    return label


_SHORT_LATIN = re.compile(r"^[a-z0-9]{1,4}$")


def _short_latin_hit(key: str, lowered: str) -> bool:
    """RE / CE / IR / IM / STO 这类短缩写只认整词，不认子串。"""
    return re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", lowered) is not None


def keyword_hits(text: str, *, retrieve_only: bool = False) -> list[dict]:
    """整词别名命中。retrieve_only=True 时只返回已开通选段的条目。"""
    folded = _fold(text)
    if len(folded) < 2:
        return []
    lowered = (text or "").lower()
    index = load_keyword_index()
    hits: list[dict] = []
    seen: set[int] = set()
    for key, rows in index.items():
        if len(key) < 2:
            continue
        if _SHORT_LATIN.match(key):
            if not _short_latin_hit(key, lowered):
                continue
        elif key not in folded and folded not in key:
            continue
        for row in rows:
            seq = int(row.get("seq") or 0)
            if not seq or seq in seen:
                continue
            if retrieve_only and not row.get("retrieve"):
                continue
            if retrieve_only and row.get("kind") not in {"retrieve", "strong", "name"}:
                continue
            seen.add(seq)
            hits.append(dict(row))
    return hits


def neighbors(seq: int, rel: str = "") -> list[dict]:
    nid = f"clause:{int(seq)}"
    out: list[dict] = []
    for edge in load_graph().get("edges") or []:
        if edge.get("from") != nid and edge.get("to") != nid:
            continue
        if rel and edge.get("rel") != rel:
            continue
        out.append(edge)
    return out


_STATUS_LABEL = {
    "published": "已开通检索",
    "confirmed": "已确认",
    "draft": "待确认",
}
_REL_LABEL = {
    "related": "相关",
    "not": "易混",
    "same_slot": "同一格",
    "interprets": "适用公式",
}
_REL_RANK = {"not": 0, "same_slot": 1, "interprets": 2, "related": 3}
_SOURCE_TITLE = {
    "list-120": "电机控制需求清单",
    "clause-yaml": "条款词典",
    "physics": "电机控制器物理关系",
    "enterprise-std": "企业标准",
    "manuals": "手册与过往文档",
}
_PATHISH = re.compile(
    r"(?i)(?:^|[\s「『(（])(?:docs/)?[\w./-]+\.(?:ya?ml|json|md)\b"
)
_LEX = PROJECT_ROOT / "docs" / "clause_lexicon.json"


def _scrub_text(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    replaced = raw
    for needle, label in (
        ("docs/clause_lexicon.yaml", "条款词典"),
        ("docs/clause_lexicon.json", "条款词典"),
        ("docs/knowledge/physics.yaml", "电机控制器物理关系"),
        ("docs/knowledge/catalog.yaml", "知识库目录"),
        ("docs/knowledge/registry.yaml", "发布登记"),
        ("docs/knowledge/enterprise_std.yaml", "企业标准"),
        ("clause_lexicon.yaml", "条款词典"),
        ("physics.yaml", "电机控制器物理关系"),
        ("catalog.yaml", "知识库目录"),
        ("registry.yaml", "发布登记"),
        ("enterprise_std.yaml", "企业标准"),
    ):
        replaced = replaced.replace(needle, label)
    if _PATHISH.search(replaced) or "docs/" in replaced:
        return re.sub(r"(?i)(?:docs/)?[\w./-]+\.(?:ya?ml|json|md)", "知识库条目", replaced)
    return replaced


def _scrub_party(text: str) -> str:
    """工位页不出现合同角色「甲方/乙方」。catalog 里仍可记谁提供。"""
    out = _scrub_text(text or "")
    for old, new in (
        ("甲方确认口径；乙方整理卡片与发布", "口径经确认后使用"),
        ("甲方确认口径", "口径经确认后使用"),
        ("乙方按电控常识整理，待甲方确认", "待确认"),
        ("乙方整理，待甲方确认", "待确认"),
        ("待甲方确认", "待确认"),
        ("甲方业务系统数据", "业务系统数据"),
        ("甲方材料", "当份材料"),
    ):
        out = out.replace(old, new)
    out = re.sub(r"甲方|乙方", "", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"[；;]{2,}", "；", out)
    return out.strip(" ；;·，,")


def _source_confirm_status(row: dict) -> str:
    blob = _scrub_party(
        f"{row.get('provided_by') or ''}\n{row.get('used_for') or ''}"
    )
    if re.search(r"待确认|确认前|未提供", blob):
        return "待确认"
    return "已确认"


def _public_source(row: dict) -> dict:
    sid = str(row.get("id") or "").strip()
    title = _SOURCE_TITLE.get(sid) or _scrub_party(str(row.get("title") or sid))
    if sid in {"list-120", "enterprise-std"}:
        given = _scrub_party(str(row.get("title") or ""))
        if given and "docs/" not in given and ".yaml" not in given:
            title = given
    return {
        "id": sid,
        "title": title,
        "version": str(row.get("version") or "").strip(),
        "status": _source_confirm_status(row),
        "classification": str(row.get("classification") or "内部").strip() or "内部",
        "leave_site": False,
        "used_for": _scrub_party(str(row.get("used_for") or "")),
    }


def _lexicon_frames() -> list[dict]:
    if not _LEX.is_file():
        return []
    data = json.loads(_LEX.read_text(encoding="utf-8"))
    frames = data.get("frames") if isinstance(data, dict) else []
    return frames if isinstance(frames, list) else []


def _cap_list(values: object, limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in values or []:
        text = _scrub_text(str(item or "")).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _other_id(edge: dict, nid: str) -> str:
    src = str(edge.get("from") or "")
    dst = str(edge.get("to") or "")
    if src == nid:
        return dst
    return src


@lru_cache(maxsize=1)
def browse_catalog() -> dict:
    """工位知识库界面用。不出现源文件路径，也不提供抽出值。"""
    manifest = load_manifest()
    version = str(manifest.get("version") or "").strip()
    if not version:
        return {
            "version": "",
            "fill_from_kb": False,
            "leave_site": False,
            "clauses": [],
            "physics": [],
            "enterprise": [],
            "enterprise_terms": [],
            "graph": {"nodes": [], "edges": []},
        }
    graph = load_graph()
    frames = _lexicon_frames()
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    node_by_id = {str(n.get("id") or ""): n for n in nodes if n.get("id")}
    name_by_seq = {
        int(row.get("seq") or 0): str(row.get("name") or "")
        for row in frames
        if row.get("seq")
    }
    physics_by_id: dict[str, dict] = {}
    for card in manifest.get("physics_cards") or []:
        cid = str(card.get("id") or "").strip()
        if cid:
            physics_by_id[cid] = card
    for node in nodes:
        nid = str(node.get("id") or "")
        if not nid.startswith("physics:"):
            continue
        cid = nid.split(":", 1)[1]
        physics_by_id.setdefault(cid, {})
        physics_by_id[cid].setdefault("title", node.get("title") or cid)
        physics_by_id[cid].setdefault("law", node.get("law") or "")
        physics_by_id[cid]["fill"] = False
        physics_by_id[cid].setdefault("derive", bool(node.get("derive")))

    adj: dict[str, list[dict]] = {}
    for edge in edges:
        rel = str(edge.get("rel") or "related")
        src = str(edge.get("from") or "")
        dst = str(edge.get("to") or "")
        if not src or not dst:
            continue
        item = {"from": src, "to": dst, "rel": rel}
        adj.setdefault(src, []).append(item)
        adj.setdefault(dst, []).append(item)

    def links_for(nid: str) -> list[dict]:
        ranked = sorted(
            adj.get(nid) or [],
            key=lambda e: (_REL_RANK.get(str(e.get("rel")), 9), str(e.get("to"))),
        )
        out: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for edge in ranked:
            other = _other_id(edge, nid)
            rel = str(edge.get("rel") or "related")
            key = (other, rel)
            if not other or key in seen:
                continue
            seen.add(key)
            row = {
                "id": other,
                "rel": rel,
                "rel_label": _REL_LABEL.get(rel, "相关"),
            }
            if other.startswith("clause:"):
                try:
                    seq = int(other.split(":", 1)[1])
                except ValueError:
                    continue
                row["seq"] = seq
                row["name"] = name_by_seq.get(seq) or str(
                    (node_by_id.get(other) or {}).get("name") or f"#{seq}"
                )
                row["kind"] = "clause"
            elif other.startswith("physics:"):
                cid = other.split(":", 1)[1]
                card = physics_by_id.get(cid) or {}
                row["physics_id"] = cid
                row["name"] = str(card.get("title") or cid)
                row["law"] = str(card.get("law") or "")
                row["kind"] = "physics"
            else:
                continue
            out.append(row)
            if len(out) >= 12:
                break
        return out

    clauses: list[dict] = []
    groups: dict[str, int] = {}
    retrieve_n = 0
    for row in frames:
        seq = int(row.get("seq") or 0)
        if not seq:
            continue
        group = str(row.get("group") or "未分组").strip() or "未分组"
        groups[group] = groups.get(group, 0) + 1
        status = str(row.get("status") or "draft").strip() or "draft"
        retrieve = bool(row.get("retrieve"))
        if retrieve:
            retrieve_n += 1
            status = "published"
        nid = f"clause:{seq}"
        related = links_for(nid)
        clauses.append(
            {
                "seq": seq,
                "name": str(row.get("name") or f"#{seq}"),
                "group": group,
                "gloss": _scrub_text(str(row.get("gloss") or "")),
                "aliases": _cap_list(row.get("aliases"), 12),
                "reject": _cap_list(row.get("exclude") or row.get("reject_patterns"), 8),
                "std": _cap_list(row.get("std"), 10),
                "units": _cap_list(row.get("unit_cues"), 4),
                "see": [int(x) for x in (row.get("see") or []) if str(x).isdigit()],
                "retrieve": retrieve,
                "status": status,
                "status_label": _STATUS_LABEL.get(status, "待确认"),
                "related": related,
            }
        )

    physics: list[dict] = []
    for cid, card in physics_by_id.items():
        nid = f"physics:{cid}"
        see_seq = [int(x) for x in (card.get("see_seq") or []) if str(x).isdigit()]
        if not see_seq:
            see_seq = [
                int(item["seq"])
                for item in links_for(nid)
                if item.get("kind") == "clause" and item.get("seq")
            ]
        physics.append(
            {
                "id": cid,
                "title": str(card.get("title") or cid),
                "law": str(card.get("law") or ""),
                "gloss": _scrub_text(str(card.get("gloss") or "")),
                "derive": bool(card.get("derive")),
                "fill": False,
                "see_seq": see_seq,
            }
        )
    physics.sort(key=lambda c: c.get("id") or "")

    graph_nodes = []
    for node in nodes:
        nid = str(node.get("id") or "")
        if nid.startswith("physics:"):
            graph_nodes.append(
                {
                    "id": nid,
                    "kind": "physics",
                    "label": str(node.get("title") or nid.split(":", 1)[-1]),
                    "law": str(node.get("law") or ""),
                }
            )
        elif nid.startswith("clause:"):
            graph_nodes.append(
                {
                    "id": nid,
                    "kind": "clause",
                    "label": str(node.get("name") or ""),
                    "group": str(node.get("group") or ""),
                    "seq": node.get("seq"),
                }
            )
    graph_edges = [
        {
            "from": str(e.get("from") or ""),
            "to": str(e.get("to") or ""),
            "rel": str(e.get("rel") or "related"),
        }
        for e in edges
        if e.get("from") and e.get("to")
    ]

    scope = manifest.get("scope") if isinstance(manifest.get("scope"), dict) else {}
    citation = manifest.get("citation") if isinstance(manifest.get("citation"), dict) else {}
    enterprise = manifest.get("enterprise") if isinstance(manifest.get("enterprise"), dict) else {}
    enterprise_clauses = []
    for row in enterprise.get("clauses") or []:
        enterprise_clauses.append(
            {
                "id": _scrub_text(str(row.get("id") or "")),
                "title": _scrub_text(str(row.get("title") or "")),
                "kind": _scrub_text(str(row.get("kind") or "")),
                "method_std": _cap_list(row.get("method_std"), 6),
                "gloss": _scrub_text(str(row.get("gloss") or "")),
                "look_in_dpr": _cap_list(row.get("look_in_dpr"), 16),
                "see_seq": [int(x) for x in (row.get("see_seq") or []) if str(x).isdigit() or isinstance(x, int)],
                "fill": False,
            }
        )
    enterprise_terms = []
    for row in enterprise.get("terms") or []:
        enterprise_terms.append(
            {
                "name": _scrub_text(str(row.get("name") or "")),
                "gloss": _scrub_text(str(row.get("gloss") or "")),
                "see_seq": [int(x) for x in (row.get("see_seq") or []) if str(x).isdigit() or isinstance(x, int)],
                "fill": False,
            }
        )
    return {
        "title": "电机控制器知识库",
        "version": version,
        "fill_from_kb": False,
        "leave_site": False,
        "classification": "内部",
        "rule": _scrub_text(
            str(
                citation.get("rule")
                or "抽出值只来自当份规格书。知识库只提供条目的含义、出处和条目间关系，不提供取值。"
            )
        ),
        "scope": {
            "answers": [_scrub_party(str(x)) for x in (scope.get("answers") or [])],
            "does_not": [_scrub_party(str(x)) for x in (scope.get("does_not") or [])],
            "owner": _scrub_party(str(scope.get("owner") or "口径经确认后使用")),
            "site": _scrub_party(str(scope.get("site") or "指定场所内使用，整库不出公网")),
        },
        "sources": [_public_source(row) for row in (manifest.get("sources") or [])],
        "stats": {
            "clauses": len(clauses),
            "physics": len(physics),
            "retrieve": retrieve_n,
            "edges": len(graph_edges),
            "groups": len(groups),
            "enterprise": len(enterprise_clauses),
        },
        "groups": [
            {"name": name, "count": count} for name, count in groups.items()
        ],
        "clauses": clauses,
        "physics": physics,
        "enterprise": enterprise_clauses,
        "enterprise_terms": enterprise_terms,
        "enterprise_meta": {
            "std_id": _scrub_text(str(enterprise.get("std_id") or "")),
            "title": _scrub_text(str(enterprise.get("title") or "")),
            "coverage": _scrub_text(str(enterprise.get("coverage") or "")),
            "rule": _scrub_text(str(enterprise.get("rule") or "")),
            "fill": False,
        },
        "graph": {"nodes": graph_nodes, "edges": graph_edges},
    }


_FEATURE_FILES = {
    "arch": "arch_kb.yaml",
    "hsi": "hsi_kb.yaml",
}


def feature_library(kind: str) -> dict:
    """电驱对照库或 HSI 规则库。不开选段，不提供可填进表的数。"""
    filename = _FEATURE_FILES.get(kind)
    if not filename:
        return {}
    path = PROJECT_ROOT / "docs" / "knowledge" / filename
    if not path.is_file():
        return {}
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if raw.get("fill_from_kb") is not False or raw.get("retrieve") is not False:
        raise ValueError(f"{filename} 必须 fill_from_kb=false 且 retrieve=false")
    clauses: list[dict] = []
    groups: dict[str, int] = {}
    for index, card in enumerate(raw.get("cards") or [], start=1):
        group = str(card.get("group") or "未分组").strip() or "未分组"
        groups[group] = groups.get(group, 0) + 1
        clauses.append(
            {
                "seq": index,
                "id": str(card.get("id") or ""),
                "name": _scrub_text(str(card.get("title") or "")),
                "group": group,
                "gloss": _scrub_text(str(card.get("gloss") or "")),
                "use": _scrub_text(str(card.get("use") or "")),
                "limits": [_scrub_text(str(item)) for item in (card.get("does_not") or [])],
                "aliases": [],
                "reject": [],
                "std": [],
                "units": [],
                "see": [],
                "retrieve": False,
                "status": "active",
                "status_label": "已用于核对",
                "related": [],
                "fill": False,
            }
        )
    scope = raw.get("scope") or {}
    return {
        "kind": kind,
        "title": _scrub_text(str(raw.get("title") or "")),
        "version": str(raw.get("version") or "").strip(),
        "fill_from_kb": False,
        "leave_site": False,
        "rule": _scrub_text(str(raw.get("rule") or "")),
        "scope": {
            "answers": [_scrub_text(str(item)) for item in (scope.get("answers") or [])],
            "does_not": [_scrub_text(str(item)) for item in (scope.get("does_not") or [])],
            "owner": _scrub_text(str(scope.get("owner") or "")),
            "site": _scrub_text(str(scope.get("site") or "")),
        },
        "sources": [],
        "stats": {
            "clauses": len(clauses),
            "physics": 0,
            "retrieve": 0,
            "edges": 0,
            "groups": len(groups),
            "enterprise": 0,
        },
        "groups": [{"name": name, "count": count} for name, count in groups.items()],
        "clauses": clauses,
        "physics": [],
        "enterprise": [],
        "enterprise_terms": [],
        "graph": {"nodes": [], "edges": []},
    }


_PENDING = PROJECT_ROOT / "docs" / "knowledge" / "pending_rulings.json"


def pending_rulings_count() -> int:
    """待专家口径的条目数（pending_rulings.json 里的 rulings 条数）。"""
    if not _PENDING.is_file():
        return 0
    try:
        data = json.loads(_PENDING.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    rows = data.get("rulings") if isinstance(data, dict) else data
    return len(rows) if isinstance(rows, list) else 0


@lru_cache(maxsize=1)
def knowledge_summary() -> dict:
    """工作台摘要卡：版本 + 数量。不含条目内容，不含取值。"""
    version = knowledge_version()
    if not version:
        return {}
    stats = dict(browse_catalog().get("stats") or {})
    out = {
        "version": version,
        "clauses": int(stats.get("clauses") or 0),
        "physics": int(stats.get("physics") or 0),
        "enterprise": int(stats.get("enterprise") or 0),
        "groups": int(stats.get("groups") or 0),
        "edges": int(stats.get("edges") or 0),
        "retrieve": int(stats.get("retrieve") or 0),
    }
    return out
