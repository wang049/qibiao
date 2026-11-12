"""兼容旧入口。请使用 python -m electrical.backend。"""
from electrical.backend.app import app, main

__all__ = ["app", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
