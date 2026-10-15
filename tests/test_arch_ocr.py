from __future__ import annotations

import unittest

from electrical_krow.arch_contrast import NOTE_OCR, SourceDoc, drop_duplicate_grids, split_document, table_entries
from electrical_krow.arch_ocr import grid_lines, merge_boxes

try:
    import cv2
    import numpy as np
    from rapidocr import RapidOCR  # noqa: F401

    _OCR_READY = True
except Exception:  # noqa: BLE001
    _OCR_READY = False


def _draw_table(cells: list[list[str]], *, merge_header: bool = False):
    """画一张带格线的表格图（黑线白底），每格居中写字。merge_header 时表头第二、三格合并成一格。"""
    cell_w, cell_h = 260, 70
    rows, cols = len(cells), len(cells[0])
    img = np.full((rows * cell_h + 1, cols * cell_w + 1), 255, dtype=np.uint8)
    for r in range(rows + 1):
        cv2.line(img, (0, r * cell_h), (cols * cell_w, r * cell_h), 0, 2)
    for c in range(cols + 1):
        for r in range(rows):
            if merge_header and r == 0 and c == 2:
                continue  # 表头第 2、3 格之间不画线
            cv2.line(img, (c * cell_w, r * cell_h), (c * cell_w, (r + 1) * cell_h), 0, 2)
    for r, row in enumerate(cells):
        for c, text in enumerate(row):
            if text:
                x = c * cell_w + 20
                if merge_header and r == 0 and c == 1:
                    x = c * cell_w + cell_w  # 合并格的字写在两格中间
                cv2.putText(img, text, (x, r * cell_h + 45), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 2)
    return img


class ArchOcrTests(unittest.TestCase):
    def test_merge_boxes_joins_stacked_slices_of_one_table(self) -> None:
        boxes = [(42.0, 224.0, 553.0, 340.0), (42.0, 340.0, 553.0, 455.0), (160.0, 366.0, 502.0, 426.0)]
        merged = merge_boxes(boxes)
        self.assertIn((42.0, 224.0, 553.0, 455.0), merged)
        self.assertIn((160.0, 366.0, 502.0, 426.0), merged)  # 另一张不对齐的图不并
        self.assertEqual(len(merged), 2)

    def test_grid_lines_need_two_rows_and_two_columns(self) -> None:
        blank = np.full((200, 400), 255, dtype=np.uint8)
        self.assertEqual(grid_lines(blank), ([], []))
        ys, xs = grid_lines(_draw_table([["a", "b"], ["c", "d"]]))
        self.assertEqual((len(ys), len(xs)), (3, 3))

    @unittest.skipUnless(_OCR_READY, "rapidocr 不可用")
    def test_grid_from_image_reads_cells_and_merged_header(self) -> None:
        from electrical_krow.arch_ocr import grid_from_image

        grid = grid_from_image(_draw_table([["Item", "Spec", ""], ["Ripple", "1.0 V", "pk-pk"], ["Delay", "10 ms", "max"]], merge_header=True))
        self.assertIsNotNone(grid)
        self.assertEqual((len(grid), len(grid[0])), (3, 3))
        self.assertEqual(grid[0][0].lower(), "item")
        self.assertEqual(grid[0][1].lower(), "spec")  # 合并表头归到左格
        self.assertEqual(grid[0][2], "")
        self.assertEqual(grid[1][0].lower(), "ripple")
        self.assertIn("1.0", grid[1][1])
        self.assertIn("10", grid[2][1])
        entries = table_entries(grid)
        self.assertEqual([e.item.lower() for e in entries], ["ripple", "delay"])

    @unittest.skipUnless(_OCR_READY, "rapidocr 不可用")
    def test_diagram_without_grid_is_not_a_table(self) -> None:
        from electrical_krow.arch_ocr import grid_from_image

        img = np.full((300, 600), 255, dtype=np.uint8)
        cv2.rectangle(img, (50, 50), (550, 250), 0, 2)
        cv2.putText(img, "Power Semiconductor", (120, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 2)
        self.assertIsNone(grid_from_image(img))

    def test_drop_duplicate_grids_keeps_only_image_tables_without_text_layer(self) -> None:
        text_grid = [["Classification", "Analysis", "", "Verification results"], ["LDC", "①", "Vibration", "ESIR verification data"]]
        ocr_same = [["Classification", "Analysis", "", "Verification results"], ["LDC", "①", "Vibration", "ESIR verification data"]]
        ocr_other = [["Item", "Spec"], ["Ripple", "1.0 V"], ["Delay", "10 ms"]]
        kept = drop_duplicate_grids({42: [text_grid]}, {42: [ocr_same, ocr_other], 7: [ocr_other]})
        self.assertEqual(kept, {42: [ocr_other], 7: [ocr_other]})

    def test_split_document_emits_image_table_rows_with_ocr_note(self) -> None:
        pages = ((1, "4.3 Analysis and verification\nSubmit the result of the analysis for each item below."),)
        grid = [["Item", "Spec"], ["Ripple", "1.0 V"], ["Delay", "10 ms"]]
        rows, tables = split_document(SourceDoc("ldc.pdf", pages, {}, {1: [grid]}))
        table_rows = [r for r in rows if r[7]]
        self.assertEqual([(r[7], r[9]) for r in table_rows], [("Ripple", "1.0 V"), ("Delay", "10 ms")])
        self.assertTrue(all(NOTE_OCR in r[15] for r in table_rows))
        self.assertEqual(tables, [])  # 拆成行的表不再整表进附件
        # 表头认不出的图片表格才整表进附件，类型标 OCR
        _, tables = split_document(SourceDoc("ldc.pdf", pages, {}, {1: [[["a", "b"], ["c", "d"], ["e", "f"]]]}))
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0][5], "图片表格·OCR")
        self.assertIn(NOTE_OCR, tables[0][7])


if __name__ == "__main__":
    unittest.main()
