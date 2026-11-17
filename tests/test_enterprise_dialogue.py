"""企标对话不联网：未给网址时跳过抓取，临时文档能抽出关键行。"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from docx import Document
from openpyxl import Workbook

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

    def test_replaced_and_older_files_are_dropped(self) -> None:
        page = """
        <a href="https://8.8.8.8/a.docx">Q-JLY J7110137D-2019-车载充电机.docx</a>
        <a href="https://8.8.8.8/b.docx">Q-JLY J7110137E-2024-车载充电机.docx</a>
        <a href="https://8.8.8.8/c.docx">Q-JLY J7110137E-2024-车载充电机-修订.docx 已替换</a>
        """
        kept = dialogue.files_for_table(
            dialogue.parse_catalog(page, "https://8.8.8.8/list"),
            "标准号 J7110137 绝缘性能试验",
        )
        self.assertEqual([item.name for item in kept], ["Q-JLY J7110137E-2024-车载充电机.docx"])

    def test_comparison_lists_every_condition_with_source(self) -> None:
        manual = [dialogue.ManualItem("7.7.1", "绝缘性能试验")]
        conditions = dialogue.conditions_from_pages(
            [("12", "7.7.1 绝缘性能试验\n试验条件：温度 25℃\n7.8 其他试验")],
            "车载充电机.docx",
        )
        sheet = dialogue.build_comparison_sheet(manual, conditions, note="")
        headers = sheet["headers"]
        rows = sheet["rows"]
        compared = headers.index("对比")
        indicator = headers.index("指标")
        standard_text = headers.index("标准条件")
        source = headers.index("来源")
        document = headers.index("标准文件")
        self.assertEqual(rows[0][compared], "对应")
        self.assertEqual(rows[0][indicator], "验证对比")
        self.assertTrue(any("温度 25℃" in row[standard_text] for row in rows))
        self.assertTrue(
            any("第12页" in row[source] and row[document] == "车载充电机.docx" for row in rows if row[compared] == "对应")
        )
        self.assertTrue(
            any(
                row[compared] == "标准有、测试表未列" and row[indicator] == "欠缺补充" and row[standard_text] == "其他试验"
                for row in rows
            )
        )

    def test_missing_url_does_not_invent_a_standard(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "测试表.txt"
            path.write_text("7.7.1 绝缘性能试验\n", encoding="utf-8")
            with mock.patch.object(dialogue, "source_url", return_value=""):
                result = dialogue.compare_manual_file(path)
        sheet = result["tables"][0]
        row = sheet["rows"][0]
        headers = sheet["headers"]
        self.assertEqual(row[headers.index("试验项目")], "绝缘性能试验")
        self.assertIn("尚未提供", row[headers.index("对比")])
        self.assertEqual(row[headers.index("标准条件")], "")

    def test_dvp_input_keeps_standard_clause_and_criteria(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "电机.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.append(["序号 / No.", "试验项目 / Test Name", "试验标准号及名称 / Test Spec.", "目标要求 / （评定依据） / Test Criteria"])
            sheet.append(["DV试验阶段"])
            sheet.append(["1.1", "超速", "Q/JLY J7110218D-2025", "电机应能承受不低于1.1倍最高工作转速"])
            book.save(path)
            book.close()
            items = dialogue.read_manual_table(path)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.stage, "DV")
        self.assertEqual(item.number, "1.1")
        self.assertEqual(item.name, "超速")
        self.assertIn("J7110218D-2025", item.standard)
        self.assertEqual(item.clause_id, "")
        self.assertIn("1.1倍", item.criteria)

    def test_referenced_condition_is_taken_from_the_input_row(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "电控.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.title = "DVP&R"
            sheet.append(["序号 / No.", "试验项目 / Test Name", "试验标准号及名称 / Test Spec.", "试验条件 / Test Condition", "目标要求（评定依据） / Test Criteria"])
            sheet.append(["Property requirements of parts  DV性能验证"])
            sheet.append(["Leg03", "EMC", "Q/JLY J7110779E-2023-乘用车电气-电子零部件电磁兼容规范", "满足电磁兼容规范", "需符合零部件产品测试计划"])
            sheet.append(["Leg01-02", "低温储存", "按Q/JLY J7111029E-2024① 5.3.1要求：", "a）环境温度：-40℃", "满足功能状态 A"])
            sheet.append(["Property requirements of parts  ECV性能验证"])
            sheet.append(["Leg01-03", "低温工作", "按Q/JLY J7111029E-2024① 5.3.2要求：", "参考DV Leg01-02试验条件要求", "满足功能状态 A"])
            book.save(path)
            book.close()
            items = dialogue.read_manual_table(path)
        self.assertEqual([item.number for item in items], ["Leg03", "Leg01-02", "Leg01-03"])
        self.assertEqual([item.clause_id for item in items], ["", "5.3.1", "5.3.2"])
        self.assertEqual(items[2].stage, "ECV")
        self.assertEqual(items[2].condition, "a）环境温度：-40℃")

    def test_sso_host_may_resolve_to_intranet(self) -> None:
        with mock.patch.object(
            dialogue.socket,
            "getaddrinfo",
            return_value=[(2, 1, 6, "", ("198.18.0.33", 0))],
        ):
            kept = dialogue.public_http_url("https://sso.aurobaytech.com/frontend/login")
        self.assertTrue(kept.startswith("https://sso.aurobaytech.com/"))

    def test_other_host_on_intranet_is_rejected(self) -> None:
        with mock.patch.object(
            dialogue.socket,
            "getaddrinfo",
            return_value=[(2, 1, 6, "", ("10.1.2.3", 0))],
        ):
            with self.assertRaises(ValueError):
                dialogue.public_http_url("https://example.com/a")

    def test_login_page_is_not_a_file_list(self) -> None:
        def get(url: str):
            if url.rstrip("/").endswith("aurobaytech.com"):
                return 301, "http://sso.aurobaytech.com/frontend/login#/geelyLogin", b""
            return 200, "", "<title>统一登录门户 登录</title>".encode()

        with mock.patch.object(
            dialogue.socket,
            "getaddrinfo",
            return_value=[(2, 1, 6, "", ("198.18.0.33", 0))],
        ):
            _final, body, note = dialogue.follow_same_host("https://sso.aurobaytech.com/", get)
        self.assertEqual(body, b"")
        self.assertIn("登录尚未完成", note)

    def test_file_page_is_read_after_login_redirect(self) -> None:
        def get(url: str):
            if "files" not in url:
                return 302, "https://sso.aurobaytech.com/files", b""
            return 200, "", b"<a href='a.docx'>J7110137E-2024.docx</a>"

        with mock.patch.object(
            dialogue.socket,
            "getaddrinfo",
            return_value=[(2, 1, 6, "", ("10.8.0.4", 0))],
        ):
            final, body, note = dialogue.follow_same_host(
                "https://sso.aurobaytech.com/frontend/login", get
            )
        self.assertTrue(final.endswith("/files"))
        self.assertIn(b"docx", body)
        self.assertEqual(note, "已读取网址。")

    def test_redirect_to_another_site_stops(self) -> None:
        def get(_url: str):
            return 302, "https://8.8.8.8/files", b""

        with mock.patch.object(
            dialogue.socket,
            "getaddrinfo",
            return_value=[(2, 1, 6, "", ("198.18.0.33", 0))],
        ):
            with self.assertRaises(ValueError):
                dialogue.follow_same_host("https://sso.aurobaytech.com/", get)

    def test_login_fields_in_the_url_are_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            dialogue.public_http_url("https://account:secret@sso.aurobaytech.com/login")
        self.assertIn("不代填", str(caught.exception))

    def test_stored_account_or_password_is_refused(self) -> None:
        with mock.patch.dict(os.environ, {"ENTERPRISE_TEST_PASSWORD": "secret"}):
            with self.assertRaises(ValueError) as caught:
                dialogue.public_http_url("https://8.8.8.8/std")
        self.assertIn("不代填", str(caught.exception))

    def test_workstation_login_is_not_this_rule(self) -> None:
        with mock.patch.dict(os.environ, {"KROW_PASSWORD": "workstation"}, clear=False):
            self.assertEqual(dialogue.public_http_url("https://8.8.8.8/std"), "https://8.8.8.8/std")

    def test_turns_require_a_user_line(self) -> None:
        with self.assertRaises(ValueError):
            dialogue.clean_turns([{"role": "assistant", "content": "先说要查什么"}])
        turns = dialogue.clean_turns([{"role": "user", "content": "绝缘试验怎么做"}])
        self.assertEqual(turns[0]["role"], "user")


if __name__ == "__main__":
    unittest.main()
