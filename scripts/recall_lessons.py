#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修认条/出表前召回同主题复盘。不调 LLM，不填抽出值。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from electrical_krow.lessons import fill_from_lessons_allowed, recall_related


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="召回 .krow/lessons 同主题复盘（修 bug 前先跑）"
    )
    parser.add_argument("query", nargs="+", help="清单序号或关键词，如 115 或 升压充电")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--full", action="store_true", help="打印全文")
    args = parser.parse_args(argv)
    if fill_from_lessons_allowed():
        raise SystemExit("lessons must not fill extracted values")
    query = " ".join(args.query).strip()
    hits = recall_related(query, limit=args.limit)
    if not hits:
        print(f"无命中：{query}")
        print("没有同主题复盘也可以改，但结案时仍须新写一篇。")
        return 0
    print(f"召回 {len(hits)} 篇（不得写入抽出值）：")
    for item in hits:
        rel = item.path.relative_to(ROOT)
        seqs = ",".join(f"#{n}" for n in item.seqs) or "—"
        print(f"\n- {rel}")
        print(f"  {item.title}  [{item.status}]  {seqs}")
        if args.full:
            print(item.body.rstrip())
        else:
            if item.counterfactual:
                print(f"  反事实：{item.counterfactual.splitlines()[0][:120]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
