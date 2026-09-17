"""业务复盘召回：修之前先搜 .insights；active 必须有两行 + 闸门。不得填格。"""
from __future__ import annotations

import unittest

from electrical_krow.lessons import (
    LESSONS_DIR,
    closeout_ok,
    fill_from_lessons_allowed,
    load_lessons,
    recall_related,
)
from electrical_krow.paths import PROJECT_ROOT


class LessonRecallTests(unittest.TestCase):
    def test_lessons_never_fill_cells(self) -> None:
        self.assertFalse(fill_from_lessons_allowed())

    def test_business_lessons_live_in_insights_not_krow(self) -> None:
        self.assertEqual(LESSONS_DIR, PROJECT_ROOT / ".insights" / "lessons")
        self.assertTrue(LESSONS_DIR.is_dir())
        leftover = PROJECT_ROOT / ".krow" / "lessons"
        if leftover.is_dir():
            leftover_md = [
                p.name for p in leftover.glob("*.md") if not p.name.startswith("_")
            ]
            self.assertEqual(leftover_md, [])

    def test_recall_115_charge_connector(self) -> None:
        hits = recall_related("115")
        self.assertTrue(hits)
        names = [item.name for item in hits]
        self.assertTrue(any("115" in name and "connector" in name for name in names))
        by_word = recall_related("升压充电 连接器")
        self.assertTrue(any("115" in item.name for item in by_word))
        self.assertTrue(all(".insights" in str(item.path) for item in hits))

    def test_active_lessons_have_closeout(self) -> None:
        lessons = load_lessons()
        self.assertTrue(lessons)
        for item in lessons:
            self.assertTrue(closeout_ok(item), item.name)
            self.assertEqual(item.path.parent.resolve(), LESSONS_DIR.resolve())


if __name__ == "__main__":
    unittest.main()
