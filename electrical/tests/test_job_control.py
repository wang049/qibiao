"""暂停 / 结束在段与段之间生效。"""
from __future__ import annotations

import threading
import unittest

from electrical.progress import JobControl, checkpoint, set_control, was_stopped


class JobControlTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_control(None)

    def test_stop_makes_checkpoint_false(self) -> None:
        ctrl = JobControl()
        set_control(ctrl)
        self.assertTrue(checkpoint())
        ctrl.request_stop()
        self.assertFalse(checkpoint())
        self.assertTrue(was_stopped())

    def test_pause_then_resume(self) -> None:
        ctrl = JobControl()
        set_control(ctrl)
        ctrl.request_pause()
        self.assertTrue(ctrl.paused())

        def resume() -> None:
            ctrl.request_resume()

        threading.Timer(0.05, resume).start()
        self.assertTrue(checkpoint())
        self.assertFalse(ctrl.paused())

    def test_stop_unblocks_pause(self) -> None:
        ctrl = JobControl()
        set_control(ctrl)
        ctrl.request_pause()

        def stop() -> None:
            ctrl.request_stop()

        threading.Timer(0.05, stop).start()
        self.assertFalse(checkpoint())
        self.assertTrue(was_stopped())

    def test_stop_runs_callback_immediately(self) -> None:
        ctrl = JobControl()
        seen: list[str] = []
        ctrl.add_stop_callback(lambda: seen.append("closed"))
        ctrl.request_stop()
        self.assertEqual(seen, ["closed"])

    def test_callback_after_already_stopped_runs_now(self) -> None:
        ctrl = JobControl()
        ctrl.request_stop()
        seen: list[str] = []
        ctrl.add_stop_callback(lambda: seen.append("late"))
        self.assertEqual(seen, ["late"])


class StatsReporterTests(unittest.TestCase):
    """实时计数：没挂接收方时静默；挂上后收到整数字段；接收方抛错不影响抽取。"""

    def tearDown(self) -> None:
        from electrical.progress import set_stats_reporter

        set_stats_reporter(None)

    def test_report_stats_delivers_ints_and_swallows_errors(self) -> None:
        from electrical.progress import report_stats, set_stats_reporter

        report_stats(filled=3)  # 无接收方不报错
        got: list[dict] = []
        set_stats_reporter(got.append)
        report_stats(chunk_done=2, chunk_total="9", filled=41.0)
        self.assertEqual(got, [{"chunk_done": 2, "chunk_total": 9, "filled": 41}])

        def boom(_fields: dict) -> None:
            raise RuntimeError("接收方坏了")

        set_stats_reporter(boom)
        report_stats(filled=1)  # 不抛


if __name__ == "__main__":
    unittest.main()
