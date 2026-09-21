"""登录页会话：cookie 或 Bearer。"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field

from electrical_krow.login import AuthSession


@dataclass
class StoredSession:
    sid: str
    auth: AuthSession
    chat_model: str = ""
    extract_model: str = ""
    created_at: float = field(default_factory=time.time)


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_sid: dict[str, StoredSession] = {}
        self._default: StoredSession | None = None

    def put(self, auth: AuthSession, *, chat_model: str = "") -> StoredSession:
        stored = StoredSession(
            sid=secrets.token_hex(16),
            auth=auth,
            chat_model=chat_model.strip(),
        )
        with self._lock:
            self._by_sid[stored.sid] = stored
            self._default = stored
        return stored

    def get(self, sid: str | None) -> StoredSession | None:
        if not sid:
            return None
        with self._lock:
            return self._by_sid.get(sid)

    def by_token(self, token: str | None) -> StoredSession | None:
        if not token:
            return None
        with self._lock:
            for item in self._by_sid.values():
                if item.auth.access_token == token:
                    return item
        return None

    def default(self) -> StoredSession | None:
        with self._lock:
            return self._default

    def set_chat_model(self, item: StoredSession, name: str) -> None:
        with self._lock:
            item.chat_model = name.strip()
            item.extract_model = ""

    def drop(self, sid: str | None) -> None:
        if not sid:
            return
        with self._lock:
            gone = self._by_sid.pop(sid, None)
            if gone is not None and self._default is gone:
                self._default = next(iter(self._by_sid.values()), None)

    def clear(self) -> list[StoredSession]:
        with self._lock:
            items = list(self._by_sid.values())
            self._by_sid.clear()
            self._default = None
        return items
