"""检索结果三类标准。"""
from __future__ import annotations

import unittest

from electrical.schema import (
    STATUS_FOUND,
    STATUS_MISS,
    STATUS_PARTIAL,
    ExtractedCell,
    finalize_retrieval_statuses,
)


class RetrievalStatusTests(unittest.TestCase):
    def test_three_way_finalize(self) -> None:
        cells = [
            ExtractedCell(name="a", seq=1, value="125kW", confidence=0.9),
            ExtractedCell(name="b", seq=2),
            ExtractedCell(
                name="c",
                seq=3,
                note="原文仅有流程语，无数值",
            ),
            ExtractedCell(name="d", seq=4, value="约略相关", confidence=0.5),
        ]
        finalize_retrieval_statuses(cells)
        self.assertEqual(cells[0].review_status, STATUS_FOUND)
        self.assertEqual(cells[1].review_status, STATUS_MISS)
        self.assertEqual(cells[2].review_status, STATUS_PARTIAL)
        self.assertEqual(cells[3].review_status, STATUS_PARTIAL)

    def test_finalize_does_not_upgrade_partial(self) -> None:
        cells = [
            ExtractedCell(
                name="P1最高工作转速",
                seq=35,
                value="16000 Rpm",
                confidence=0.9,
                review_status=STATUS_PARTIAL,
                note="交流基频满性能假设（极对数×转速），不是最高工作转速定义。",
            ),
            ExtractedCell(
                name="升压充电功能",
                seq=115,
                value="有高压慢充连接器",
                confidence=0.82,
                review_status=STATUS_PARTIAL,
            ),
        ]
        finalize_retrieval_statuses(cells)
        self.assertEqual(cells[0].review_status, STATUS_PARTIAL)
        self.assertEqual(cells[1].review_status, STATUS_PARTIAL)

    def test_method_note_without_value_stays_miss(self) -> None:
        cells = [
            ExtractedCell(
                name="最大散热能力",
                seq=72,
                note="企标方法对照：当份 DPR 未给出该指标；Q/JLP 030602-07-2026A 7.3 → Q/JLP 030600-11。",
                review_status=STATUS_MISS,
            )
        ]
        finalize_retrieval_statuses(cells)
        self.assertEqual(cells[0].review_status, STATUS_MISS)
        self.assertFalse((cells[0].value or "").strip())


if __name__ == "__main__":
    unittest.main()
