"""出表 HTTP 服务：只监听本机，规格书不出公网。"""

from electrical.backend.app import app, main

__all__ = ["app", "main"]
