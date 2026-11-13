"""企标对话不联网：未给网址时跳过抓取，临时文档能抽出关键行。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unittest import mock

from docx import Document

from electrical_krow import enterprise_dialogue as dialogue


class EnterpriseDialogueTest(unittest.TestCase):
    def test_missing_url_skips_fetch(self) -> None:
        text, note = dialogue.fetch_source_page("")
        self.assertEqual(text, "")
        self.assertIn("尚未提供", note)

    def test_private_and_local_urls_are_rejected(self) -> None:
        for raw in ("http://127.0.0.1/a", "http://10.1.2.3/a", "http://localhost/a", "file:///c:/a"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    dialogue.public_http_url(raw)

    def test_public_address_is_kept(self) -> None:
        self.assertEqual(dialogue.public_http_url("https://8.8.8.8/std"), "https://8.8.8.8/std")

    def test_docx_key_lines_follow_the_clause_rule(self) -> None:
        dialogue._CACHE = None
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            path = folder / "企标.docx"
            document = Document()
            document.add_paragraph("7.7.1 绝缘性能试验")
            document.add_paragraph("3.1 范围")
            document.save(path)
            brief = dialogue.file_key_brief(folder)
        self.assertIn("7.7.1", brief)
        self.assertIn("绝缘性能试验", brief)
        self.assertNotIn("3.1", brief)

    def test_recorded_lines_remain_when_the_folder_is_gone(self) -> None:
        missing = Path(tempfile.gettempdir()) / "enterprise-std-missing"
        with mock.patch.object(dialogue, "standards_dir", return_value=missing):
            brief = dialogue.file_key_brief()
        self.assertIn("7.7.1", brief)
        self.assertIn("绝缘性能试验", brief)
        self.assertIn("不要补写", brief)

    def test_recorded_brief_stays_off_the_list_until_it_has_a_page(self) -> None:
        tables = {sheet["title"]: sheet for sheet in dialogue.output_tables("", dialogue._RECORDED_BRIEF)}
        names = [row[1] for row in tables["测试项对比表"]["rows"]]
        self.assertEqual(names, ["电气安全试验", "绝缘性能试验", "电气间隙和爬电距离试验"])
        self.assertTrue(all(row[6] == "待确认" for row in tables["测试项对比表"]["rows"]))
        self.assertEqual(tables["企标测试清单"]["rows"], [])
        self.assertEqual(tables["测试用例"]["rows"], [])
        self.assertIn("未提供阶段模板", tables["填报记录"]["rows"][1][2])

    def test_paged_line_enters_the_list_as_a_draft(self) -> None:
        brief = "企标.pdf | 6.2 | 第12页 | 绝缘电阻试验"
        tables = {sheet["title"]: sheet for sheet in dialogue.output_tables("6.4 湿热试验", brief)}
        self.assertEqual(tables["企标测试清单"]["rows"][0][:3], ["6.2", "绝缘电阻试验", "企标.pdf"])
        case = tables["测试用例"]["rows"][0]
        self.assertEqual(case[6], "用例初稿")
        self.assertEqual(case[8], "")
        pending = [row[1] for row in tables["测试项对比表"]["rows"] if row[6] == "待确认"]
        self.assertIn("湿热试验", pending)

    def test_turns_require_a_user_line(self) -> None:
        with self.assertRaises(ValueError):
            dialogue.clean_turns([{"role": "assistant", "content": "先说要查什么"}])
        turns = dialogue.clean_turns([{"role": "user", "content": "绝缘试验怎么做"}])
        self.assertEqual(turns[0]["role"], "user")


if __name__ == "__main__":
    unittest.main()
