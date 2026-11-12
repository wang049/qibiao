"""对照黄金答案给核对表打分。不调用 LLM。

两种黄金格式：
- 片段式（旧）：{"must": [{group, name, contains}], "must_not": [...]}，只查若干格。
- 整表式（review-golden/1）：{"rows": [{seq, name, status, value, clause, value_must_not}]}，
  由专家认可的核对表冻结而来，逐格比对状态、数值和条款号；页码不比。

    python -m electrical.eval 核对表.xlsx examples/golden/dhts160_dpr.json
    python -m electrical.eval 专家认可.xlsx examples/golden/dhts160_dpr.json --freeze --source DHTS160_DPR.docx
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

ROW_SCHEMA = "review-golden/1"
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_MISS_WORDS = ("未检索到", "未抽出")


def _norm(text: str) -> str:
    text = (text or "").casefold()
    text = re.sub(r"(\d),(\d)", r"\1.\2", text)
    text = text.replace("×", "x").replace("·", "").replace(" ", "")
    text = text.replace("℃", "c").replace("°c", "c")
    text = text.replace("～", "~").replace("－", "-").replace("—", "-").replace("–", "-")
    text = text.replace("（", "(").replace("）", ")").replace("；", ";").replace("，", ",")
    text = text.replace("＞", ">").replace("＜", "<").replace("≥", ">=").replace("≤", "<=")
    return re.sub(r"\s+", "", text)


def _numbers(text: str) -> list[str]:
    """抽出值里的数字（去重、保序）。数值是专家最在意的东西，措辞可变，数字不能变。"""
    seen: list[str] = []
    for tok in _NUMBER.findall(_norm(text)):
        tok = tok.rstrip("0").rstrip(".") if "." in tok else tok
        if tok and tok not in seen:
            seen.append(tok)
    return seen


def _is_miss(value: str) -> bool:
    v = (value or "").strip()
    return not v or any(v.startswith(w) for w in _MISS_WORDS)


def load_review_rows(xlsx: Path) -> list[dict[str, str]]:
    """读「电控设计需求」页为逐行字典：seq / name / status / value / clause / page / note / conf。"""
    wb = load_workbook(xlsx, data_only=True)
    ws = wb["电控设计需求"] if "电控设计需求" in wb.sheetnames else wb["核对表"]
    headers: list[str] = []
    header_row = 0
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=6, values_only=True), start=1):
        texts = [str(v or "").strip() for v in row]
        if "需求条目" in texts and "抽出值" in texts:
            headers, header_row = texts, i
            break
    if not header_row:
        raise ValueError(f"{xlsx.name} 找不到「需求条目 / 抽出值」表头")

    def col(*names: str) -> int | None:
        for n in names:
            if n in headers:
                return headers.index(n)
        return None

    idx = {
        "status": col("核对状态"),
        "group": col("分组"),
        "seq": col("需求序号"),
        "name": col("需求条目", "字段"),
        "value": col("抽出值", "值"),
        "page": col("页码"),
        "clause": col("条款号"),
        "note": col("复核备注"),
        "conf": col("置信度"),
    }
    out: list[dict[str, str]] = []
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        cells = [str(v).strip() if v is not None else "" for v in row]
        get = lambda key: cells[idx[key]] if idx[key] is not None and idx[key] < len(cells) else ""  # noqa: E731
        if not get("name"):
            continue
        out.append({key: get(key) for key in idx})
    return out


def freeze(xlsx: Path, *, source: str = "", note: str = "") -> dict[str, Any]:
    """把专家认可的核对表冻结成整表黄金。页码不入黄金。"""
    rows = []
    for r in load_review_rows(xlsx):
        item: dict[str, Any] = {
            "seq": int(r["seq"]) if r["seq"].isdigit() else r["seq"],
            "name": r["name"],
            "status": r["status"],
            "value": r["value"],
        }
        if r["clause"]:
            item["clause"] = r["clause"]
        rows.append(item)
    return {
        "schema": ROW_SCHEMA,
        "source": source or xlsx.name,
        "frozen_from": xlsx.name,
        "note": note,
        "compare": {
            "status": "必须一致",
            "value": "未检索到必须仍为未检索到；否则黄金里的数字都要出现在抽出值里，措辞不同只告警",
            "clause": "不一致只告警",
            "page": "不比对",
        },
        "rows": rows,
    }


def score_rows(xlsx: Path, spec: dict[str, Any]) -> dict[str, Any]:
    produced = {}
    for r in load_review_rows(xlsx):
        key = int(r["seq"]) if r["seq"].isdigit() else r["name"]
        produced[key] = r
        produced.setdefault(r["name"], r)
    failed: list[str] = []
    warned: list[str] = []
    passed = 0
    by_status: dict[str, dict[str, int]] = {}
    for item in spec.get("rows") or []:
        seq = item.get("seq")
        label = f"#{seq} {item.get('name', '')}"
        got = produced.get(seq) or produced.get(item.get("name", ""))
        if got is None:
            failed.append(f"{label} 产出表里没有这一行")
            continue
        want_status = str(item.get("status") or "")
        bucket = by_status.setdefault(want_status, {"total": 0, "same": 0})
        bucket["total"] += 1
        problems: list[str] = []
        if got["status"] != want_status:
            problems.append(f"状态 {want_status} → {got['status']}")
        else:
            bucket["same"] += 1
        want_value = str(item.get("value") or "")
        if _is_miss(want_value):
            if not _is_miss(got["value"]):
                problems.append(f"应为未检索到，实际填了 {got['value']!r}")
        else:
            missing = [n for n in _numbers(want_value) if n not in _norm(got["value"])]
            if missing:
                problems.append(f"数字缺失 {missing}（期望 {want_value!r}，实际 {got['value']!r}）")
            elif _norm(want_value) != _norm(got["value"]):
                warned.append(f"{label} 措辞不同：期望 {want_value!r}，实际 {got['value']!r}")
        for bad in item.get("value_must_not") or []:
            if _norm(str(bad)) and _norm(str(bad)) in _norm(got["value"]):
                problems.append(f"抽出值不得含 {bad!r}（实际 {got['value']!r}）")
        want_clause = str(item.get("clause") or "")
        if want_clause and got["clause"] != want_clause:
            warned.append(f"{label} 条款号 {want_clause} → {got['clause'] or '空'}")
        if problems:
            failed.append(f"{label}：" + "；".join(problems))
        else:
            passed += 1
    total = len(spec.get("rows") or [])
    return {
        "source": spec.get("source", ""),
        "schema": ROW_SCHEMA,
        "passed": passed,
        "failed": failed,
        "warned": warned,
        "by_status": by_status,
        "ok": not failed,
        "score": f"{passed}/{total}",
    }


def load_rows(xlsx: Path) -> dict[tuple[str, str], str]:
    wb = load_workbook(xlsx, data_only=True)
    ws = wb["电控设计需求"] if "电控设计需求" in wb.sheetnames else wb["核对表"]
    header_row = 1
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=5, values_only=True), start=1):
        texts = [str(v or "") for v in row]
        if "需求条目" in texts or "字段" in texts:
            header_row = i
            headers = texts
            break
    else:
        headers = [str(v or "") for v in next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
    name_i = next((i for i, h in enumerate(headers) if h in {"需求条目", "字段"}), 2)
    value_i = next((i for i, h in enumerate(headers) if h in {"抽出值", "值"}), 3)
    seq_i = next((i for i, h in enumerate(headers) if h == "需求序号"), None)
    if seq_i is None:
        seq_i = next((i for i, h in enumerate(headers) if h == "分组"), 1)
    rows: dict[tuple[str, str], str] = {}
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if i <= header_row:
            continue
        seq = str(row[seq_i] or "").strip() if seq_i < len(row) else ""
        name = str(row[name_i] or "").strip() if name_i < len(row) else ""
        value = str(row[value_i] or "").strip() if value_i < len(row) else ""
        if name:
            rows[(seq or "条目", name)] = value
            rows[("", name)] = value
    return rows


def score(xlsx: Path, golden: Path) -> dict[str, Any]:
    spec = json.loads(golden.read_text(encoding="utf-8"))
    if spec.get("schema") == ROW_SCHEMA or "rows" in spec:
        return score_rows(xlsx, spec)
    rows = load_rows(xlsx)
    passed: list[str] = []
    failed: list[str] = []

    for item in spec.get("must") or []:
        key = (item["group"], item["name"])
        needle = _norm(item["contains"])
        raw = rows.get(key) or rows.get(("", item["name"]), "")
        value = _norm(raw)
        label = f"{key[0]}/{key[1]} 应含 {item['contains']!r}（实际 {raw!r}）"
        if needle and needle in value:
            passed.append(label)
        else:
            failed.append(label)

    for item in spec.get("must_not") or []:
        key = (item["group"], item["name"])
        needle = _norm(item["contains"])
        raw = rows.get(key) or rows.get(("", item["name"]), "")
        value = _norm(raw)
        label = f"{key[0]}/{key[1]} 不应含 {item['contains']!r}（实际 {raw!r}）"
        if needle and needle in value:
            failed.append(label)
        else:
            passed.append(label)

    return {
        "source": spec.get("source", golden.name),
        "passed": passed,
        "failed": failed,
        "ok": not failed,
        "score": f"{len(passed)}/{len(passed) + len(failed)}",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="用黄金答案给核对表打分，或把认可的核对表冻结成黄金")
    parser.add_argument("xlsx", help="pipeline 产出的核对表 xlsx（--freeze 时为专家认可的核对表）")
    parser.add_argument("golden", help="examples/golden/*.json")
    parser.add_argument("--freeze", action="store_true", help="把 xlsx 冻结成整表黄金写入 golden 路径")
    parser.add_argument("--source", default="", help="冻结时记录的源规格书名")
    parser.add_argument("--note", default="", help="冻结时记录的认可说明")
    args = parser.parse_args(argv)

    if args.freeze:
        spec = freeze(Path(args.xlsx), source=args.source, note=args.note)
        Path(args.golden).write_text(
            json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"已冻结 {len(spec['rows'])} 行 → {args.golden}")
        return 0

    result = score(Path(args.xlsx), Path(args.golden))
    print(f"{result['source']}  {result['score']}  {'通过' if result['ok'] else '未通过'}")
    for status, bucket in (result.get("by_status") or {}).items():
        print(f"  {status:<12} 状态一致 {bucket['same']}/{bucket['total']}")
    for line in result["failed"]:
        print(f"  FAIL  {line}")
    for line in result.get("warned") or []:
        print(f"  WARN  {line}")
    if result["ok"] and isinstance(result["passed"], list):
        for line in result["passed"]:
            print(f"  PASS  {line}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
