import sys
import tempfile
import unittest
from pathlib import Path

from electrical_krow.local_table import intake_summary, read_shared_bytes, stage_table


class LocalTableTest(unittest.TestCase):
    def test_shared_read_matches_the_file(self) -> None:
        folder = Path(tempfile.mkdtemp())
        path = folder / "plain.txt"
        path.write_bytes("1.1 绝缘\n".encode("utf-8"))
        self.assertEqual(read_shared_bytes(path), path.read_bytes())

    def test_shared_read_works_while_another_program_holds_the_file(self) -> None:
        if sys.platform != "win32":
            self.skipTest("Windows share read")
        import ctypes
        from ctypes import wintypes

        folder = Path(tempfile.mkdtemp())
        path = folder / "plain.txt"
        payload = "1.1 绝缘\n".encode("utf-8")
        path.write_bytes(payload)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        # 和 Excel 打开工作簿一样：自己读写，只允许别人读。
        handle = kernel.CreateFileW(str(path), 0x80000000 | 0x40000000, 0x1, None, 3, 0x80, None)
        self.assertNotEqual(handle, wintypes.HANDLE(-1).value)
        try:
            self.assertEqual(read_shared_bytes(path), payload)
        finally:
            kernel.CloseHandle(handle)

    def test_stage_reads_rows_from_a_copy(self) -> None:
        from openpyxl import Workbook

        folder = Path(tempfile.mkdtemp())
        path = folder / "表.xlsx"
        book = Workbook()
        grid = book.active
        grid.append(["序号", "试验项目", "试验标准号及名称", "目标要求"])
        grid.append(["1.1", "绝缘", "Q/JLY J7110218D-2025", "满足图纸"])
        book.save(path)
        book.close()
        _kept, _dest, manual, size = stage_table(path)
        self.assertEqual(size, path.stat().st_size)
        self.assertEqual(len(manual), 1)
        self.assertIn("抽出 1 行", intake_summary(path.name, manual, size))
        self.assertIn("接下来打开", intake_summary(path.name, manual, size))

    def test_motor_workbook_is_read_locally(self) -> None:
        path = Path(r"D:\企标测试\输入条件") / "(电机DVP)DVP-001.xlsx"
        if not path.is_file():
            self.skipTest("motor workbook is not on this machine")
        _kept, _dest, manual, size = stage_table(path)
        self.assertEqual(size, path.stat().st_size)
        self.assertEqual(len(manual), 63)
        text = intake_summary(path.name, manual, size)
        self.assertIn("抽出 63 行", text)
        self.assertIn("J7110218D-2025", text.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
