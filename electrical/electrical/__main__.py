"""命令行：python -m electrical 规格书.pdf"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from electrical.extract import DEFAULT_MODEL, ExtractError
from electrical.pipeline import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="电子电器 · SOR填表：读 PDF/Word/Excel，产出可核对 Excel",
    )
    parser.add_argument("input", help="规格书路径（.pdf / .docx / .xlsx）")
    parser.add_argument(
        "-o",
        "--output",
        help="输出 xlsx 路径（默认 output/<原文件名>_<年月日时分秒>.xlsx）",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"本机 Ollama 模型名（默认 {DEFAULT_MODEL}）",
    )
    args = parser.parse_args(argv)

    try:
        result = run(
            Path(args.input),
            Path(args.output) if args.output else None,
            model=args.model,
        )
    except FileNotFoundError as exc:
        print(f"找不到文件: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"无法处理: {exc}", file=sys.stderr)
        return 2
    except ExtractError as exc:
        print(f"抽取失败: {exc}", file=sys.stderr)
        return 1

    filled = result.filled
    print(f"源文件 : {Path(args.input).name}")
    if result.kind_label:
        print(f"类型   : {result.kind_label}（{'抽取' if result.extract else '不按 120 项电控清单抽取'}）")
    print(f"扫描件 : {'可能是' if result.likely_scan else '否（按数字稿处理）'}")
    if result.qa_verdict or result.qa_summary:
        print(f"质检   : {result.qa_summary or result.qa_verdict}")
    print(f"输出   : {result.output_xlsx}")
    print(
        f"字段   : {len(result.cells)} 行，已填 {filled} 行，"
        f"{result.pending_review} 行建议人工核对"
    )
    if result.kind_note:
        print(f"说明   : {result.kind_note}")
    if result.coverage_note and result.extract:
        print(f"覆盖   : {result.coverage_note}")
    print(f"耗时   : {result.elapsed_seconds:.1f} 秒")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
