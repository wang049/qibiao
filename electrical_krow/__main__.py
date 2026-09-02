"""命令行入口。"""
from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="电子电器 · SOR填表")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gateway", help="启动登录后出表页（默认客户端回环，开系统浏览器）")
    sub.add_parser("desktop", help="原生窗口客户端（嵌入 Python，不跳系统浏览器）")
    sub.add_parser("site", help="场所网页模式（浏览器访问内网/本机地址）")
    sub.add_parser("mock", help="启动本机联调识别服务")
    sub.add_parser("probe", help="登录、识别连通，并和出表服务联调")
    args, rest = parser.parse_known_args(argv)
    if args.cmd == "gateway":
        from electrical_krow.gateway import main as gateway_main

        return gateway_main(rest)
    if args.cmd == "desktop":
        from electrical_krow.desktop import main as desktop_main

        return desktop_main(rest)
    if args.cmd == "site":
        from electrical_krow.gateway import main as gateway_main

        return gateway_main(["--site", *rest])
    if args.cmd == "mock":
        from electrical_krow.mock_server import main as mock_main

        return mock_main(rest)
    from electrical_krow.probe import main as probe_main

    return probe_main(rest)


if __name__ == "__main__":
    raise SystemExit(main())
