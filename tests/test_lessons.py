"""复盘召回：修之前先搜同主题；active 必须有两行 + 闸门。"""
from __future__ import annotations

import unittest

from electrical_krow.lessons import (
    closeout_ok,
    fill_from_lessons_allowed,
    load_lessons,
    recall_related,
)


class LessonRecallTests(unittest.TestCase):
    def test_lessons_never_fill_cells(self) -> None:
        self.assertFalse(fill_from_lessons_allowed())

    def test_recall_115_charge_connector(self) -> None:
        hits = recall_related("115")
        self.assertTrue(hits)
        names = [item.name for item in hits]
        self.assertTrue(any("115" in name and "connector" in name for name in names))
        by_word = recall_related("升压充电 连接器")
        self.assertTrue(any("115" in item.name for item in by_word))

    def test_active_lessons_have_closeout(self) -> None:
        lessons = load_lessons()
        self.assertTrue(lessons)
        for item in lessons:
            self.assertTrue(closeout_ok(item), item.name)


if __name__ == "__main__":
    unittest.main()
