# -*- coding: utf-8 -*-
"""跑认条召回题集：docs/knowledge/eval/*.yaml → keyword_hits。

    python scripts/eval_knowledge.py            # 全部题集
    python scripts/eval_knowledge.py --only 115 # 只跑 id/must_hit 含 115 的题

题集只评「这句话认到哪一条」，不评取值；抽出值仍只来自当份规格书。
导出包给公司知识库后，用同一份题集回归他们的检索层。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

try:
    import yaml
except ImportError:
    sys.stderr.write("需要 PyYAML：pip install pyyaml\n")
    raise

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "docs" / "knowledge" / "eval"
LESSONS = ROOT / ".insights" / "lessons"

HitsFn = Callable[..., list[dict]]


def load_cases(eval_dir: Path = EVAL_DIR) -> list[dict]:
    cases: list[dict] = []
    for path in sorted(eval_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for raw in data.get("cases") or []:
            case = dict(raw)
            case.setdefault("must_hit", [])
            case.setdefault("must_not_hit", [])
            case.setdefault("caution", [])
            case["must_hit"] = [int(x) for x in case["must_hit"]]
            case["must_not_hit"] = [int(x) for x in case["must_not_hit"]]
            case["caution"] = [int(x) for x in case["caution"]]
            case["file"] = path.name
            cases.append(case)
    return cases


def check_case(case: dict, hits_fn: HitsFn) -> dict:
    hits = hits_fn(str(case["query"]), retrieve_only=bool(case.get("retrieve_only")))
    got = sorted({int(h.get("seq") or 0) for h in hits} - {0})
    must = set(case["must_hit"])
    banned = set(case["must_not_hit"])
    problems: list[str] = []
    missing = sorted(must - set(got))
    if missing:
        problems.append("漏召回 " + ",".join(f"#{n}" for n in missing))
    leaked = sorted(banned & set(got))
    if leaked:
        problems.append("误召回 " + ",".join(f"#{n}" for n in leaked))
    if case.get("only"):
        extra = sorted(set(got) - must)
        if extra:
            problems.append("多召回 " + ",".join(f"#{n}" for n in extra))
    return {
        "id": str(case.get("id") or case["query"]),
        "query": str(case["query"]),
        "got": got,
        "ok": not problems,
        "problems": problems,
        "caution": sorted(set(case["caution"]) & set(got)),
        "lesson": str(case.get("lesson") or ""),
    }


def lesson_refs_exist(cases: list[dict]) -> list[str]:
    """题集引用的复盘必须真实存在，防止题目失去二级依据。"""
    missing: list[str] = []
    for case in cases:
        name = str(case.get("lesson") or "").strip()
        if name and not (LESSONS / f"{name}.md").is_file():
            missing.append(f"{case.get('id')}: {name}")
    return missing


def run_eval(cases: list[dict], hits_fn: HitsFn) -> list[dict]:
    return [check_case(case, hits_fn) for case in cases]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="跑认条召回题集")
    parser.add_argument("--only", default="", help="只跑 id 含该字串或 must_hit 含该序号的题")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(ROOT))
    from electrical_krow.knowledge import keyword_hits

    cases = load_cases()
    if args.only:
        key = args.only.strip()
        cases = [
            c
            for c in cases
            if key in str(c.get("id") or "")
            or (key.isdigit() and int(key) in c["must_hit"] + c["must_not_hit"])
        ]
    missing = lesson_refs_exist(cases)
    for item in missing:
        print(f"[缺复盘] {item}")
    results = run_eval(cases, keyword_hits)
    failed = 0
    for res in results:
        mark = "OK " if res["ok"] else "FAIL"
        line = f"{mark} {res['id']:34} -> {res['got']}"
        if res["caution"]:
            line += f"  (检索层允许、出表须拒: {res['caution']})"
        if res["problems"]:
            line += "  " + "；".join(res["problems"])
        print(line)
        failed += 0 if res["ok"] else 1
    print(f"\n{len(results) - failed}/{len(results)} 通过")
    return 1 if (failed or missing) else 0


if __name__ == "__main__":
    raise SystemExit(main())
