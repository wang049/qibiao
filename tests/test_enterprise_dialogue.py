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
        self.assertEqual(rows[0][headers.index("结论")], "对应")
        self.assertTrue(any("温度 25℃" in row[standard_text] for row in rows))
        self.assertTrue(
            any("第12页" in row[source] and row[document] == "车载充电机.docx" for row in rows if row[compared] == "对应")
        )
        self.assertTrue(
            any(
                row[compared] == "标准有、测试表未列" and row[indicator] == "欠缺补充" and row[standard_text] == "其他试验"
                and row[headers.index("条款")] == "7.8" and row[headers.index("试验项目")] == "其他试验"
                for row in rows
            )
        )
        self.assertIn("其他试验", dialogue.clause_findings(sheet))

    def test_missing_file_is_a_gap_and_lookup_words_are_used(self) -> None:
        sheet = dialogue.build_comparison_sheet(
            [dialogue.ManualItem("1.1", "超速", standard="J7110218D-2025")],
            [],
            note="未返回",
        )
        self.assertEqual(sheet["rows"][0][sheet["headers"].index("结论")], "缺少")
        self.assertIn("未返回", sheet["rows"][0][sheet["headers"].index("对比")])
        item = dialogue.ManualItem("", "绝缘", standard="见附件")
        written = dialogue.apply_lookup_terms(
            [item],
            '[{"i":0,"standard_no":"J7110137E-2024","file_name":"车载充电机.docx"}]',
        )
        self.assertEqual(written, 1)
        self.assertEqual(
            dialogue.search_queries([item]),
            ["J7110137E-2024"],
        )
        findings = dialogue.clause_findings(sheet)
        self.assertIn("缺少的条款", findings)
        self.assertIn("超速", findings)
        self.assertIn("条款 1.1", findings)
        self.assertIn("J7110218D-2025", findings)
        self.assertIn("错误的条款：无", findings)

    def test_wrong_clause_is_written_with_both_texts(self) -> None:
        manual = [
            dialogue.ManualItem(
                "5.1.4",
                "绝缘电阻",
                stage="DV",
                number="Leg01-01",
                criteria="电阻不低于10MΩ",
            )
        ]
        conditions = [
            dialogue.StandardCondition("5.1.4", "绝缘电阻", "电阻不低于100MΩ", "电机.docx", "3", "电阻不低于100MΩ")
        ]
        sheet = dialogue.build_comparison_sheet(manual, conditions, note="")
        text = dialogue.clause_findings(sheet)
        self.assertIn("错误的条款", text)
        self.assertIn("条款 5.1.4", text)
        self.assertIn("不低于10MΩ", text)
        self.assertIn("不低于100MΩ", text)
        import io

        from openpyxl import load_workbook

        book = load_workbook(io.BytesIO(dialogue.comparison_workbook(sheet)))
        values = [cell.value for cell in book["缺少与错误"][2]]
        self.assertEqual(values[0], "错误")
        self.assertIn("10MΩ", values[6])
        self.assertIn("100MΩ", values[7])

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
        self.assertIn("缺少的条款", result["reply"])
        self.assertIn("绝缘性能试验", result["reply"])
        self.assertIn("7.7.1", result["reply"])

    def test_downloaded_file_returns_then_the_sheet_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            table = root / "测试表.txt"
            table.write_text("7.7.1 绝缘性能试验\n", encoding="utf-8")
            save = root / "标准文件"
            found = dialogue.CatalogFile("绝缘性能试验.txt", "https://8.8.8.8/a.txt", False)

            def collect(url, manual, **kwargs):
                return url, [found], "已在检索框填入 1 个标准号或文件名，搜索结果列出 1 个文件。"

            def download(url, dest, timeout=20.0):
                dest.write_text("7.7.1 绝缘性能试验\n试验条件 电阻应不低于10MΩ\n", encoding="utf-8")

            steps: list[str] = []
            with (
                mock.patch.object(dialogue, "collect_for_manual", collect),
                mock.patch.object(dialogue, "_download_standard", download),
            ):
                result = dialogue.compare_manual_file(
                    table,
                    on_step=lambda _name, detail="": steps.append(detail),
                    save_dir=save,
                )
            self.assertEqual(len(list(save.glob("*.txt"))), 1)
            self.assertEqual(len(result["saved_files"]), 1)
            self.assertIn("已生成对比表", result["reply"])
            sheet = result["tables"][0]
            standard_text = sheet["headers"].index("标准条件")
            self.assertTrue(any("不低于10MΩ" in row[standard_text] for row in sheet["rows"]))
            joined = "\n".join(steps)
            self.assertIn("交回工程", joined)
            self.assertIn("提取测试项目", joined)
            self.assertIn("对比表已写出", joined)

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
        self.assertIn("参考DV Leg01-02试验条件要求", items[2].condition)
        self.assertIn("来源：DVP&R DV Leg01-02", items[2].condition)
        self.assertIn("a）环境温度：-40℃", items[2].condition)

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

    def test_file_site_defaults_to_arsm(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ENTERPRISE_TEST_SOURCE_URL", None)
            self.assertEqual(dialogue.source_url(), "http://arsm.aurobaytech.com/home/index")

    def test_arsm_may_resolve_to_intranet(self) -> None:
        with mock.patch.object(
            dialogue.socket,
            "getaddrinfo",
            return_value=[(2, 1, 6, "", ("10.8.0.4", 0))],
        ):
            kept = dialogue.public_http_url("https://arsm.aurobaytech.com/library")
        self.assertTrue(kept.startswith("https://arsm.aurobaytech.com/"))

    def test_redirect_onto_arsm_keeps_the_file_page(self) -> None:
        def get(url: str):
            if dialogue._host_name(url) != "arsm.aurobaytech.com":
                return 302, "https://arsm.aurobaytech.com/library", b""
            return 200, "", "<a href='std.docx'>J7110137E-2024.docx</a>".encode()

        with mock.patch.object(
            dialogue.socket,
            "getaddrinfo",
            return_value=[(2, 1, 6, "", ("10.8.0.4", 0))],
        ):
            final, body, note = dialogue.follow_same_host("https://sso.aurobaytech.com/", get)
            found = dialogue.parse_catalog(body.decode("utf-8"), final)
        self.assertTrue(final.startswith("https://arsm.aurobaytech.com/library"))
        self.assertEqual(note, "已读取网址。")
        self.assertEqual([item.name for item in found], ["J7110137E-2024.docx"])
        self.assertTrue(found[0].url.startswith("https://arsm.aurobaytech.com/"))

    def test_leaving_arsm_stops(self) -> None:
        def get(_url: str):
            return 302, "https://sso.aurobaytech.com/frontend/login", b""

        with mock.patch.object(
            dialogue.socket,
            "getaddrinfo",
            return_value=[(2, 1, 6, "", ("10.8.0.4", 0))],
        ):
            with self.assertRaises(ValueError) as caught:
                dialogue.follow_same_host("https://arsm.aurobaytech.com/library", get)
        self.assertIn("其他站点", str(caught.exception))

    def test_login_words_do_not_drop_file_links(self) -> None:
        page = "<title>登录</title><a href='a.docx'>J7110137E-2024.docx</a>"

        def get(_url: str):
            return 200, "", page.encode()

        with mock.patch.object(
            dialogue.socket,
            "getaddrinfo",
            return_value=[(2, 1, 6, "", ("10.8.0.4", 0))],
        ):
            final, body, note = dialogue.follow_same_host(
                "https://arsm.aurobaytech.com/frontend/login", get
            )
            found = dialogue.parse_catalog(body.decode("utf-8"), final)
        self.assertEqual(note, "已读取网址。")
        self.assertEqual([item.name for item in found], ["J7110137E-2024.docx"])

    def test_password_form_has_no_file(self) -> None:
        page = "<form><input type='password' name='password' value='secret'></form>"
        self.assertEqual(dialogue.parse_catalog(page, "https://8.8.8.8/login"), [])

    def test_replacement_stays_on_its_own_row(self) -> None:
        page = """
        <table>
        <tr><td>有效</td><td><a href="https://8.8.8.8/good.docx">Q-JLY J7111029E-2024-低温.docx</a></td></tr>
        <tr><td>已替换</td><td><a href="https://8.8.8.8/old.docx">Q-JLY J7111029D-2019-低温.docx</a></td></tr>
        </table>
        """
        kept = dialogue.files_for_table(
            dialogue.parse_catalog(page, "https://8.8.8.8/list"),
            "标准号 J7111029",
        )
        self.assertEqual([item.name for item in kept], ["Q-JLY J7111029E-2024-低温.docx"])

    def test_unquoted_and_query_links_are_kept(self) -> None:
        page = """
        <a href=https://8.8.8.8/plain.docx>Q-JLY J7110218D-2025-电机.docx</a>
        <a href="https://8.8.8.8/download?id=9">Q-JLY J7110137E-2024-车载充电机.docx</a>
        """
        found = dialogue.parse_catalog(page, "https://8.8.8.8/list")
        self.assertEqual(
            [item.url for item in found],
            [
                "https://8.8.8.8/plain.docx",
                "https://8.8.8.8/download?id=9",
            ],
        )

    def test_file_body_is_not_cut_at_half_a_megabyte(self) -> None:
        blob = b"x" * 600_000
        self.assertEqual(dialogue._read_capped([blob], dialogue._FILE_BYTES), blob)
        with self.assertRaises(ValueError):
            dialogue._read_capped([b"abcdef"], 4)

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

    def test_relative_file_stays_in_its_directory(self) -> None:
        page = "<a href='std.docx'>J7110137E-2024.docx</a>"
        found = dialogue.parse_catalog(page, "https://8.8.8.8/library")
        self.assertEqual([item.url for item in found], ["https://8.8.8.8/library/std.docx"])

    def test_crawl_follows_folders_and_the_next_page(self) -> None:
        pages = {
            "https://8.8.8.8/list": """
                <nav><a href="https://8.8.8.8/help/">帮助</a></nav>
                <ul><li><a href="https://8.8.8.8/std/charger/">车载充电机</a></li></ul>
                <table><tr><td><a href="https://8.8.8.8/a.docx">J7110137E-2024-车载充电机.docx</a></td></tr></table>
                <a href="https://8.8.8.8/list?page=2">下一页</a>
            """.encode(),
            "https://8.8.8.8/std/charger/": b"%PDF-1.4 car charger",
            "https://8.8.8.8/list?page=2": "<a href='b.docx'>J7110218D-2025-电机.docx</a>".encode(),
        }
        seen: list[str] = []

        def fetch(url: str):
            seen.append(url)
            body = pages[url]
            return url, body, "已读取网址。"

        _landed, found, note = dialogue.crawl_catalog("https://8.8.8.8/list", fetch=fetch)
        self.assertEqual(
            [item.name for item in found],
            ["J7110137E-2024-车载充电机.docx", "车载充电机.pdf", "J7110218D-2025-电机.docx"],
        )
        self.assertNotIn("https://8.8.8.8/help/", seen)
        self.assertIn("已读取 3 页", note)

    def test_crawl_keeps_files_when_a_later_page_fails(self) -> None:
        def fetch(url: str):
            if "page=2" in url:
                raise ValueError("读取网址失败：超时")
            body = "<a href='https://8.8.8.8/a.docx'>J7110137E-2024.docx</a><a href='https://8.8.8.8/list?page=2'>下一页</a>".encode()
            return url, body, "已读取网址。"

        _landed, found, _note = dialogue.crawl_catalog("https://8.8.8.8/list", fetch=fetch)
        self.assertEqual([item.name for item in found], ["J7110137E-2024.docx"])

    def test_crawl_reads_every_page_once(self) -> None:
        pages = {
            "https://8.8.8.8/list": "<a href='https://8.8.8.8/list?page=2'>下一页</a><a href='https://8.8.8.8/a.docx'>J7110137E-2024.docx</a>",
            "https://8.8.8.8/list?page=2": "<a href='https://8.8.8.8/list?page=3'>下一页</a><a href='https://8.8.8.8/b.docx'>J7110218D-2025.docx</a>",
            "https://8.8.8.8/list?page=3": "<a href='https://8.8.8.8/c.docx'>J7110300A-2023.docx</a>",
        }
        seen: list[str] = []

        def fetch(url: str):
            seen.append(url)
            return url, pages[url].encode(), "已读取网址。"

        _landed, found, note = dialogue.crawl_catalog("https://8.8.8.8/list", fetch=fetch)
        self.assertEqual(
            [item.name for item in found],
            ["J7110137E-2024.docx", "J7110218D-2025.docx", "J7110300A-2023.docx"],
        )
        self.assertEqual(seen, list(pages))
        self.assertIn("已读取 3 页", note)
        self.assertNotIn("上限", note)

    def test_external_file_link_is_not_resolved(self) -> None:
        page = "<a href='https://example.com/a.docx'>外来.docx</a><a href='https://8.8.8.8/b.docx'>J7110137E-2024.docx</a>"
        with mock.patch.object(dialogue.socket, "getaddrinfo", side_effect=AssertionError("dns")):
            files = dialogue.parse_catalog(page, "https://8.8.8.8/list")
        self.assertEqual([item.name for item in files], ["J7110137E-2024.docx"])

    def test_catalog_stops_after_the_page_cap(self) -> None:
        def fetch(url: str):
            page = url.rstrip("/").rsplit("/", 1)[-1]
            number = 1 if page == "list" else int(page)
            nxt = f"<a href='https://8.8.8.8/{number + 1}'>下一页</a>" if number < 5 else ""
            body = f"{nxt}<a href='https://8.8.8.8/{number}.docx'>J7110137E-2024-{number}.docx</a>"
            return url, body.encode(), "已读取网址。"

        _landed, found, note = dialogue.crawl_catalog(
            "https://8.8.8.8/list", fetch=fetch, max_pages=2
        )
        self.assertEqual(len(found), 2)
        self.assertIn("没有继续读", note)

    def test_search_queries_use_the_standard_number(self) -> None:
        numbered = dialogue.ManualItem("7.7.1", "绝缘性能试验", standard="Q/JLY J7110137E-2024")
        named = dialogue.ManualItem("", "湿热试验", standard="企业技术条件")
        self.assertEqual(
            dialogue.search_queries([numbered, named]),
            ["J7110137E-2024", "企业技术条件"],
        )

    def test_password_form_is_not_the_search_box(self) -> None:
        page = """
        <form method="post" action="/login">
          <input type="text" name="username">
          <input type="password" name="password">
        </form>
        <form method="post" action="/search">
          <input type="text" name="keyword" placeholder="检索">
          <input type="hidden" name="csrf" value="t">
          <input type="hidden" name="password" value="no">
        </form>
        """
        found = dialogue.find_search_form(page, "https://8.8.8.8/")
        self.assertIsNotNone(found)
        action, field, method, hidden = found
        self.assertEqual(action, "https://8.8.8.8/search")
        self.assertEqual(field, "keyword")
        self.assertEqual(method, "post")
        self.assertEqual(hidden, [("csrf", "t")])

    def test_search_bar_outside_a_form_is_used(self) -> None:
        page = """
        <div class="header">
          <input type="text" placeholder="请输入标准号或标准名称" class="el-input__inner">
          <button type="button">搜索</button>
        </div>
        """
        found = dialogue.find_search_form(page, "https://8.8.8.8/home/index")
        self.assertIsNotNone(found)
        action, field, method, hidden = found
        self.assertEqual(action, "https://8.8.8.8/home/index")
        self.assertEqual(field, "keyword")
        self.assertEqual(method, "get")
        self.assertEqual(hidden, [])

    def test_file_name_box_and_empty_shell(self) -> None:
        page = """
        <div>
          <input type="text" placeholder="请输入文件名称" class="el-input__inner">
          <button type="button">查询</button>
        </div>
        """
        found = dialogue.find_search_form(page, "https://8.8.8.8/home/index")
        self.assertIsNotNone(found)
        shell = '<div id="app"></div><script src="/app.js"></script>'
        self.assertTrue(dialogue._page_is_shell(shell))
        self.assertFalse(dialogue._page_is_shell(page))
        described = dialogue._describe_page(
            "<title>登录</title><input type='password' value='secret'><input type='text' placeholder='请输入标准号'>"
        )
        self.assertIn("登录", described)
        self.assertIn("password", described)
        self.assertNotIn("secret", described)
        self.assertIn("请输入标准号", described)
        facts = "\n".join(
            dialogue._page_facts(
                "<title>标准库</title><div id='app'></div>"
                "<iframe src='/search-frame'></iframe>"
                "<input type='text' placeholder='请输入标准号' name='keyword' class='el-input__inner' value='secret'>"
                "<button>搜索</button><script src='/app.js'></script>",
                "源码",
            )
        )
        self.assertIn("请输入标准号", facts)
        self.assertIn("keyword", facts)
        self.assertIn("/search-frame", facts)
        self.assertIn("/app.js", facts)
        self.assertIn("搜索", facts)
        self.assertNotIn("secret", facts)

    def test_missing_box_logs_how_the_browser_ran(self) -> None:
        def fetch(url: str):
            return url, b'<div id="app"></div>', "已读取网址。"

        def rendered(url: str):
            return '<div id="app"></div>', [
                "脚本第 2 步启动浏览器 C:\\Edge\\msedge.exe。不读取已有登录状态，等待页面把检索框画出来。",
                "调试端口等待 8 秒。页面标题是「无标题」，正文 20 字，是空壳，输入框 0 个：没有，组件 0 个。",
            ]

        seen: list[str] = []
        manual = [dialogue.ManualItem("", "绝缘", standard="J7110137E-2024")]
        with (
            mock.patch.object(dialogue, "_fetch_page", fetch),
            mock.patch.object(dialogue, "_rendered_page", rendered),
        ):
            _landed, found, note = dialogue.collect_for_manual(
                "https://8.8.8.8/home/index",
                manual,
                on_step=lambda _name, detail="": seen.append(detail),
            )
        self.assertEqual(found, [])
        self.assertIn("没有找到检索框", note)
        joined = "\n".join(seen)
        self.assertIn("启动浏览器", joined)
        self.assertIn("空壳", joined)
        self.assertIn("输入框 0 个", joined)

    def test_search_reads_the_result_page(self) -> None:
        home = """
        <form method="get" action="/search">
          <input type="search" name="keyword" placeholder="检索">
        </form>
        """.encode()
        result = "<a href='a.docx'>Q-JLY J7110137E-2024-车载充电机.docx</a>".encode()
        seen: list[str] = []

        def fetch(url: str):
            seen.append(url)
            if "keyword=" in url:
                return url, result, "已读取网址。"
            return url, home, "已读取网址。"

        manual = [dialogue.ManualItem("", "绝缘", standard="Q/JLY J7110137E-2024")]
        _landed, found, note = dialogue.collect_for_manual("https://8.8.8.8/", manual, fetch=fetch)
        self.assertEqual([item.name for item in found], ["Q-JLY J7110137E-2024-车载充电机.docx"])
        self.assertIn("已在检索框填入 1 个标准号或文件名", note)
        self.assertTrue(any("keyword=J7110137E-2024" in url for url in seen))

    def test_search_reads_every_query_and_its_pages(self) -> None:
        home = "<form method='get' action='/search'><input type='search' name='keyword'></form>".encode()
        seen: list[str] = []

        def fetch(url: str):
            seen.append(url)
            if "J7110137E-2024" in url and "page=2" not in url:
                body = "<a href='https://8.8.8.8/search?keyword=J7110137E-2024&amp;page=2'>下一页</a><a href='https://8.8.8.8/a.docx'>J7110137E-2024.docx</a>"
            elif "page=2" in url:
                body = "<a href='https://8.8.8.8/b.docx'>J7110137E-2024-续.docx</a>"
            elif "J7110218D-2025" in url:
                body = "<a href='https://8.8.8.8/c.docx'>J7110218D-2025.docx</a>"
            else:
                body = home.decode()
            return url, body.encode(), "已读取网址。"

        manual = [
            dialogue.ManualItem("", "绝缘", standard="J7110137E-2024"),
            dialogue.ManualItem("", "超速", standard="J7110218D-2025"),
        ]
        _landed, found, note = dialogue.collect_for_manual("https://8.8.8.8/", manual, fetch=fetch)
        self.assertEqual(
            [item.name for item in found],
            ["J7110137E-2024.docx", "J7110137E-2024-续.docx", "J7110218D-2025.docx"],
        )
        self.assertIn("已在检索框填入 2 个标准号或文件名", note)
        self.assertNotIn("上限", note)
        self.assertEqual(sum("page=2" in url for url in seen), 1)

    def test_post_search_sends_only_the_query(self) -> None:
        home = """
        <form method="post" action="/search">
          <input type="text" name="keyword">
          <input type="hidden" name="csrf" value="t">
          <input type="hidden" name="password" value="no">
        </form>
        """.encode()
        sent: dict[str, object] = {}

        def fetch(url: str):
            return url, home, "已读取网址。"

        def post(action: str, data: dict[str, str]):
            sent["action"] = action
            sent["data"] = data
            body = "<a href='a.docx'>J7110137E-2024.docx</a>".encode()
            return action, body, "已读取网址。"

        manual = [dialogue.ManualItem("", "绝缘", standard="J7110137E-2024")]
        _landed, found, note = dialogue.collect_for_manual(
            "https://8.8.8.8/",
            manual,
            fetch=fetch,
            post=post,
        )
        self.assertEqual(sent["data"], {"csrf": "t", "keyword": "J7110137E-2024"})
        self.assertEqual([item.name for item in found], ["J7110137E-2024.docx"])
        self.assertIn("检索", note)

    def test_without_search_box_keeps_the_catalog(self) -> None:
        home = "<ul><li><a href='https://8.8.8.8/a.docx'>J7110137E-2024.docx</a></li></ul>".encode()

        def fetch(url: str):
            return url, home, "已读取网址。"

        manual = [dialogue.ManualItem("", "绝缘", standard="J7110137E-2024")]
        _landed, found, note = dialogue.collect_for_manual("https://8.8.8.8/list", manual, fetch=fetch)
        self.assertEqual(found, [])
        self.assertIn("没有找到检索框", note)

    def test_password_page_stops_before_any_file(self) -> None:
        home = """
        <form method="post" action="/login">
          <input type="text" name="username">
          <input type="password" name="password">
        </form>
        """.encode()

        def fetch(url: str):
            return url, home, "已读取网址。"

        manual = [dialogue.ManualItem("", "绝缘", standard="J7110137E-2024")]
        _landed, found, note = dialogue.collect_for_manual("https://8.8.8.8/home/index", manual, fetch=fetch)
        self.assertEqual(found, [])
        self.assertEqual(note, "登录尚未完成，未读取文件。")

    def test_script_search_finds_the_file_by_standard_number(self) -> None:
        home = "<div id='app'></div><script src='/app.js'></script>".encode()
        script = 'var url="/api/standard/search"; var field="fileName";'.encode()
        result = '{"rows":[{"fileName":"J7110137E-2024.docx","url":"/a.docx","status":"现行"}]}'.encode()

        def fetch(url: str):
            if url.endswith("/app.js"):
                return url, script, "已读取网址。"
            if "fileName=" in url or "keyword=" in url:
                return url, result, "已读取网址。"
            return url, home, "已读取网址。"

        manual = [dialogue.ManualItem("", "绝缘", standard="Q/JLY J7110137E-2024")]
        _landed, found, note = dialogue.collect_for_manual("https://8.8.8.8/home/index", manual, fetch=fetch)
        self.assertEqual(found, [])
        self.assertIn("没有找到检索框", note)

    def test_script_json_search_uses_the_standard_number(self) -> None:
        home = "<div id='app'></div><script src='/assets/index.js'></script>".encode()
        script = 'request({url:"/standard/pageList",method:"post",data:{standardNo:""}})'.encode()
        result = '{"rows":[{"fileName":"J7110218D-2025.pdf","downloadUrl":"/a.pdf"}]}'.encode()
        posted: list[dict[str, object]] = []

        def fetch(url: str):
            if url.endswith("/assets/index.js"):
                return url, script, "已读取网址。"
            return url, home, "已读取网址。"

        def post_json(action: str, payload: dict[str, object]):
            posted.append({"action": action, "payload": payload})
            if payload.get("standardNo") == "J7110218D-2025":
                return action, result, "已读取网址。"
            return action, b'{"rows":[]}', "已读取网址。"

        manual = [dialogue.ManualItem("", "超速", standard="Q/JLY J7110218D-2025")]
        _landed, found, note = dialogue.collect_for_manual(
            "https://8.8.8.8/home/index",
            manual,
            fetch=fetch,
            post_json=post_json,
        )
        self.assertEqual(found, [])
        self.assertEqual(posted, [])
        self.assertIn("没有找到检索框", note)

    def test_route_name_is_followed_to_its_list_api(self) -> None:
        home = "<div id='app'></div><script src='/app.js'></script>".encode()
        script = (
            'const route="/enterpriseStandard";'
            'request({url:"/enterpriseStandard/list",method:"get"})'
        ).encode()
        result = '{"code":200,"rows":[{"fileName":"J7110218D-2025.pdf","fileUrl":"/a.pdf"}]}'.encode()
        seen: list[str] = []

        def fetch(url: str):
            seen.append(url)
            if url.endswith("/app.js"):
                return url, script, "已读取网址。"
            if url.rstrip("/").endswith("/home/index"):
                return url, home, "已读取网址。"
            if "/enterpriseStandard/list" in url and "standardNo=J7110218D-2025" in url:
                return url, result, "已读取网址。"
            if url.rstrip("/").endswith("/enterpriseStandard") or "/enterpriseStandard?" in url:
                return url, home, "已读取网址。"
            return url, b"<p>empty</p>", "已读取网址。"

        def post_json(action: str, payload: dict[str, object]):
            return action, b'{"code":200,"rows":[]}', "已读取网址。"

        manual = [dialogue.ManualItem("", "超速", standard="Q/JLY J7110218D-2025")]
        _landed, found, note = dialogue.collect_for_manual(
            "https://8.8.8.8/home/index",
            manual,
            fetch=fetch,
            post_json=post_json,
        )
        self.assertEqual(found, [])
        self.assertIn("没有找到检索框", note)
        self.assertFalse(any("/enterpriseStandard/list" in url for url in seen))

    def test_api_prefix_is_requested_before_the_page_route(self) -> None:
        home = "<div id='app'></div><script src='/app.js'></script>".encode()
        script = (
            'axios.defaults.baseURL="/prod-api";'
            'const route="/enterpriseStandard";'
            'request({url:"/enterpriseStandard/list",method:"get"})'
        ).encode()
        result = '{"code":200,"rows":[{"standardNo":"J7110218D-2025","fileName":"规范.pdf","fileUrl":"/a.pdf"}]}'.encode()

        def fetch(url: str):
            if url.endswith("/app.js"):
                return url, script, "已读取网址。"
            if "/prod-api/enterpriseStandard/list" in url and "standardNo=J7110218D-2025" in url:
                return url, result, "已读取网址。"
            return url, home, "已读取网址。"

        def post_json(action: str, payload: dict[str, object]):
            return action, home, "已读取网址。"

        manual = [dialogue.ManualItem("", "超速", standard="Q/JLY J7110218D-2025")]
        _landed, found, note = dialogue.collect_for_manual(
            "https://8.8.8.8/home/index",
            manual,
            fetch=fetch,
            post_json=post_json,
        )
        self.assertEqual(found, [])
        self.assertIn("没有找到检索框", note)

    def test_login_wall_is_named_and_credentials_stay_out(self) -> None:
        home = "<div id='app'></div><script src='/app.js'></script>".encode()
        script = 'request({url:"/enterpriseStandard/list",method:"get"})'.encode()
        denied = '{"code":401,"msg":"认证失败，无法访问系统资源"}'.encode()

        def fetch(url: str):
            if url.endswith("/app.js"):
                return url, script, "已读取网址。"
            if url.rstrip("/").endswith("/home/index"):
                return url, home, "已读取网址。"
            return url, denied, "已读取网址。"

        def post_json(action: str, payload: dict[str, object]):
            return action, denied, "已读取网址。"

        manual = [dialogue.ManualItem("", "超速", standard="Q/JLY J7110218D-2025")]
        _landed, found, note = dialogue.collect_for_manual(
            "https://8.8.8.8/home/index",
            manual,
            fetch=fetch,
            post_json=post_json,
        )
        self.assertEqual(found, [])
        self.assertIn("没有找到检索框", note)
        self.assertNotIn("code=401", note)

    def test_empty_script_api_keeps_files_on_the_page(self) -> None:
        home = (
            "<div id='app'></div><script src='/app.js'></script>"
            "<a href='https://8.8.8.8/a.docx'>J7110137E-2024.docx</a>"
        ).encode()
        script = 'var url="/api/standard/search";'.encode()

        def fetch(url: str):
            if url.endswith("/app.js"):
                return url, script, "已读取网址。"
            return url, b"<p>empty</p>" if "search?" in url or "keyword=" in url else home, "已读取网址。"

        def post_json(action: str, payload: dict[str, object]):
            return action, b'{"rows":[]}', "已读取网址。"

        manual = [dialogue.ManualItem("", "绝缘", standard="J7110137E-2024")]
        _landed, found, note = dialogue.collect_for_manual(
            "https://8.8.8.8/home/index",
            manual,
            fetch=fetch,
            post_json=post_json,
        )
        self.assertEqual(found, [])
        self.assertIn("没有找到检索框", note)

    def test_collect_reports_the_stage(self) -> None:
        seen: list[str] = []

        def fetch(url: str):
            return url, b"<p>plain</p>", "已读取网址。"

        manual = [dialogue.ManualItem("", "绝缘", standard="J7110137E-2024")]
        dialogue.collect_for_manual(
            "https://8.8.8.8/home/index",
            manual,
            fetch=fetch,
            on_step=lambda name, detail="": seen.append(name),
        )
        self.assertEqual(seen[0], "find")
        self.assertIn("search", seen)

    def test_comparison_workbook_is_an_excel_file(self) -> None:
        sheet = {
            "title": "对比表",
            "headers": ["试验项目", "对比"],
            "rows": [["绝缘", "对应"]],
        }
        data = dialogue.comparison_workbook(sheet)
        self.assertTrue(data.startswith(b"PK"))

    def test_name_only_row_survives_beside_a_standard_number(self) -> None:
        page = """
        <a href="https://8.8.8.8/a.docx">Q-JLY J7110137E-2024-车载充电机.docx</a>
        <a href="https://8.8.8.8/b.docx">低温贮存试验.docx</a>
        """
        files = dialogue.parse_catalog(page, "https://8.8.8.8/list")
        items = [
            dialogue.ManualItem("", "绝缘", standard="Q/JLY J7110137E-2024"),
            dialogue.ManualItem("", "低温贮存", standard="企业技术条件"),
        ]
        kept = dialogue.files_for_items(files, items)
        self.assertEqual(
            [item.name for item in kept],
            ["Q-JLY J7110137E-2024-车载充电机.docx", "低温贮存试验.docx"],
        )

    def test_numbered_page_and_html_folder_are_followed(self) -> None:
        pages = {
            "https://8.8.8.8/list.html": """
                <nav><a href="https://8.8.8.8/help.html">帮助</a></nav>
                <ul><li><a href="https://8.8.8.8/std/charger/index.html">车载充电机</a></li></ul>
                <a href="https://8.8.8.8/list_2.html">2</a>
                <a href="https://8.8.8.8/a.docx">J7110137E-2024.docx</a>
            """.encode(),
            "https://8.8.8.8/std/charger/index.html": "<a href='https://8.8.8.8/b.docx'>J7110218D-2025.docx</a>".encode(),
            "https://8.8.8.8/list_2.html": "<a href='https://8.8.8.8/c.docx'>J7110300A-2023.docx</a>".encode(),
        }
        seen: list[str] = []

        def fetch(url: str):
            seen.append(url)
            return url, pages[url], "已读取网址。"

        _landed, found, _note = dialogue.crawl_catalog("https://8.8.8.8/list.html", fetch=fetch)
        self.assertEqual(
            [item.name for item in found],
            ["J7110137E-2024.docx", "J7110218D-2025.docx", "J7110300A-2023.docx"],
        )
        self.assertNotIn("https://8.8.8.8/help.html", seen)

    def test_word_table_cells_are_read(self) -> None:
        from docx import Document

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "std.docx"
            document = Document()
            table = document.add_table(rows=2, cols=2)
            table.rows[0].cells[0].text = "7.7.1"
            table.rows[0].cells[1].text = "绝缘性能试验"
            table.rows[1].cells[0].text = "试验条件"
            table.rows[1].cells[1].text = "温度 25℃"
            document.save(path)
            conditions = dialogue.conditions_from_pages(dialogue._pages_of(path), path.name)
        self.assertTrue(any(item.clause_id == "7.7.1" and "温度 25℃" in item.condition for item in conditions))

    def test_legacy_doc_text_is_read(self) -> None:
        page = "<a href='https://8.8.8.8/a.doc'>Q-JLY J7110137D-2019-车载充电机.doc</a>"
        found = dialogue.parse_catalog(page, "https://8.8.8.8/list")
        self.assertEqual([item.name for item in found], ["Q-JLY J7110137D-2019-车载充电机.doc"])
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "std.doc"
            path.write_bytes("7.7.1 绝缘性能试验\n试验条件：温度 25℃".encode("utf-16le"))
            conditions = dialogue.conditions_from_pages(dialogue._pages_of(path), path.name)
        self.assertTrue(any(item.clause_id == "7.7.1" and "温度 25℃" in item.condition for item in conditions))

    def test_every_dvp_sheet_is_read(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "电机.xlsx"
            book = Workbook()
            first = book.active
            first.title = "P1"
            first.append(["序号 / No.", "试验项目 / Test Name", "试验标准号及名称 / Test Spec.", "目标要求 / （评定依据） / Test Criteria"])
            first.append(["零件名称： / Part Name", "发电机定子总成"])
            first.append(["DV试验阶段"])
            first.append(["1.1", "超速", "Q/JLY J7110218D-2025", "持续时间不少于2min"])
            second = book.create_sheet("P3")
            second.append(["序号 / No.", "试验项目 / Test Name", "试验标准号及名称 / Test Spec.", "目标要求 / （评定依据） / Test Criteria"])
            second.append(["零件名称： / Part Name", "驱动电机转子总成"])
            second.append(["DV试验阶段"])
            second.append(["1.1", "超速", "Q/JLY J7110218D-2025", "持续时间不少于2min"])
            book.save(path)
            book.close()
            items = dialogue.read_manual_table(path)
        self.assertEqual([item.sheet for item in items], ["P1 发电机定子总成", "P3 驱动电机转子总成"])
        self.assertEqual([item.name for item in items], ["超速", "超速"])
        self.assertEqual([item.standard for item in items], ["Q/JLY J7110218D-2025", "Q/JLY J7110218D-2025"])
        sheet = dialogue.build_comparison_sheet(items, [], note="")
        self.assertEqual(sheet["headers"], list(dialogue.COMPARE_HEADERS_OUT))
        self.assertEqual([row[0] for row in sheet["rows"]], ["DV", "DV"])
        origin = sheet["headers"].index("来源")
        self.assertIn("P1 发电机定子总成", sheet["rows"][0][origin])
        self.assertIn("P3 驱动电机转子总成", sheet["rows"][1][origin])

    def test_catalog_sheet_fills_the_standard_and_method(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "电控.xlsx"
            book = Workbook()
            plan = book.active
            plan.title = "DVP&R"
            plan.append(["序号 / No.", "试验项目 / Test Name", "试验标准号及名称 / Test Spec.", "试验条件 / Test Condition", "目标要求（评定依据） / Test Criteria"])
            plan.append(["DV试验阶段"])
            plan.append(["Leg01-02", "低温储存", "=VLOOKUP(B3,TestCaseSelection!B:D,2,FALSE)", "参考DV Leg01-01试验条件要求", "=VLOOKUP(B3,TestCaseSelection!B:D,3,FALSE)"])
            plan.append(["Leg01-01", "五点功能", "", "工作模式：4.2", "功能状态应符合 A 级要求"])
            catalog = book.create_sheet("TestCaseSelection")
            catalog.append(["序号", "试验项目", "标准", "要求"])
            catalog.append(["2", "低温储存", "按Q/JLY J7111029E-2024 5.3.1要求\n温度保持8小时", "满足功能状态 A"])
            modes = book.create_sheet("总成-电源平台工况定义说明")
            modes.append(["工作模式定义", "ISO 16750-1-2023", "4.2", "模拟整车连接线束", "UA", "UX", "持续功率110kW"])
            modes.append(["功能状态等级", "ISO 16750-1-2023", "Class A", "试验期间和之后均满足设计要求"])
            book.save(path)
            book.close()
            items = dialogue.read_manual_table(path)
        cold, points = items
        self.assertEqual(cold.standard, "按Q/JLY J7111029E-2024 5.3.1要求")
        self.assertIn("5.3.1", cold.clause_id)
        self.assertIn("来源：TestCaseSelection\n温度保持8小时", cold.condition)
        self.assertEqual(cold.criteria, "来源：TestCaseSelection\n满足功能状态 A")
        self.assertIn("来源：总成-电源平台工况定义说明", points.condition)
        self.assertIn("工作模式4.2", points.condition)
        self.assertIn("110kW", points.condition)
        self.assertIn("功能状态A", points.condition.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
