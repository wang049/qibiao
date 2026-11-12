"""出表进度与暂停/结束：工位演示页轮询用。命令行仍打 stderr。"""
from __future__ import annotations

import sys
import threading
from collections.abc import Callable

Reporter = Callable[[str, int, str], None]

_tls = threading.local()


class JobControl:
    """暂停在批次之间生效（一批最多并行若干段）；结束则停止抽取并按已抽出内容出表。"""

    def __init__(self) -> None:
        self._pause = threading.Event()
        self._stop = threading.Event()
        self._gate = threading.Event()
        self._gate.set()
        self._cb_lock = threading.Lock()
        self._on_stop: list[Callable[[], None]] = []

    def add_stop_callback(self, fn: Callable[[], None]) -> None:
        """点「结束」时立刻调用（用于断开在途 HTTP，不必等本批超时）。"""
        with self._cb_lock:
            if self._stop.is_set():
                run_now = True
            else:
                self._on_stop.append(fn)
                run_now = False
        if run_now:
            fn()

    def request_pause(self) -> None:
        if self._stop.is_set():
            return
        self._pause.set()
        self._gate.clear()

    def request_resume(self) -> None:
        self._pause.clear()
        self._gate.set()

    def request_stop(self) -> None:
        self._stop.set()
        self._pause.clear()
        self._gate.set()
        with self._cb_lock:
            callbacks = list(self._on_stop)
            self._on_stop.clear()
        for fn in callbacks:
            try:
                fn()
            except Exception:
                pass

    def paused(self) -> bool:
        return self._pause.is_set() and not self._stop.is_set()

    def stopped(self) -> bool:
        return self._stop.is_set()


def set_reporter(fn: Reporter | None) -> None:
    _tls.fn = fn


StatsReporter = Callable[[dict[str, int]], None]


def set_stats_reporter(fn: StatsReporter | None) -> None:
    """实时计数（已处理分段 / 已抽出格数）。与文字进度分开，命令行不打印。"""
    _tls.stats_fn = fn


def report_stats(**fields: int) -> None:
    fn = getattr(_tls, "stats_fn", None)
    if fn is None:
        return
    try:
        fn({k: int(v) for k, v in fields.items()})
    except Exception:  # noqa: BLE001
        pass


def set_control(ctrl: JobControl | None) -> None:
    _tls.control = ctrl


def get_control() -> JobControl | None:
    return getattr(_tls, "control", None)


def was_stopped() -> bool:
    ctrl = get_control()
    return bool(ctrl and ctrl.stopped())


def report(message: str, *, percent: int | None = None, stage: str = "") -> None:
    print(message, file=sys.stderr)
    fn = getattr(_tls, "fn", None)
    if fn is None:
        return
    pct = 0 if percent is None else max(0, min(100, int(percent)))
    fn(message, pct, stage)


def checkpoint(*, stage: str = "extract") -> bool:
    """批次之间检查。暂停则等待；结束则返回 False，调用方应停止抽取并出表。"""
    ctrl = get_control()
    if ctrl is None:
        return True
    if ctrl.stopped():
        report("已结束抽取，按已抽出内容出表…", percent=90, stage=stage)
        return False
    if ctrl.paused():
        report(
            "已暂停。点「继续」接着抽，或点「结束」按已抽出内容出表。",
            percent=None,
            stage=stage,
        )
        while ctrl.paused():
            ctrl._gate.wait(timeout=0.4)
            if ctrl.stopped():
                break
        if ctrl.stopped():
            report("已结束抽取，按已抽出内容出表…", percent=90, stage=stage)
            return False
        report("已继续出表…", stage=stage)
    return not ctrl.stopped()
