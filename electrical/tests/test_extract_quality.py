"""抽取提准：拒流程语、堵串线冲突组。"""
from __future__ import annotations

import re
import unittest

from electrical.extract import (
    ExtractAuthError,
    ExtractError,
    _assistant_text,
    _cell_from_item,
    _chunk_fields,
    _derived_fits_field,
    _value_in_source,
    _clause_for_index,
    _downgrade_ocr_excerpt,
    _excerpt_index,
    _field_conflict_group,
    _field_needles,
    _has_printed_page_markers,
    _heading_clause_before,
    _is_junk_value,
    _is_process_language,
    _llm_chunk_budget,
    _looks_like_ocr_garbage,
    _main_extract_prompt,
    _name_match_tokens,
    _normalize_page,
    _page_blocks,
    _page_for_index,
    _clause_token,
    _parallel_workers,
    _parse_model_json,
    _rule_cells,
    _score_block,
    _select_chunks,
    _scrub_drive_boost_if_charge_spec,
    _fill_peak_bemf_from_motors,
    _collect_off_list_requirements,
    _is_off_list_process,
    _maps_to_template_field,
    _split_off_list_item,
    _store_cell,
    _strip_running_header,
    _value_fits_field,
    is_off_list_requirement,
    should_send_chunk_to_model,
)
from electrical.schema import (
    STATUS_FOUND,
    STATUS_MISS,
    STATUS_PARTIAL,
    ExtractedCell,
    empty_template_rows,
    finalize_retrieval_statuses,
    load_template_fields,
)


class JunkAndFitTests(unittest.TestCase):
    def test_item_4_scope_renamed_to_traction_boost(self) -> None:
        from electrical.extract import _bind_seq, _store_cell

        load_template_fields.cache_clear()
        names = {spec.seq: spec.name for spec in load_template_fields()}
        self.assertEqual(names[4], "设计范围是否包含行车升压功能")
        self.assertNotIn(18, names)
        self.assertNotIn(19, names)
        self.assertNotIn(26, names)
        self.assertNotIn(27, names)
        self.assertIn(13, names)
        self.assertIn(14, names)
        self.assertIn(15, names)
        self.assertIn(16, names)
        self.assertEqual(len(names), 116)
        rows = {c.seq: c for c in empty_template_rows()}
        self.assertEqual(_bind_seq(0, "设计范围是否包含充电升压功能", rows), 4)
        chunk = "Charging Buck/Boost Function Requirements充电升压/降压功能需求"
        _store_cell(
            ExtractedCell(
                name="设计范围是否包含充电升压功能",
                value="是（含充电 Boost/Buck 功能）",
                excerpt=chunk,
                confidence=0.9,
            ),
            chunk,
            rows,
            [],
            set(),
            {},
            {},
        )
        self.assertEqual(rows[4].name, "设计范围是否包含行车升压功能")
        self.assertIn("Boost/Buck", rows[4].value or "")

    def test_process_language_rejected(self) -> None:
        self.assertTrue(_is_process_language("具体数值以电机实际达成为准"))
        self.assertTrue(_is_junk_value("硬件设计后需提供计算，并经吉利认可", "静态电流"))
        self.assertFalse(_is_junk_value("125kW@320V-450V@10S", "P1峰值功率"))
        self.assertFalse(
            _is_junk_value(
                "电源开关须承受 P1/P3 反电动势最大值；具体以电机实际达成为准",
                "P1反电动势（Back EMF）",
            )
        )

    def test_excerpt_index_prefers_longest_prefix_twin(self) -> None:
        """6.5.7.1（P1）与 6.5.8.1（P3）前 48 字相同，P3 摘录必须落到 P3 句。"""
        p1 = (
            "6.5.7.1 AC Active short circuit current PEI P1\n\n"
            "During active short circuit the maximum allowed steady state current in the P1 EM is 250A rms. "
            "The requirement is applicable in the complete working speed range.\n\n"
        )
        p3 = (
            "6.5.8.1 AC Active short circuit current PEI P3  P3逆变器主动短路电流\n\n"
            "During active short circuit the maximum allowed continuous current in the P3 EM is 310 Arms;"
            "The requirement is applicable in the complete working speed range. PEI P3 shall be able to "
            "perform under this condition during 20s.XCM must handle transient currents around 1300Arms@1ms "
            "when entering activating ASC;Active short circuit may be performed on the two XCM outputs, "
            "P1 EM and P3 EM, at the same time.\n\n"
        )
        chunk = p1 + p3
        p3_excerpt = "During active short circuit the maximum allowed continuous current in the P3 EM is 310 Arms"
        p1_excerpt = "During active short circuit the maximum allowed steady state current in the P1 EM is 250A rms"
        self.assertEqual(_excerpt_index(chunk, p3_excerpt), chunk.index(p3_excerpt))
        self.assertEqual(_excerpt_index(chunk, p1_excerpt), chunk.index(p1_excerpt))
        # 只给前 48 字（两处同形）时退回首次出现，不抛错
        self.assertEqual(_excerpt_index(chunk, p3_excerpt[:48]), chunk.index(p3_excerpt[:48]))

        rows = {c.seq: c for c in empty_template_rows()}
        extra: list[ExtractedCell] = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        by_name = {c.name: c for c in rows.values()}
        asc = by_name["P3 ASC电流能力（是否整机提供？）"]
        inv = by_name["P3逆变器交流主动短路电流"]
        self.assertIn("310", asc.value)
        self.assertNotIn("250", asc.value)
        self.assertIn("P3 EM is 310", asc.excerpt)
        self.assertEqual(asc.clause, "6.5.8.1")
        self.assertIn("310", inv.value)
        self.assertIn("1300", inv.value)
        self.assertEqual(inv.clause, "6.5.8.1")
        # P1 格不得被 P3 的 310 串入（P1 规则本身要中文句才触发，整份 DPR 仅规则跑已验证不变）
        self.assertNotIn("310", by_name["P1 ASC电流能力"].value)

    def test_boost_output_performance_rejects_efficiency_block(self) -> None:
        """#61 Boost输出性能不得抄 #62 升压效率整段（2026-09-16 13:26 那份）。"""
        name = "Boost输出性能"
        efficiency = (
            "最高效率：99.5%@直通，99%@升压；输入功率5-50kW，效率≥99.1%@300V直通；"
            "输入功率5-60kW，效率≥98.8%@升压至340V；输入功率5-40kW，效率≥98.5%@升压至400-450V"
        )
        excerpt = "BOOST efficiency target　BOOST效率目标 最高效率： 99.5%@直通， 99%@升压"
        self.assertFalse(_value_fits_field(name, efficiency, excerpt))
        self.assertFalse(
            _value_fits_field(
                name, "Max efficiency 99.5% bypass / 99% boost", "BOOST efficiency target"
            )
        )
        # 输出侧电压/功率仍收；效率整段仍归 #62
        self.assertTrue(
            _value_fits_field(
                name,
                "450V（升压器目标输出）",
                "Target output voltage of booster 升压器的目标输出电压 | 450 | V",
            )
        )
        self.assertTrue(
            _value_fits_field(
                name,
                "峰值 180kW（450V×400A@10s）",
                "BOOST input peak current BOOST输入峰值电流 | 400A@10S | A",
            )
        )
        self.assertTrue(_value_fits_field("升压效率", efficiency, excerpt))
        self.assertFalse(
            _value_fits_field(
                name,
                "The XCM shall be able to boost the HV input voltage to a higher voltage "
                "in order to improve the TM performance when HVDC input voltage is low.",
                "The XCM shall be able to boost the HV input voltage to a higher voltage "
                "in order to improve the TM performance when HVDC input voltage is low.",
            )
        )
        self.assertTrue(_is_junk_value(
            "The XCM shall be able to boost the HV input voltage to a higher voltage "
            "in order to improve the TM performance when HVDC input voltage is low.",
            name,
        ))

    def test_od_upshift_rejects_cooling_with_od(self) -> None:
        excerpt = (
            "Cooling flow resistance requirement for XCM: ≤ 35Kpa@65 ℃@10L/min;"
            "（with OD）, The pressure resistance of the waterway is ≥ 200KPa."
        )
        name = "设计范围是否包含OD上移功能"
        self.assertTrue(_is_junk_value("with OD", name))
        self.assertFalse(_value_fits_field(name, "with OD", excerpt))
        self.assertFalse(
            _value_fits_field("设计范围是否包含OD本体物理集成", "with OD", excerpt)
        )
        self.assertTrue(
            _value_fits_field(
                name,
                "是；需提供推荐电路",
                "OD上移功能：需提供OD上移动推荐电路，若不提供需确认平台电路是否可直接使用。",
            )
        )
        self.assertTrue(
            _value_fits_field(
                "设计范围是否包含OD本体物理集成",
                "是（重量目标含OD模块）",
                "The weight of the XCM shall be less than 20.2kg(With OD Module).",
            )
        )
        rows = {c.seq: c for c in empty_template_rows()}
        _store_cell(
            ExtractedCell(
                seq=2,
                name=name,
                value="with OD",
                excerpt=excerpt,
                clause="6.2.2",
                confidence=0.85,
            ),
            excerpt,
            rows,
            [],
            set(),
            {},
            {},
        )
        self.assertFalse((rows[2].value or "").strip())

    def test_peak_duration_not_current(self) -> None:
        self.assertFalse(
            _value_fits_field(
                "P1峰值功率持续时间",
                "10S",
                "BOOST input peak current 400A@10S",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "P1峰值功率持续时间",
                "10s@125kW@320V-450V",
                "HVDC peak power 高压直流峰值功率 125kW@320V-450V@10S",
            )
        )

    def test_boost_performance_needs_metric(self) -> None:
        self.assertFalse(
            _value_fits_field(
                "Boost输出性能",
                "三种工作模式：Boost 升压 / bypass 直通 / BUCK 降压",
                "需要具备三种作工作模式",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "Boost输出性能",
                "≤±16 V @输入300~380V输出450V",
                "BOOST output ripple voltage升压输出纹波电压",
            )
        )

    def test_conflict_groups(self) -> None:
        self.assertEqual(
            _field_conflict_group("P3峰值扭矩/时间/对应转速范围"),
            "peak_torque",
        )
        self.assertEqual(_field_conflict_group("P3堵转扭矩/时间"), "stall_torque")
        self.assertNotEqual(
            _field_conflict_group("P1峰值功率持续时间"),
            _field_conflict_group("BOOST输入峰值电流"),
        )
        self.assertNotEqual(
            _field_conflict_group("直流母线纹波电压要求"),
            _field_conflict_group("高压安全-纹波电压"),
        )
        self.assertNotEqual(
            _field_conflict_group("直流母线纹波电压要求"),
            _field_conflict_group("升压纹波电压"),
        )
        self.assertNotEqual(
            _field_conflict_group("P1反电动势（Back EMF）"),
            _field_conflict_group("P3 反电动势（Back EMF）"),
        )

    def test_chunk_budget_scales(self) -> None:
        self.assertEqual(_llm_chunk_budget(10), 6)
        self.assertEqual(_llm_chunk_budget(30), 8)
        self.assertEqual(_llm_chunk_budget(50), 12)
        self.assertEqual(_llm_chunk_budget(80), 14)

    def test_markdown_table_page_scores_higher(self) -> None:
        table = (
            "## 第 8 页\n"
            "| Item | Value |\n"
            "| --- | --- |\n"
            "| HVDC bus voltage | 380 Vdc |\n"
            "| Peak power | 80 kW |\n"
        )
        prose = "## 第 2 页\nRevision history updated by supplier.\n"
        self.assertGreater(_score_block(table), _score_block(prose))

    def test_scan_chunk_budget_is_higher(self) -> None:
        ocr = "[本页为本机 OCR]\nHVDC 400 V\n"
        self.assertEqual(_llm_chunk_budget(80, ocr), 24)
        self.assertEqual(_llm_chunk_budget(50, ocr), 24)

    def test_strip_horse_header_keeps_body(self) -> None:
        text = (
            "## 第 63 页\n\n[本页为本机 OCR]\nHORSE\nDocument Name\n"
            "4LDHT260 PCM DESIGN PREREQUISITES\nDocument Type DPR\n"
            "Prerelease\nIssue 001\nVolume No /\nPage No\n63 (110)\n"
            "6.5.1 LVDC Voltage Range\nThe PCM voltage range according to ISO 16750-2:CodeA(6~16V)\n"
        )
        stripped = _strip_running_header(text)
        self.assertIn("6.5.1 LVDC Voltage Range", stripped)
        self.assertNotIn("Document Name", stripped)
        self.assertIn("## 第 63 页", stripped)

    def test_select_chunks_covers_more_ocr_pages(self) -> None:
        pages = []
        pad = "HVDC bus voltage 400 V inverter asil D coolant 10 LPM active discharge 1s. " * 25
        for i in range(1, 51):
            pages.append(
                f"## 第 {i} 页\n[本页为本机 OCR]\n{pad}\npeak power {100 + i} kW\n"
            )
        chunks = _select_chunks("\n".join(pages))
        self.assertGreaterEqual(len(chunks), 16)
        blob = "\n".join(chunks)
        self.assertGreaterEqual(blob.count("peak power"), 30)

    def test_select_chunks_by_gap_reaches_general_requirement_pages(self) -> None:
        """按空缺选段：性能词打分低的「通用要求」页（振动/寿命/海拔）也要进模型。"""
        import electrical.extract as ex
        from electrical.schema import empty_template_rows

        loud = "HVDC bus voltage 400 V inverter current 250 Arms peak power 120 kW torque 300 Nm. " * 30
        pages = [f"## 第 {i} 页\n{loud}\n" for i in range(1, 40)]
        pages.append("## 第 40 页\n5.3 Vibration 振动\nThe XCM shall withstand random vibration per J030600.\n")
        pages.append("## 第 41 页\n5.4 Life 寿命\nQualification life 15 years or 250000 km.\n")
        pages.append("## 第 42 页\n5.5 Altitude 海拔\nOperation altitude up to 5000 m above sea level.\n")
        markdown = "\n".join(pages)
        rows = {c.seq: c for c in empty_template_rows()}

        old = "\n".join(ex._select_chunks(markdown, max_chunks=8))
        new = "\n".join(ex._select_chunks(markdown, max_chunks=8, rows=rows))
        self.assertNotIn("J030600", old)
        for probe in ("J030600", "250000 km", "5000 m"):
            self.assertIn(probe, new)

        # 已填的条目不再当空缺去找段
        for cell in rows.values():
            if any(k in cell.name for k in ("振动", "寿命", "海拔")):
                cell.value = "已填"
        filled = ex._select_chunks(markdown, max_chunks=3, rows=rows)
        self.assertNotIn("J030600", "\n".join(filled))

    def test_short_latin_alias_only_whole_word_in_coverage(self) -> None:
        import electrical.extract as ex

        self.assertTrue(ex._token_present("OD", "integrated od module"))
        self.assertFalse(ex._token_present("OD", "the model shall"))
        self.assertFalse(ex._token_present("RE", "requirements"))
        self.assertTrue(ex._token_present("绝缘电阻", "控制器绝缘电阻 48 MΩ"))

    def test_weak_aliases_let_weight_and_corrosion_pages_be_found(self) -> None:
        """#73/#101 重量、#74/#102 防腐 的别名都在词典 weak 层（同槽共享，进不了 strong）。
        找页与 prompt 认条要用上它们；但「质量 / 涂层 / 表面处理」这类泛词最多算顺带提及。"""
        import electrical.extract as ex
        from electrical.schema import load_template_fields

        by_name = {s.name: s for s in load_template_fields()}
        weight, corrosion = by_name["控制器重量"], by_name["防腐等级"]
        self.assertTrue(weight.weak_aliases and corrosion.weak_aliases)
        self.assertIn("质量", ex._capped_weak_tokens(weight.name, weight.weak_aliases))
        self.assertNotIn("重量目标", ex._capped_weak_tokens(weight.name, weight.weak_aliases))
        self.assertIn("涂层", ex._capped_weak_tokens(corrosion.name, corrosion.weak_aliases))

        page = "2.3.1 Weight 重量目标\nThe weight of the XCM shall be less than 20.2kg (with OD module).\n"
        self.assertEqual(ex._block_covers(page, [weight]).get(weight.seq), 2)
        noise = "供应商质量管理体系应满足 IATF 16949:2016，质量目标见附件 3。"
        self.assertLessEqual(ex._block_covers(noise, [weight]).get(weight.seq, 0), 1)
        fields, hit = ex._chunk_fields(page, None)
        self.assertTrue(hit)
        self.assertIn("控制器重量", fields)

        corr = "4.2.1 Corrosion 防腐等级\nThe XCM shall meet corrosion class F3 per Q/JL J160003-2024.\n"
        self.assertEqual(ex._block_covers(corr, [corrosion]).get(corrosion.seq), 2)

    def test_token_strength_prefers_value_bearing_page(self) -> None:
        import electrical.extract as ex

        spec_line = "5.3 Vibration: random vibration 27.8 m/s² for 8 h per axis"
        mention = "see also the vibration chapter for details"
        self.assertEqual(ex._token_strength("vibration", spec_line, spec_line.lower()), 2)
        self.assertEqual(ex._token_strength("vibration", mention, mention.lower()), 1)
        self.assertEqual(ex._token_strength("vibration", "nothing here", "nothing here"), 0)

    def test_unpaginated_docx_does_not_invent_page_one(self) -> None:
        body = (
            "weight of the XCM shall be less than 20.2kg(With OD Module)\n"
            "The XCM shall be able to boost the HV input voltage\n"
            "控制器高压回路与地之间（外壳）绝缘电阻应当不小于48兆欧\n"
        ) * 120
        fake = "## 第 1 页\n" + body
        self.assertFalse(_has_printed_page_markers(fake))
        self.assertEqual(_page_for_index(fake, 200), "")
        self.assertEqual(_normalize_page("1", fake), "")
        trailing = body + "\n## 第 1 页\n[本页为本机 OCR]\nlogo\n## 第 2 页\n[本页为本机 OCR]\nicon\n"
        self.assertEqual(_page_for_index(trailing, 200), "")
        self.assertEqual(_normalize_page("", trailing), "")
        blocks = _page_blocks(fake)
        self.assertTrue(blocks)
        self.assertTrue(all(page == 0 for page, _text in blocks))
        chunks = _select_chunks(fake)
        self.assertGreaterEqual(len(chunks), 2)

    def test_printed_page_markers_still_used(self) -> None:
        text = "## 第 78 页\n控制器高压回路与地之间（外壳）绝缘电阻应当不小于48兆欧\n"
        self.assertTrue(_has_printed_page_markers(text))
        self.assertEqual(_page_for_index(text, 10), "78")

    def test_digital_draft_still_sends_empty_fields_to_model(self) -> None:
        self.assertTrue(should_send_chunk_to_model("1.工作电压、12.绝缘电阻"))
        self.assertFalse(should_send_chunk_to_model(""))
        self.assertFalse(should_send_chunk_to_model("   "))

    def test_parallel_workers_clamped(self) -> None:
        import os

        self.addCleanup(os.environ.pop, "SPEC_SHEET_EXTRACT_PARALLEL", None)
        os.environ["SPEC_SHEET_EXTRACT_PARALLEL"] = "9"
        self.assertEqual(_parallel_workers(), 4)
        os.environ["SPEC_SHEET_EXTRACT_PARALLEL"] = "0"
        self.assertEqual(_parallel_workers(), 1)
        os.environ["SPEC_SHEET_EXTRACT_PARALLEL"] = "3"
        self.assertEqual(_parallel_workers(), 3)

    def test_chunk_fields_hit_flag(self) -> None:
        _text, hit = _chunk_fields("额定电压 400V 直流母线工作电压", None)
        self.assertTrue(hit)
        _text2, hit2 = _chunk_fields("hello world xyz", None)
        self.assertFalse(hit2)

    def test_chunk_without_field_hit_is_not_sent_to_model(self) -> None:
        rows = {cell.seq: cell for cell in empty_template_rows()}
        fields, hit = _chunk_fields(
            "Document change history and reviewer signature.",
            rows,
        )
        self.assertFalse(hit)
        self.assertEqual(fields, "")
        self.assertFalse(should_send_chunk_to_model(fields))

    def test_chunk_with_reliable_hit_is_still_sent_to_model(self) -> None:
        rows = {cell.seq: cell for cell in empty_template_rows()}
        fields, hit = _chunk_fields("直流母线工作电压范围为 250V 至 450V", rows)
        self.assertTrue(hit)
        self.assertIn("工作电压", fields)
        self.assertTrue(should_send_chunk_to_model(fields))

    def test_parse_model_json_fallback(self) -> None:
        def boom(prompt, timeout=0):
            raise ExtractError("nope")

        self.assertEqual(
            _parse_model_json(boom, "a", 1.0),
            {"rows": [], "_parse_failed": True},
        )
        calls: list[str] = []

        def once(prompt, timeout=0):
            calls.append(prompt)
            if "fallback" in prompt:
                return '{"rows":[]}'
            raise ExtractError("nope")

        data = _parse_model_json(once, "main", 1.0, fallback_prompt="fallback")
        self.assertEqual(data, {"rows": []})
        self.assertEqual(len(calls), 2)

        self.assertEqual(
            _parse_model_json(
                boom,
                "main",
                1.0,
                fallback_prompt="also fails",
            ),
            {"rows": [], "_parse_failed": True},
        )

    def test_parse_model_json_does_not_swallow_auth(self) -> None:
        def boom(prompt, timeout=0):
            raise ExtractAuthError("识别未授权，请退出后重新登录再出表。")

        with self.assertRaises(ExtractAuthError):
            _parse_model_json(boom, "a", 1.0)
        with self.assertRaises(ExtractAuthError):
            _parse_model_json(boom, "a", 1.0, fallback_prompt="fallback")

    def test_locking_rule_splits_peak_and_stall(self) -> None:
        chunk = (
            "Locking strategy: P3, 85% (Tmax * 0.85) peak torque @ 3s "
            "@65C @10L/min @(300-450)V then 2s to 50% peak for stall; Tmax=260Nm"
        )
        found = {c.name: c.value for c in _rule_cells(chunk, family="dpr")}
        self.assertNotIn("P3峰值扭矩/时间/对应转速范围", found)
        self.assertIn("P3堵转扭矩/时间", found)
        self.assertIn("堵转", found["P3堵转扭矩/时间"])
        self.assertFalse(
            _value_fits_field(
                "P3峰值扭矩/时间/对应转速范围",
                "85%(Tmax×0.85)峰值扭矩@3s@65℃@10L/min",
                chunk,
            )
        )

    def test_phase_current_asil_not_accuracy(self) -> None:
        self.assertFalse(
            _value_fits_field(
                "相电流采样精度",
                "The AC current sensors shall fulfill ASIL C according to ISO 26262-2018.",
                "Each of the inverters shall measure three AC phase currents. ASIL C.",
            )
        )

    def test_asil_uses_complete_shall_sentence(self) -> None:
        chunk = (
            "Safety requirements.\n"
            "The XCM shall be designed to fulfill ASIL C according to ISO 26262-2018.\n"
            "Next clause."
        )
        found = {c.name: c for c in _rule_cells(chunk, family="dpr")}
        self.assertIn("功能安全", found)
        full = "The XCM shall be designed to fulfill ASIL C according to ISO 26262-2018."
        self.assertEqual(found["功能安全"].value, full)
        self.assertEqual(found["功能安全"].excerpt, full)
        self.assertNotEqual(
            found["功能安全"].excerpt,
            "fulfill ASIL C according to ISO 26262",
        )

    def test_ohm_computes_insulation_from_voltage_and_current(self) -> None:
        chunk = (
            "## 第 78 页\n"
            "2.3.3.3 Insulation\n"
            "Insulation test voltage 1000 VDC, leakage current 0.1 mA.\n"
        )
        cells = [c for c in _rule_cells(chunk, family="dpr") if "绝缘" in c.name]
        self.assertTrue(cells)
        cell = cells[0]
        self.assertEqual(cell.page, "78")
        self.assertEqual(cell.clause, "2.3.3.3")
        self.assertRegex(cell.value.replace(" ", ""), r"10MΩ|10MOhm")
        self.assertIn("R=U/I", cell.note)
        self.assertIn("由物理公式计算", cell.note)
        self.assertEqual(cell.review_status, "局部对应/需人工复核")
        self.assertTrue(_value_fits_field(cell.name, cell.value, cell.excerpt))

        from electrical.extract import _store_cell
        from electrical.schema import empty_template_rows

        rows = {c.seq: c for c in empty_template_rows()}
        _store_cell(cell, chunk, rows, [], set(), {}, {})
        stored = next(c for c in rows.values() if c.value and "绝缘" in c.name)
        self.assertEqual(stored.page, "78")
        self.assertEqual(stored.clause, "2.3.3.3")
        self.assertRegex(stored.value.replace(" ", ""), r"10MΩ")
        self.assertEqual(stored.review_status, "局部对应/需人工复核")
        self.assertIn("由物理公式计算", stored.note)
        self.assertIn("R=U/I", stored.note)
        self.assertIn("代入", stored.note)

    def test_model_json_keeps_formula_note(self) -> None:
        cell = _cell_from_item(
            {
                "seq": 13,
                "name": "高压安全-绝缘电阻",
                "value": "10 MΩ",
                "note": "由物理公式计算：R=U/I（代入 1000 VDC、0.1 mA）",
            }
        )
        self.assertIsNotNone(cell)
        self.assertEqual(cell.note, "由物理公式计算：R=U/I（代入 1000 VDC、0.1 mA）")

    def test_law_sentence_without_quantities_is_not_a_value(self) -> None:
        chunk = (
            "## 第 78 页\n"
            "2.3.3.3 Insulation\n"
            "The XCM insulation design shall comply with Ohm's law.\n"
        )
        cells = [c for c in _rule_cells(chunk, family="dpr") if "绝缘" in c.name]
        self.assertFalse(cells)
        self.assertFalse(
            _value_fits_field(
                "高压安全-绝缘电阻",
                "The XCM insulation design shall comply with Ohm's law.",
                "The XCM insulation design shall comply with Ohm's law.",
            )
        )

    def test_kirchhoff_sentence_without_quantities_is_not_a_value(self) -> None:
        chunk = (
            "## 第 61 页\n"
            "6.5.11.1 LV supply\n"
            "The LV voltage and current shall satisfy Kirchhoff's current law.\n"
        )
        cells = [c for c in _rule_cells(chunk, family="dpr") if "Kirchhoff" in (c.value or "")]
        self.assertFalse(cells)

    def test_p_ui_computes_p1_peak_power(self) -> None:
        chunk = (
            "## 第 40 页\n"
            "4.2.1 P1 peak power\n"
            "PCMPI peak 350 A @ 640 V, duration 10s.\n"
        )
        cells = [c for c in _rule_cells(chunk, family="dpr") if "P=UI" in (c.note or "")]
        self.assertTrue(cells)
        self.assertEqual(cells[0].name, "P1峰值功率")
        self.assertIn("224", cells[0].value)
        self.assertIn("kW", cells[0].value)
        self.assertIn("P=UI", cells[0].note)
        self.assertEqual(cells[0].page, "40")
        self.assertEqual(cells[0].clause, "4.2.1")

    def test_torque_from_power_and_speed(self) -> None:
        chunk = (
            "## 第 41 页\n"
            "5.1.1 P1 rated torque\n"
            "P1 continuous generate 70kW@7500rpm.\n"
        )
        cells = [c for c in _rule_cells(chunk, family="dpr") if "T=9550P/n" in (c.note or "")]
        self.assertTrue(cells)
        self.assertEqual(cells[0].name, "P1额定扭矩")
        self.assertIn("Nm", cells[0].value)
        self.assertEqual(cells[0].page, "41")

    def test_rc_discharge_resistor_from_c_t_v(self) -> None:
        chunk = (
            "## 第 55 页\n"
            "6.4.1 Active discharge\n"
            "DC-link 660uF, discharge from 1000 VDC to 60 V within 2 s.\n"
        )
        cells = [c for c in _rule_cells(chunk, family="dpr") if "ln(V0/V1)" in (c.note or "")]
        self.assertTrue(cells)
        self.assertEqual(cells[0].name, "主动放电电阻")
        self.assertRegex(cells[0].value, r"Ω|Ohm")
        self.assertEqual(cells[0].page, "55")
        self.assertEqual(cells[0].clause, "6.4.1")

    def test_rc_discharge_time_from_r_c_v(self) -> None:
        chunk = (
            "## 第 56 页\n"
            "6.4.2 Passive discharge\n"
            "DC-link 660uF, 1 kΩ bleed resistor, from 1000 VDC to 60 V.\n"
        )
        cells = [c for c in _rule_cells(chunk, family="dpr") if "t=RC ln" in (c.note or "")]
        self.assertTrue(cells)
        self.assertEqual(cells[0].name, "高压安全-被动放电功能")
        self.assertRegex(cells[0].value, r"s|秒|ms")
        self.assertEqual(cells[0].page, "56")

    def test_boost_current_from_power_and_voltage(self) -> None:
        chunk = (
            "## 第 70 页\n"
            "7.1.1 Boost peak input\n"
            "Boost peak power 136kW @ 340V.\n"
        )
        cells = [c for c in _rule_cells(chunk, family="dpr") if "I=P/U" in (c.note or "")]
        self.assertTrue(cells)
        self.assertEqual(cells[0].name, "BOOST输入峰值电流")
        self.assertIn("400", cells[0].value)
        self.assertEqual(cells[0].page, "70")

    def test_heat_loss_from_efficiency_and_power(self) -> None:
        chunk = (
            "## 第 80 页\n"
            "8.1.1 Heat loss\n"
            "Controller heat loss from inverter efficiency 99.5%, input 140kW.\n"
        )
        cells = [c for c in _rule_cells(chunk, family="dpr") if "P_loss=P(1-η)" in (c.note or "")]
        self.assertTrue(cells)
        self.assertEqual(cells[0].name, "热损失")
        self.assertIn("kW", cells[0].value)
        self.assertEqual(cells[0].page, "80")

    def test_hipot_2u_plus_1000_is_not_derived(self) -> None:
        chunk = (
            "## 第 20 页\n"
            "2.1.1 HVDC operating voltage\n"
            "Operating voltage 450 VDC. Dielectric shall follow 2U+1000.\n"
        )
        cells = [c for c in _rule_cells(chunk, family="dpr") if "耐电压" in c.name]
        for cell in cells:
            self.assertNotIn("1900", cell.value.replace(" ", ""))

    def test_item_number_is_junk_but_clause_sentence_is_not(self) -> None:
        self.assertTrue(_is_junk_value("5.直流工作电压范围", "直流工作电压范围"))
        self.assertFalse(
            _is_junk_value(
                "1.冷启动最低：160V  最高：未给出",
                "直流工作电压范围",
            )
        )
        self.assertFalse(
            _is_junk_value(
                "1.峰值：450V×400A@10s",
                "升压输出功率",
            )
        )
        self.assertFalse(
            _is_junk_value(
                "1.峰值：180kW（450V×400A@10s）",
                "升压输出功率",
            )
        )
        self.assertFalse(
            _is_junk_value(
                "1.峰值功率：180kW（最大电压450V×最大电流400A@10s）",
                "升压输出功率",
            )
        )
        self.assertFalse(
            _is_junk_value(
                "The XCM insulation design shall comply with Ohm's law.",
                "高压安全-绝缘电阻",
            )
        )

    def test_boost_power_writes_kw_point_not_range(self) -> None:
        from electrical.extract import _fmt_p_ui_at, _parse_boost_power_vi

        self.assertEqual(
            _fmt_p_ui_at("450", "400", "10s"),
            "180kW（最大电压450V×最大电流400A@10s）",
        )
        self.assertEqual(
            _fmt_p_ui_at("450", "195", current_kind="cont"),
            "87.75kW（最大电压450V×持续电流195A）",
        )
        chunk = """
表1：DHTS160--boost 峰值
BOOST input peak current BOOST输入峰值电流 | 400A@10S | A |
表3：DHT160S --boost
BOOST input continue current 升压输入持续电流 | Boost:195A  ；Bypass:200A | A |
Target output voltage of booster 升压器的目标输出电压 | 450 | V
"""
        parsed = _parse_boost_power_vi(chunk)
        self.assertIsNotNone(parsed)
        body = parsed[0]
        self.assertIn("180kW", body)
        self.assertIn("87.75kW", body)
        self.assertIn("峰值功率", body)
        self.assertIn("持续稳定功率", body)
        self.assertIn("最大电压450V×最大电流400A@10s", body)
        self.assertIn("最大电压450V×持续电流195A", body)
        self.assertNotIn("64", body)
        self.assertNotRegex(body, r"200A")
        self.assertNotRegex(body, r"64\s*[–\-~～]\s*180")

    def test_section_number_is_not_page(self) -> None:
        self.assertEqual(_normalize_page("2.3.3.3", "## 第 60 页\nbody"), "60")
        self.assertEqual(_clause_token("see 2.3.3.3 Insulation"), "2.3.3.3")

    def test_reject_presence_as_accuracy_or_temp(self) -> None:
        self.assertFalse(
            _value_fits_field(
                "母线电压采样精度",
                "测量 DC Link Voltage",
                "Voltage sensor DC Link Voltage",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "冷却液温度范围",
                "从冷却方法适用的冷却液（ATF或冷却液）中连接驱动电机和逆变器",
                "connect drive motor and inverter from coolant",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "电机温度采样精度",
                "有电机温度传感器（转子/定子/线圈/磁钢测点）",
                "Motor temperature sensor",
            )
        )
        self.assertTrue(
            _value_fits_field(
                "冷却液温度范围",
                "-40℃~65℃（冷却水）",
                "Cooling Water Temperature ℃ -40~65°C",
            )
        )

    def test_reject_scan_misbinds(self) -> None:
        self.assertTrue(
            _is_junk_value(
                "冷启动时：X& /à ZJt US fik fEE FJE；有限性能时：tE FEPR #/RJ",
                "降额工作电压范围",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "直流工作电压范围",
                "945VDC或瞬态电压510VDC",
                "The unit shall not generate continuous voltages higher than 945VDC or transient voltages",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "主动放电时间",
                "after a crash ... 5 seconds or until the HV bus is below 60VDC",
                "Active discharge during crash continue to operate for 5 seconds",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "密封（IP等级）",
                "IP68",
                "Non-mated connectors shall have a protection degree of at least IP68",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "冷却液温度范围",
                "65 °C",
                "Locking strategy: P3 ... @ 65 °C cooling water temperature @ 10lpm",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "高压安全-Y电容指标",
                "需提供Y电容特性文件，电容值需吉利批准",
                "All components connected to HV network including Y-capacitors must have capacitor properties documented",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "P3峰值功率",
                "13 kW",
                "During this UDC mode the power capability shall be peak 13 kW and continues power 10 Kw.",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "直流电压过压保护",
                "XCM shall protect itself from excess voltage build-up that might be caused by the rotation of the EMs.",
                "XCM shall protect itself from excess voltage build-up that might be caused by the rotation of the EMs. This can be done for example by using active short circuit.",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "设计范围是否包含驱动升压功能",
                "是（含充电 Boost/Buck 功能）",
                "Charging Buck/Boost Function Requirements充电升压/降压功能需求",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "直流母线纹波电压要求",
                "桩侧≤1%；电池侧（单体未接入）≤20V；接入系统后≤10V",
                "纹波电压-桩侧 | ≤1%（桩侧） | 纹波电压-电池侧（单体未接入） | ≤20V",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "升压输出功率",
                "1.400V×250A@50min\n2.720V×250A@30min",
                "充电功率 | 250A/100kW@400V 50min；250A/180kW@720V 30min",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "BOOST输入峰值电流",
                "250A（低压侧，与额定同表）",
                "额定输入电流 | 250A（低压侧）",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "P1 ASC电流能力",
                "有；P1 控制器应满足 P1 电机 ASC 特性",
                "The P1 controller shall meet the ASC characteristics of the P1 motor",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "高压安全-耐电压",
                "按照Q/JLY J7111029E-2024①《汽车电气和电子零部件通用技术规范》，试验过程中...",
                "耐电压",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "加速踏板PWM频率/占空比/高低电平范围",
                "PEIs shall be prepared for a switching frequency up to 12.5 kHz",
                "Switching frequency strategy on various load cases will be set and controlled by GEELY.",
            )
        )
        self.assertTrue(
            _value_fits_field(
                "高压安全-耐电压",
                "应能耐受GB/T 18488-2024中表1所规定的直流电压，试验持续时间1min，应无击穿现象，漏电流限值应≤5mA",
                "集成式驱动电机系统耐电压要求 直流端动力端子与外壳 应无击穿现象",
            )
        )


class DielectricAliasTests(unittest.TestCase):
    def test_na_ya_is_alias_not_split(self) -> None:
        tokens = _name_match_tokens("高压安全-耐电压")
        self.assertIn("耐压", tokens)
        self.assertIn("耐电压", tokens)
        self.assertNotIn("耐电", tokens)
        self.assertNotIn("电压", tokens)
        needles = _field_needles("高压安全-耐电压")
        self.assertIn("耐压", needles)
        self.assertNotIn("耐电", needles)
        self.assertNotIn("电压", needles)

    def test_chunk_with_na_ya_selects_dielectric_field(self) -> None:
        text, hit = _chunk_fields("动力端子对壳体耐压 2000V，1min，无击穿", None)
        self.assertTrue(hit)
        self.assertIn("耐电压", text)

    def test_na_ya_with_voltage_and_duration_fits(self) -> None:
        self.assertTrue(
            _value_fits_field(
                "高压安全-耐电压",
                "耐压 2000V，1分钟，无击穿",
                "动力端子对壳体耐压 2000V，试验 1分钟，应无击穿",
            )
        )
        self.assertTrue(
            _value_fits_field(
                "高压安全-耐电压",
                "交流耐压 640Vac",
                "交流耐压 640Vac，1min",
            )
        )

    def test_continuous_supply_500v_is_not_dielectric(self) -> None:
        excerpt = "The unit must withstand continuous supply voltages of maximum 500V"
        self.assertFalse(_value_fits_field("高压安全-耐电压", "500V", excerpt))
        found = {c.name for c in _rule_cells(excerpt, family="dpr")}
        self.assertNotIn("高压安全-耐电压", found)

    def test_continuous_hvdc_body_without_heading_still_stores(self) -> None:
        """扩句后摘录常丢掉 6.6.3 标题，正文句仍要进 #14，不能被 ISO 6469 顶掉。"""
        excerpt = (
            "The unit must withstand continuous supply voltages of maximum 500V "
            "on the HVDC bus without any permanent damages."
        )
        self.assertTrue(
            _value_fits_field(
                "高压安全-耐电压",
                "母线持续供电最大 500V，无永久性损坏",
                excerpt,
            )
        )
        chunk = (
            excerpt
            + "\n6.10.3.2 HV insulation requirements 高压绝缘要求\n"
            "The XCM shall meet the withstand voltage capability test according to ISO 6469-32018. "
            "The following minimum AC test voltage of a frequency between 50 Hz and 60 Hz "
            "shall be applied for 1 min:\n"
        )
        rows = {c.seq: c for c in empty_template_rows()}
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, [], set(), {}, {})
        cell = rows[14]
        self.assertEqual(cell.clause, "6.6.3")
        self.assertIn("500V", cell.value or "")
        self.assertIn("永久性损坏", cell.value or "")
        self.assertNotIn("ISO 6469", cell.value or "")

    def test_continuous_hvdc_withstand_is_dielectric_663(self) -> None:
        chunk = (
            "### Continuous HVDC withstand voltage 连续高压直流耐压\n"
            "The unit must withstand continuous supply voltages of maximum 500V "
            "on the HVDC bus without any permanent damages.\n"
            "设备必须能承受高压直流母线上最大500V的连续供电电压，且不能造成任何永久性损坏。\n"
            "The functional status class shall be minimum C according to ISO 16750-1."
            "根据ISO 16750-1，功能状态等级应为最低C。\n"
        )
        self.assertTrue(
            _value_fits_field(
                "高压安全-耐电压",
                "母线持续供电最大 500V，无永久性损坏；功能状态最低 C（ISO 16750-1）",
                chunk,
            )
        )
        found = {c.name: c for c in _rule_cells(chunk, family="dpr")}
        self.assertIn("高压安全-耐电压", found)
        self.assertIn("500V", found["高压安全-耐电压"].value)
        self.assertIn("永久性损坏", found["高压安全-耐电压"].value)
        self.assertIn("16750-1", found["高压安全-耐电压"].value)
        self.assertEqual(found["高压安全-耐电压"].clause, "6.6.3")

    def test_operating_voltage_chunk_does_not_select_dielectric(self) -> None:
        text, hit = _chunk_fields("HVDC bus voltage 400 Vdc operating range", None)
        self.assertTrue(hit)
        self.assertNotIn("耐电压", text)

    def test_prompt_uses_aliases_not_example_values(self) -> None:
        prompt = _main_extract_prompt(
            index=0,
            total=1,
            page_count=10,
            filename="x.docx",
            fields="14.高压安全-耐电压（规格常见：耐压 / hipot / 工频耐压）",
            chunk="动力端子对壳体耐压 2000V，1min，无击穿",
        )
        self.assertIn("规格常见：耐压", prompt)
        self.assertIn("只用于认条", prompt)
        self.assertIn("行业常识", prompt)
        self.assertIn("clause", prompt)
        self.assertIn("2.3.3.3", prompt)
        self.assertIn("R=U/I", prompt)
        self.assertNotIn("用完整原句作摘要", prompt)
        self.assertNotIn("2828V", prompt)

    def test_chunk_fields_label_includes_dielectric_alias(self) -> None:
        text, hit = _chunk_fields("动力端子对壳体耐压 2000V，1min，无击穿", None)
        self.assertTrue(hit)
        self.assertIn("规格常见：", text)
        self.assertIn("耐压", text)

    def test_heading_and_transient_and_cap_still_rejected(self) -> None:
        self.assertFalse(
            _value_fits_field(
                "高压安全-耐电压",
                "动力端子对壳体/信号端子：按 GB/T 18488-2024 表1",
                "耐电压要求（电控）",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "高压安全-耐电压",
                "must withstand at least five pulses",
                "Transient HVDC withstand capability 瞬态高压直流耐压能力",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "高压安全-耐电压",
                "电容耐压 500Vdc",
                "薄膜电容 电容耐压 500Vdc",
            )
        )

    def test_rule_fills_na_ya_clause(self) -> None:
        found = {
            c.name: c.value
            for c in _rule_cells("动力端子对壳体耐压 2000V，1min，无击穿。", family="dpr")
        }
        self.assertIn("高压安全-耐电压", found)
        self.assertIn("2000V", found["高压安全-耐电压"])
        self.assertNotIn(
            "高压安全-耐电压",
            {c.name for c in _rule_cells("耐电压要求（电控）", family="dpr")},
        )


class SuperEvoFixTests(unittest.TestCase):
    CHUNK = """
| P1 continuous generate power@80℃@800V P1电机额定发电功率 | kW | 120kW@12000~15000rpm |
| P1 peak generate power@80℃@≥10s@250Arms P1电机峰值发电 | kW | 220kW@14500~16000rpm |
| P1 continuous torque (80degC) @800V P1电机额定扭矩 @80℃ | Nm | / |
| P3 continuous torque (80degC) P3电机额定扭矩 @80℃ | Nm | ≥196Nm*10min,0-4000rpm |
| P1 Back EMF(@peek speed@20℃) | Vdc | 反电势＜1200V@16500rpm，20℃，开关频率＜15kHz |
| P3 Back EMF(@peek speed@20℃) | Vdc | ＜1400V，@ 20000rpm，开关频率10kHz |
| the max speed of P3 P3电机最高转速 | rpm | 最高转速20000出功率50kW @20s，20500随转，超速22000rpm |
HVDC peak power 高压直流峰值功率
270kW@10s
HVDC continuous power高压直流持续功率
110kW
| 1 | 5501805977 | 可拓展动力域控制模块_总成 | 12 | 1 | 12 | 配置： 4pin塑料AUX连接器，2保险 |
未唤醒@仅低压上电 | 0.5 |
唤醒@IGBT开管@高低压都上电 | 3000（稳态状态，不含电子锁及差速锁） |
高压直流电压应在全电压范围内测量，测量误差小于300V为±3V，300V以上±1%。
| Q/JLY J7110779E-2023 | Specification for electromagnetic compatibility |
| Q/JLY J7110922D-2024 | Electromagnetic compatibility specification |
控制器应满足Q/JLY J7110922D-2024的要求。
"""

    def test_reject_p3_torque_on_p1(self) -> None:
        self.assertFalse(
            _value_fits_field(
                "P1额定扭矩",
                "≥196Nm*10min,0-4000rpm",
                "P3 continuous torque (80degC) P3电机额定扭矩 @80℃",
            )
        )

    def test_reject_hvdc_270_as_p1_peak(self) -> None:
        self.assertFalse(
            _value_fits_field(
                "P1峰值功率",
                "270kW@10s",
                "HVDC peak power 高压直流峰值功率 270kW@10s",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "P3峰值功率持续时间",
                "270kW@10s",
                "HVDC peak power 高压直流峰值功率 270kW@10s",
            )
        )

    def test_p3_duration_not_from_peak_kw_only(self) -> None:
        self.assertFalse(
            _value_fits_field(
                "P3峰值功率持续时间",
                "10s",
                "P3 peak drive power (@80℃) P3电机峰值驱动功率@80℃ | kW | ≥300kw @800V",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "P3峰值功率持续时间",
                "10s",
                "P3 peak drive power (@80℃) P3电机峰值驱动功率@80℃ | kW | ≥300kw @800V | "
                "P3 continuous torque (80degC) P3电机额定扭矩 @80℃ | Nm | ≥196Nm*10min | "
                "P3 peak torque (@480A@10s@870V P3电机峰值扭矩@480A@10s@870V",
            )
        )
        self.assertTrue(
            _value_fits_field(
                "P1峰值功率持续时间",
                "≥10s@220kW@14500~16000rpm",
                "P1 peak generate power@80℃@≥10s@250Arms | kW | 220kW@14500~16000rpm",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "P3 额定转速",
                "20000rpm",
                "the max speed of P3 P3电机最高转速 最高转速20000出功率",
            )
        )

    def test_p3_duration_not_from_next_torque_row(self) -> None:
        chunk = """
| P3 peak drive power (@80℃) P3电机峰值驱动功率@80℃ | kW | ≥300kw @800V |
| P3 continuous torque (80degC) P3电机额定扭矩 @80℃ | Nm | ≥196Nm*10min,0-4000rpm |
| P3 peak torque (@480A@10s@870V P3电机峰值扭矩@480A@10s@870V | Nm | ≥480Nm |
"""
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        power = next(c for c in rows.values() if c.name == "P3峰值功率")
        dur = next(c for c in rows.values() if c.name == "P3峰值功率持续时间")
        self.assertIn("300", power.value or "")
        self.assertFalse((dur.value or "").strip())
        self.assertFalse(
            _value_fits_field(
                "P1 转速需求",
                "最高转速16500rpm出功率，随转18000",
                "the max speed of P1@870V P1电机最高转速@870V | 最高转速16500rpm出功率，随转18000",
            )
        )

    def test_superevo_rules(self) -> None:
        found = {c.name: c.value for c in _rule_cells(self.CHUNK, family="dpr")}
        self.assertEqual(found.get("P1峰值功率"), "220kW@14500~16000rpm")
        self.assertEqual(found.get("P1额定功率"), "120kW@12000~15000rpm")
        self.assertNotEqual(found.get("P1额定扭矩"), "≥196Nm*10min,0-4000rpm")
        self.assertIn("196Nm", found.get("P3额定扭矩") or "")
        self.assertIn("1200V", found.get("P1反电动势（Back EMF）") or "")
        self.assertIn("1200V", found.get("反电动势峰值") or "")
        self.assertIn("1400V", found.get("P3 反电动势（Back EMF）") or "")
        self.assertIn("12kg", found.get("控制器重量") or "")
        self.assertIn("0.5mA", found.get("静态电流") or "")
        self.assertIn("3000mA", found.get("低压功耗要求") or "")
        self.assertIn("±3V", found.get("母线电压采样精度") or "")
        self.assertIn("J7110922D", found.get("EMC等级") or "")
        self.assertNotEqual(found.get("P1峰值功率"), "270kW@10s")
        self.assertNotEqual(found.get("P1额定功率"), "110kW")
        self.assertNotIn("P3 额定转速", found)


class SuperEvoChargeMisbindTests(unittest.TestCase):
    CHUNK = """
Charging Buck/Boost Function Requirements充电升压/降压功能需求
纹波电压-桩侧 | ≤1%（桩侧） | 接入系统（电池） |
| 12 | 纹波电压-电池侧（单体未接入） | ≤20V（电池侧） | 单体未接入系统(电池) |
| 13 | 纹波电压-电池侧（接入系统后） | ≤10V
额定输入电流 | 250A（低压侧）
充电功率 | 250A/100kW@400V 50min；250A/180kW@720V 30min
满功率工作 | 高压侧：1056V＜U≤1066V
满电流工作 | 低压侧：390V≤U≤1000V；高压侧：480V≤U≤1056V
允许过压保护（可自动恢复） | 高压侧：＞1066V
The P1 controller shall meet the ASC characteristics of the P1 motor
The P3 controller shall meet the ASC characteristics of the P3 motor
Transient HVDC withstand capability 瞬态高压直流耐压能力
"""

    def test_charging_table_not_drive_or_bus(self) -> None:
        found = {c.name: c.value for c in _rule_cells(self.CHUNK, family="dpr")}
        self.assertNotIn("设计范围是否包含驱动升压功能", found)
        self.assertIn("设计范围是否包含行车升压功能", found)
        self.assertNotIn("设计范围是否包含充电升压功能", found)
        self.assertNotIn("直流母线纹波电压要求", found)
        self.assertNotIn("高压安全-纹波电压", found)
        self.assertIn("升压纹波电压", found)
        self.assertIn("1%", found.get("升压纹波电压") or "")
        self.assertIn("升压输出功率", found)
        pwr = found.get("升压输出功率") or ""
        self.assertIn("100kW", pwr)
        self.assertIn("180kW", pwr)
        self.assertIn("最大电压400V×最大电流250A@50min", pwr)
        self.assertIn("最大电压720V×最大电流250A@30min", pwr)
        self.assertNotRegex(pwr, r"64\s*[–\-~～]\s*180")
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(self.CHUNK, family="dpr"):
            _store_cell(cell, self.CHUNK, rows, extra, set(), {}, {})
        stored = next(c for c in rows.values() if c.name == "升压输出功率")
        self.assertIn("100kW", stored.value)
        self.assertIn("180kW", stored.value)
        self.assertIn("最大电压400V×最大电流250A@50min", stored.value)
        self.assertIn("最大电压720V×最大电流250A@30min", stored.value)
        self.assertIn("480", found.get("升压输出电压") or "")
        self.assertNotIn("BOOST输入峰值电流", found)
        self.assertEqual(found.get("BOOST输入额定电流"), "250A（低压侧）")
        self.assertNotIn("P3额定功率相电流", found)
        self.assertEqual(found.get("BOOST最高工作电压"), "1066V（高压侧满功率上限）")
        self.assertNotIn("P1 ASC电流能力", found)
        self.assertNotIn("高压安全-耐电压", found)
        self.assertNotIn("直流电压过压保护", found)

    def test_charging_power_escaped_at_still_fills(self) -> None:
        """Word 表把 @ 存成 \\@ 时，#64 仍要收到 100kW/180kW。"""
        chunk = (
            "Charging Buck/Boost Function Requirements充电升压/降压功能需求\n"
            "充电功率\n"
            "250A/100kW\\@400V 50min；250A/180kW\\@720V 30min\n"
        )
        found = {c.name: c.value for c in _rule_cells(chunk, family="dpr")}
        pwr = found.get("升压输出功率") or ""
        self.assertIn("100kW", pwr)
        self.assertIn("180kW", pwr)
        self.assertIn("400V", pwr)
        self.assertIn("720V", pwr)

    def test_item4_prefers_charging_buck_over_hv_input(self) -> None:
        chunk = (
            self.CHUNK
            + "\n6.5.4 HV Booster\n"
            "The XCM shall be able to boost the HV input voltage to a higher voltage "
            "in order to improve the TM performance when HVDC input voltage is low.\n"
        )
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        stored = next(
            c for c in rows.values() if c.name == "设计范围是否包含行车升压功能"
        )
        self.assertIn("Boost/Buck", stored.value or "")
        self.assertNotIn("TM", stored.value or "")
        drive = next(
            c for c in rows.values() if c.name == "设计范围是否包含驱动升压功能"
        )
        self.assertIn("TM", drive.value or "")

    def test_pcm_dielectric_withstand(self) -> None:
        chunk = (
            "耐电压要求 （电控） Withstand voltage requirements of PCM "
            "应能耐受GB/T 18488-2024中表1规定的试验电压。持续时间为1min，无击穿现象，漏电流限值应≤5mA。"
            "信号端子与外壳之间，应能耐受500V的工频耐电压试验。"
        )
        found = {c.name: c.value for c in _rule_cells(chunk, family="dpr")}
        val = found.get("高压安全-耐电压") or ""
        self.assertIn("18488", val)
        self.assertIn("5mA", val)
        self.assertIn("500V", val)
        self.assertTrue(
            _value_fits_field("高压安全-耐电压", val, chunk)
        )



class InverterSrFixTests(unittest.TestCase):
    CHUNK = """
Ambient(Storage) Temperature
℃
-40~105°C
Cooling Water Temperature
℃
-40~65°C
Ambient(Operating)
Temperature
℃
-40~85°C
Hyundai/Kia Motors
"""

    def test_ambient_temps_from_capacitor_table(self) -> None:
        found = {c.name: c.value for c in _rule_cells(self.CHUNK, family="inverter")}
        self.assertEqual(found.get("工作温度范围"), "-40℃~85℃（Operating）")
        self.assertEqual(found.get("存储温度范围"), "-40℃~105℃（Storage）")
        self.assertEqual(found.get("冷却液温度范围"), "-40℃~65℃（冷却水）")
        dpr = {c.name: c.value for c in _rule_cells(self.CHUNK, family="dpr")}
        self.assertNotEqual(dpr.get("工作温度范围"), "-40℃~85℃（Operating）")

    def test_emc_hv_ripple_and_hvil_tick_are_not_pcm_fields(self) -> None:
        chunk = """
Voltage Ripple on HV
100Hz~300kHz
15Vpp/30Vpp
Region I
HVIL design compliance √
High-voltage interlock signal / Main relay & Precharge status / Collision information (CAN)
BMS Inverter Rdy / Main Relay Off Request
Rotor position
Insulation characteristics: Insulation resistance and dielectric strength (leakage current) shall meet the design specifications
"""
        found = {c.name: c.value for c in _rule_cells(chunk, family="inverter")}
        self.assertNotIn("直流母线纹波电压要求", found)
        self.assertNotIn("高压安全-纹波电压", found)
        self.assertNotIn("高压连接器保护", found)
        self.assertNotIn("P1位置传感器", found)
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="inverter"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        llm = (
            ExtractedCell(
                name="高压安全-绝缘电阻",
                value=(
                    "Insulation characteristics: Insulation resistance and "
                    "dielectric strength (leakage current) shall meet the design specifications"
                ),
                excerpt=(
                    "Insulation characteristics: Insulation resistance and "
                    "dielectric strength (leakage current) shall meet the design specifications"
                ),
                confidence=0.85,
                extra=True,
            ),
            ExtractedCell(
                name="高压连接器保护",
                value="支持 HVIL 高压互锁",
                excerpt="HVIL design compliance √",
                confidence=0.86,
                extra=True,
            ),
            ExtractedCell(
                name="P1位置传感器",
                value="转子位置 / Resolver",
                excerpt="Rotor position / High-voltage interlock signal / Main relay",
                confidence=0.86,
                extra=True,
            ),
        )
        for cell in llm:
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        ins = next(c for c in rows.values() if c.name == "高压安全-绝缘电阻")
        conn = next(c for c in rows.values() if c.name == "高压连接器保护")
        pos = next(c for c in rows.values() if c.name == "P1位置传感器")
        self.assertFalse(ins.value)
        self.assertFalse(conn.value)
        self.assertFalse(pos.value)
        self.assertFalse(
            _value_fits_field(
                "高压安全-绝缘电阻",
                "Insulation characteristics: Insulation resistance and dielectric strength "
                "(leakage current) shall meet the design specifications",
                "Insulation characteristics: Insulation resistance and dielectric strength "
                "(leakage current) shall meet the design specifications",
            )
        )

    def test_can_fd_with_lin_is_not_can_fd_only(self) -> None:
        chunk = """
CAN-FD Test Specification for Electronic Control Units
3.3.6 Software Requirements
- The inverter must support CAN, CAN-FD, and LIN communication.
Must be able to communicate in at least 3 independent CAN BUS.
"""
        found = {c.name: c.value for c in _rule_cells(chunk, family="inverter")}
        comm = found.get("通讯方式") or ""
        self.assertIn("LIN", comm)
        self.assertNotEqual(comm.strip(), "CAN-FD")
        self.assertNotEqual(comm.strip(), "CAN FD")
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="inverter"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        stored = next(c for c in rows.values() if c.name == "通讯方式")
        self.assertIn("LIN", stored.value)
        self.assertNotEqual(stored.value.strip(), "CAN FD")

    def test_life_excerpt_is_not_page_footer(self) -> None:
        chunk = (
            "Note) 2.2.3 Product Life Item Warranty Life Target : 15 years 300,000 km\n"
            "Motor/Gearbox Same Con tent\n"
        )
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="inverter"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        llm = ExtractedCell(
            name="寿命要求",
            value="15 years - 300,000 km",
            excerpt="Motor/Gearbox Same Con tent",
            confidence=0.92,
        )
        _store_cell(llm, chunk, rows, extra, set(), {}, {})
        life = next(c for c in rows.values() if c.name == "寿命要求")
        self.assertIn("15", life.value or "")
        self.assertNotRegex(life.excerpt or "", r"Motor/Gearbox Same")

    def test_partner_proposal_and_rpm_heading_are_not_values(self) -> None:
        chunk = """
Dielectric strength @60sec
Vac
Partner proposal
√ √ √
Maximum allowable RPM
"""
        found = {c.name: c.value for c in _rule_cells(chunk, family="inverter")}
        self.assertNotIn("高压安全-耐电压", found)
        self.assertNotIn("P1最高工作转速", found)
        self.assertNotIn("P3最高工作转速", found)
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        llm = (
            ExtractedCell(
                name="高压安全-耐电压",
                value="Dielectric strength @60sec  Vac  Partner proposal  √  √  √",
                excerpt="Dielectric strength @60sec  Vac  Partner proposal  √  √  √",
                confidence=0.86,
                extra=True,
            ),
            ExtractedCell(
                name="P1最高工作转速",
                value="Maximum allowable RPM",
                excerpt="Maximum allowable RPM",
                confidence=0.86,
                extra=True,
            ),
            ExtractedCell(
                name="P3最高工作转速",
                value="Maximum allowable RPM",
                excerpt="Maximum allowable RPM",
                confidence=0.86,
                extra=True,
            ),
        )
        for cell in llm:
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        hip = next(c for c in rows.values() if c.name == "高压安全-耐电压")
        p1 = next(c for c in rows.values() if c.name == "P1最高工作转速")
        p3 = next(c for c in rows.values() if c.name == "P3最高工作转速")
        self.assertFalse(hip.value)
        self.assertFalse(p1.value)
        self.assertFalse(p3.value)
        self.assertFalse(
            _value_fits_field(
                "高压安全-耐电压",
                "Dielectric strength @60sec  Vac  Partner proposal  √  √  √",
                chunk,
            )
        )
        self.assertFalse(
            _value_fits_field(
                "P1最高工作转速",
                "Maximum allowable RPM",
                "Maximum allowable RPM",
            )
        )
        self.assertTrue(_is_junk_value("Maximum allowable RPM", "P1最高工作转速"))

    HEADER = (
        "Writing Team Vehicle Product name Rev No Date PAGE Inverter model {n}/99 "
        "DHT120s Inverter Engineering Design 001 2026.06.XX\n"
    )
    CAE_PAGE = (
        "## 第 65 页\n" + HEADER.format(n=65) +
        "2) Inverter CAE Analysis Requirements\n- Negotiable by vehicle condition.\n"
        "CATEGORY CONTENTS TARGET (*May vary depending on vehicle measurement)\n"
        "MODAL > 300Hz @1ST MODE\nVIBRATION -. System specification to be distributed soon\n"
        "COOLING PASS PRESSURE DROP < 300mbar, @12lpm @65℃\n"
        "Table 3.12 Inverter CAE Analysis Requirements 65\n"
    )
    TOC_PAGE = (
        "## 第 3 页\n| Vehicle model SX3id | Product name DHT120s Inverter | PAGE 3/99 |\n"
        "| <Table of Contents> 1. Overview 2. System Requirements 2.1 Specification Management Plan |\n"
        "2.6.13 Electromagnetic Safety\n2.6.14 Product Maturity\n"
    )

    def test_body_page_with_contents_column_is_not_front_matter(self) -> None:
        """逆变器 SR 2026-09-16：表头 `CATEGORY CONTENTS TARGET` 让 Table 3.12 整页判成目录，
        冷却压降 <300mbar@12lpm 这页选段/补抽都不看，34 次调用净增 0 格。"""
        import electrical.extract as ex

        self.assertFalse(ex._is_front_matter(self.CAE_PAGE))
        self.assertFalse(
            ex._is_front_matter(
                "Any matters not specified shall follow the laws, standards, and contents stated in ES/MS.\n"
                "1) Non-functional requirements\n"
            )
        )
        self.assertTrue(ex._is_front_matter(self.TOC_PAGE))
        self.assertTrue(ex._is_front_matter("Contents\n1. Overview .......... 3\n2. Scope .......... 4\n"))
        self.assertTrue(ex._is_front_matter("| CONTENTS |\n| --- |\n| 1 Scope 3 |\n"))
        self.assertTrue(ex._is_front_matter("Revision History\nRev 0 Released\n"))

    def test_topup_dedupe_uses_stripped_header_key(self) -> None:
        """补抽判重键要和送出的段做同样的页眉剥离，否则带 running header 的文档每页都会被重送。"""
        import electrical.extract as ex
        from electrical.schema import empty_template_rows

        page_a = (
            "## 第 65 页\nModel DHT120s Inverter Engineering Design Rev No 001 PAGE 65/99\n"
            "COOLING PASS PRESSURE DROP < 300mbar, @12lpm @65℃\n"
        )
        page_b = (
            "## 第 66 页\nModel DHT120s Inverter Engineering Design Rev No 001 PAGE 66/99\n"
            "EMC: CISPR 25 Class 3, ECE R10.06\n"
        )
        markdown = page_a + page_b
        rows = {c.seq: c for c in empty_template_rows()}
        sent = [ex._strip_running_header(page_a)]
        self.assertNotIn("PAGE 65/99", sent[0])
        more = ex._topup_chunks(markdown, rows, sent, limit=6)
        self.assertFalse(any("PRESSURE DROP" in m for m in more), more)
        # 没送过时仍会选到
        more2 = ex._topup_chunks(markdown, rows, [], limit=6)
        self.assertTrue(any("PRESSURE DROP" in m for m in more2), more2)


class ScanDprFixTests(unittest.TestCase):
    CHUNK = """
6.5.3 HVDC Voltage Range
HVDC bus voltage [V]
Min level during cold ICE start
Min level for limited performance
Min level for full power
Max level for full power
Max limited performance
380
640
945
945
Full power is a condition where the unit can perform without any power derating.
Locking strategy:
P3, 85% (Tmax * 0.85) peak torque @ 3s @ 65 °C cooling water temperature @ 10lpm @ (650-945) V @ 4K, followed by 2 seconds to reduce to 50% peak torque
##**#: P3, 85% (T max*0.85) @ (300-450) V
The Y-capacitors of the PCM shall be less then the values below:
HVDC+ to GND
Y+≤SSnF & Y-≤S5nF
The PCM shall have functionality to perform an active discharge of the entire HVDC bus.
The active discharge shall be completed within ls of the triggering event (opening of the HV battery contactors).
The PCM shall have the possibility to passively discharge the HVDC bus. below 60VIDC within 120 s after opening of battery contactors.
Non-mated connectors (e.g. connectors for options) shall have a protection degree of at least IP68.
The unit shall not generate continuous voltages higher than 945VDC or transient voltages higher than 510VDC on the HVDC bus.
"""

    RATIO_PAGE = (
        "Table4 Drivability Targets 表4驾驰性目标 指标项 Units Data数值 Item 单位\n"
        "ICE: 7.119/4.881/3.689/2.941 变速箱速比（转化为阶差） 1 主减：3.462\n"
        "Ratio Step 1st\\2nd\\3rd P3: 12.830\n"
        "离合器扭矩精度 Clutch torque accuracy Nm ≥100Nm: ±3%Nm <100Nm: ±3Nm\n"
    )

    def test_chunk_fields_lists_two_char_name_by_strong_alias(self) -> None:
        """4LDHT260 / SuperEvo 2026-09-16：#75 速比二字名切不出整词，选段按别名送了这页，
        prompt 却没列 #75，模型无从作答，两份都漏。强别名整词命中也要把条目列进 prompt。"""
        from electrical.schema import empty_template_rows

        rows = {c.seq: c for c in empty_template_rows()}
        fields, hit = _chunk_fields(self.RATIO_PAGE, rows)
        self.assertTrue(hit)
        self.assertIn("速比", fields)
        # 已填的条目不再列
        for cell in rows.values():
            if cell.name == "速比":
                cell.value = "x"
        fields2, _ = _chunk_fields(self.RATIO_PAGE, rows)
        self.assertNotIn("速比", fields2)

    def test_strong_alias_latin_is_whole_word(self) -> None:
        """英文别名整词：creep（滑膜起步）不能认 creepage（爬电距离）；复数 fuses 仍认 fuse。"""
        import electrical.extract as ex

        self.assertFalse(ex._strong_alias_present("creep", "all creepage distances and clearances"))
        self.assertTrue(ex._strong_alias_present("creep", "creep mode shall be supported"))
        self.assertTrue(ex._strong_alias_present("fuse", "external fuses at kl30"))
        self.assertTrue(ex._strong_alias_present("速比", "变速箱速比（转化为阶差）"))
        self.assertFalse(ex._strong_alias_present("re", "requirements"))
        # 爬电距离页不能因 creep 把「滑膜起步功能」列进 prompt
        fields, _ = _chunk_fields(
            "All creepage distances and clearances of barriers shall be designed per ISO 6469-3.",
            None,
        )
        self.assertNotIn("滑膜起步", fields)

    def test_ratio_value_passes_guards(self) -> None:
        excerpt = "变速箱速比（转化为阶差） 1 主减：3.462 Ratio Step 1st\\2nd\\3rd P3: 12.830"
        self.assertTrue(_value_fits_field("速比", "ICE: 7.119/4.881/3.689/2.941；主减：3.462；P3: 12.830", excerpt))

    def test_scan_rules(self) -> None:
        found = {c.name: c.value for c in _rule_cells(self.CHUNK, family="dpr")}
        self.assertIn("380", found.get("直流工作电压范围") or "")
        self.assertIn("640", found.get("满功率(电流)工作电压") or "")
        self.assertIn("380", found.get("降额工作电压范围") or "")
        ycap = found.get("高压安全-Y电容指标") or ""
        self.assertNotIn("55nF", ycap)
        self.assertNotIn("批准", ycap)
        self.assertIn("1s", found.get("高压安全-主动放电功能") or "")
        self.assertIn("120", found.get("高压安全-被动放电功能") or "")
        self.assertFalse(found.get("P3峰值扭矩/时间/对应转速范围"))
        stall = found.get("P3堵转扭矩/时间") or ""
        self.assertIn("堵转", stall)
        self.assertIn("85%", stall)
        self.assertNotIn("IP68", found.get("密封（IP等级）") or "")
        self.assertNotEqual(found.get("直流工作电压范围"), "945VDC或瞬态电压510VDC")
        self.assertNotEqual(found.get("冷却液温度范围"), "65 °C")

    def test_ipxxb_is_not_enclosure_ip68(self) -> None:
        self.assertFalse(
            _value_fits_field(
                "密封（IP等级）",
                "IP68",
                ".3关于IPXXB 的要求 The drive motor controller should refer "
                "to the requirements for IPXXB in GB/",
            )
        )
        distant = (
            "6.10.15 Non-mated connectors\n"
            "Non-mated connectors (e.g. connectors for options, variants "
            "and accessories) shall:\n"
            "junk line " * 20
            + "have a protection degree of at least IP68. 1P69K\n"
        )
        found = {c.name: c.value for c in _rule_cells(distant, family="dpr")}
        self.assertNotIn("IP68", found.get("密封（IP等级）") or "")

    def test_scan_env_and_boost_scope(self) -> None:
        chunk = """
PCM is the control unit of a hybrid dedicated transmission, which includes transmission
control, motor control, thermal management control, boost control, and integrates power distribution module.
Considering the platform integration of PCM, PCM must have variants tailored to the BOOST architecture.
Minimum allowable storage temperature when not working (not exceeding one month): -40°C
Maximum allowable storage temperature when not working (not exceeding one month): 105°C.
The PCM shall be able to withstand a surface temperature of -40°C~110°C constant temperature when working
5.2.2 Operation altitude
The component shall be designed to operate up to 5000m above sea level.
The passive discharge circuitry shall be dimensioned so that the HVDC voltage in the unit
is below 60VIDC within
120 s after opening of battery contactors.
P1 continuous generate power @60°C@640V 70kW
P1 peak generate power 140kW
P1 continuous torque 55Nm
"""
        found = {c.name: c.value for c in _rule_cells(chunk, family="dpr")}
        drive = found.get("设计范围是否包含驱动升压功能") or ""
        self.assertTrue(drive.startswith("是"))
        self.assertNotEqual(drive, "是")
        self.assertIn("boost control", drive.lower())
        self.assertIn("boost", (found.get("Boost功能要求") or "").lower())
        self.assertNotIn("设计范围是否包含行车升压功能", found)
        self.assertNotIn("设计范围是否包含充电升压功能", found)
        self.assertNotIn("BOOST输入峰值电流", found)
        self.assertIn("5000", found.get("工作海拔高度") or "")
        self.assertIn("-40", found.get("存储温度范围") or "")
        self.assertIn("105", found.get("存储温度范围") or "")
        self.assertIn("110", found.get("工作温度范围") or "")
        self.assertIn("120", found.get("高压安全-被动放电功能") or "")
        self.assertIn("70kW", found.get("P1额定功率") or "")
        self.assertIn("140kW", found.get("P1峰值功率") or "")
        self.assertIn("55", found.get("P1额定扭矩") or "")
        self.assertFalse(
            _value_fits_field(
                "设计范围是否包含行车升压功能",
                "是",
                "thermal management control, boost control, and integrates",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "设计范围是否包含充电升压功能",
                "是",
                "thermal management control, boost control, and integrates",
            )
        )
        self.assertTrue(
            _value_fits_field(
                "设计范围是否包含驱动升压功能",
                "是",
                "thermal management control, boost control, and integrates",
            )
        )

    def test_drive_boost_scope_writes_conclusion(self) -> None:
        from electrical.extract import _better

        chunk = (
            "6.5.4 Boost\n"
            "The XCM shall be able to boost the HV input voltage to a higher voltage "
            "in order to improve the TM performance when HVDC input voltage is low.\n"
            "当高压直流输入电压较低时，控制器应能够将直流输入的电压提升到更高电压。"
        )
        found = {c.name: c.value for c in _rule_cells(chunk, family="dpr")}
        drive = found.get("设计范围是否包含驱动升压功能") or ""
        self.assertTrue(drive.startswith("是；"))
        self.assertNotEqual(drive, "是")
        self.assertIn("HVDC", drive)
        self.assertIn("TM", drive)
        traction = found.get("设计范围是否包含行车升压功能") or ""
        self.assertEqual(traction, drive)
        self.assertIn("更高电压", found.get("Boost功能要求") or "")
        yes_only = ExtractedCell(
            name="设计范围是否包含驱动升压功能",
            value="是",
            excerpt=chunk,
            confidence=0.99,
        )
        detailed = ExtractedCell(
            name="设计范围是否包含驱动升压功能",
            value=drive,
            excerpt=chunk,
            confidence=0.9,
        )
        self.assertEqual(_better(detailed, yes_only).value, drive)
        self.assertNotIn("Boost输出性能", found)

    def test_booster_target_voltage_fills_output_performance(self) -> None:
        chunk = (
            "Target output voltage of booster 升压器的目标输出电压\n"
            "450\n"
            "V\n"
            "BOOST input peak current BOOST输入峰值电流 400A@10S\n"
        )
        found = {c.name: c.value for c in _rule_cells(chunk, family="dpr")}
        self.assertEqual(found.get("Boost输出性能"), "450 V")
        self.assertIn("450", found.get("BOOST最高工作电压") or "")

    def test_hv_booster_modes_fill_output_voltage_not_item4(self) -> None:
        chunk = """
6.5.4
HV Booster 高压升压器
The XCM shall be able to boost the HV input voltage to a higher voltage in order to improve the TM performance when HVDC input voltage is low.
当高压直流输入电压较低时，控制器应能够将直流输入的电压提升到更高电压，以改善变速器的性能。
Target output voltage of booster
升压器的目标输出电压	450	V
BOOST input peak current BOOST输入峰值电流	400A@10S	A
BOOST input continue current 升压输入持续电流	Boost:195A  ；Bypass:200A	A
Switching frequency for boost 升压开关频率	≥15	KHZ
BUCK 功率	Max 85kW@200V-400V	KW
需要具备三种作工作模式	Boost升压，bypass直通，BUCK降压	／
BOOST output ripple voltage升压输出纹波电压	≤±16@输入300~380V输出450V	V
"""
        found = {c.name: c.value for c in _rule_cells(chunk, family="dpr")}
        drive = found.get("设计范围是否包含驱动升压功能") or ""
        self.assertTrue(drive.startswith("是；"))
        self.assertIn("TM", drive)
        traction = found.get("设计范围是否包含行车升压功能") or ""
        self.assertTrue(traction.startswith("是；"))
        self.assertIn("TM", traction)
        self.assertNotIn("85kW", traction)
        self.assertNotRegex(traction, r"三种")
        self.assertNotIn("设计范围是否包含充电升压功能", found)
        self.assertNotIn("升压充电功能", found)
        out = found.get("升压输出电压") or ""
        self.assertIn("450", out)
        self.assertRegex(out, r"Boost/bypass/BUCK|三种")
        self.assertIn("85kW", out)
        self.assertFalse(
            _value_fits_field(
                "设计范围是否包含行车升压功能",
                "是（含 BUCK 降压模式，Max 85kW@200V-400V）",
                chunk,
            )
        )
        self.assertTrue(
            _value_fits_field(
                "设计范围是否包含行车升压功能",
                "是；HVDC 输入电压较低时将高压输入升至更高电压，以改善 TM 性能",
                "The XCM shall be able to boost the HV input voltage to a higher voltage "
                "in order to improve the TM performance when HVDC input voltage is low.",
            )
        )

    def test_scan_ocr_4ldht_performance_stores(self) -> None:
        from electrical.extract import _store_cell
        from electrical.schema import empty_template_rows

        text = """
动力控制模块_总  14.9  14.9
PCMPl peak current  母线满功率电压范围  Ams  350Ams@10s
PCMPI 峰值电流  PCM P1 Continuous Current  210Amms@30min
PCMP3 peak current  PCMP3峰值电流  Ams  600Ams@10s
PCMP3持续电流  PCMP3 Continuous Current  Ars  310Ars@30min
PCM maximum efficiency @640V  %  P3：≥99.9%；  PI：≥99.5%；
P1 continuous generate power @60°C@640V  P1 电机额定发电功率  kW  70kW@7500rpm
power@60°C@≥10s@350Ams  P1 peak generate  P1 电机峰值发电功率  kW  140kW,10500rpm-16000rpm
P1 continuous torque （80degC） @640V  Nm  95Nm @ 0-7000rpm
P1 电机额定扭矩 @80°C@640V
the max speed of Pl@640V  P1 电机最高转速  rpm  16000（出电功率）  17000（随转）
P1 Back EMF（@peek speed@20°C）  vdc  ≤1000（控制器耐受 1200V）
P3 continuous torque （60degC）@640V  Nm  200Nm @ 0-6000rpm
P3 电机额定扭矩 @60°C@640V
P3 peak drive power  kw  260kW@640V，@ 6500-11000rpm
P3 电机峰值驱动功率@60°C
P3 电机峰值扭矩@600A（@10s@640V  P3 peak torque（@600A@10s@640V  Nm  400Nm @0-6500rpm
the max speed of P3  P3电机最高转速  rpm  20000（出功率）  22000 随转
PCM 母线工作电压范围  PCM busbar working voltage range  Vdc  390~945
PCMbusbar full performance working voltage range PCM  Vdc  640V~945
CY+ & CY-≤110nF; Etotals0.2J
堵转安全  85%峰值扭矩@3s持续，4s-5s 功率降低50%
P3 Back EMF（@peek speed@20°C）  Vdc  ≤1000（控制器耐受 1200V）
压降≤25kPa@10L/min,65°C
控制器流量 requirement L/min ≥10L@65°C
PCMheat loss  控制器散热量  kW  低速爬坡 Q≤0.8kW；  高速爬坡 Q≤0.9kW
PCM shall be meet Q/IL J160003-2024 乘用车零部件防腐技术要求 L1-F4。
Minimum allowable storage temperature when not work ing （not exceeding one month）： -40°C
Maximum allowable storage temperature when not working （not exceeding one month）： 105°C。
PCM 需要满足 IP68 &IP6K9K
The Y-capacitors of the PCM shall be less then the values below:
Y+≤SSnF & Y-≤S5nF
"""
        rows = {c.seq: c for c in empty_template_rows()}
        excerpt_owner: dict[str, str] = {}
        value_owner: dict[str, str] = {}
        seen: set[tuple[str, str]] = set()
        extra: list = []
        for cell in _rule_cells(text, family="dpr"):
            _store_cell(cell, text, rows, extra, seen, excerpt_owner, value_owner)
        _fill_peak_bemf_from_motors(rows)
        found = {c.name: c.value for c in rows.values() if (c.value or "").strip()}
        self.assertIn("95Nm", found.get("P1额定扭矩") or "")
        self.assertIn("200Nm", found.get("P3额定扭矩") or "")
        self.assertIn("16000", found.get("P1最高工作转速") or "")
        self.assertNotIn("12000", found.get("P1最高工作转速") or "")
        self.assertIn("20000", found.get("P3最高工作转速") or "")
        self.assertIn("350", found.get("P1逆变器交流电流峰值") or "")
        self.assertRegex(found.get("P1峰值功率持续时间") or "", r"≥?10s")
        self.assertIn("210", found.get("P1逆变器持续交流电流") or "")
        self.assertIn("600", found.get("P3逆变器交流电流峰值") or "")
        self.assertIn("310", found.get("P3额定功率相电流") or "")
        self.assertIn("99.5", found.get("P1逆变器效率指标") or "")
        self.assertIn("99.9", found.get("P3逆变器效率指标") or "")
        self.assertIn("1000", found.get("P1反电动势（Back EMF）") or "")
        self.assertIn("1000", found.get("P3 反电动势（Back EMF）") or "")
        self.assertIn("1000", found.get("反电动势峰值") or "")
        self.assertIn("14.9", found.get("控制器重量") or "")
        self.assertIn("10", found.get("额定流量") or "")
        self.assertIn("0.8", found.get("热损失") or "")
        self.assertIn("F4", found.get("防腐等级") or "")
        self.assertIn("-40", found.get("存储温度范围") or "")
        self.assertIn("105", found.get("存储温度范围") or "")
        self.assertIn("IP68", found.get("密封（IP等级）") or "")
        self.assertNotIn("55nF", found.get("高压安全-Y电容指标") or "")
        self.assertIn("110nF", found.get("高压安全-Y电容指标") or "")
        self.assertIn("260", found.get("P3峰值功率") or "")
        self.assertIn("400Nm", found.get("P3峰值扭矩/时间/对应转速范围") or "")
        self.assertNotIn("85%", found.get("P3峰值扭矩/时间/对应转速范围") or "")
        self.assertIn("390", found.get("直流工作电压范围") or "")
        self.assertIn("640", found.get("满功率(电流)工作电压") or "")
        self.assertIn("85%", found.get("P1堵转扭矩/时间") or "")
        self.assertIn("16000", found.get("P1最高工作转速") or "")
        self.assertIn("17000", found.get("P1最高工作转速") or "")
        self.assertIn("出电功率", found.get("P1最高工作转速") or "")
        self.assertIn("随转", found.get("P1最高工作转速") or "")
        self.assertNotIn("7500", found.get("P1 额定转速") or "")
        self.assertFalse(
            _value_fits_field(
                "P1 额定转速",
                "7500rpm",
                "P1 continuous generate power@60℃@640V kW 70kW@7500rpm -12000rpm",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "冷却液温度范围",
                "65℃",
                "85%峰值扭矩@3s 持续，4s-5s 功率降低 50% @65℃冷却水温 Stall Safety 堵转安全",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "P1最高工作转速",
                "12000rpm",
                "12 poles and 12000 Rpm",
            )
        )

    def test_scan_ocr_weight_p1_efficiency_wake_current(self) -> None:
        from electrical.extract import _store_cell
        from electrical.schema import empty_template_rows

        text = """
动力控制模块_总成  14.9kg
PCM maximum efficiency @640V  %  P3:≥99.9%； P1:≥99.5%
未唤醒@仅低压上电  0.2
唤醒@IGBT开管@高低压都上电  2000
"""
        rows = {c.seq: c for c in empty_template_rows()}
        excerpt_owner: dict[str, str] = {}
        value_owner: dict[str, str] = {}
        seen: set[tuple[str, str]] = set()
        extra: list = []
        for cell in _rule_cells(text, family="dpr"):
            _store_cell(cell, text, rows, extra, seen, excerpt_owner, value_owner)
        found = {c.name: c.value for c in rows.values() if (c.value or "").strip()}
        self.assertIn("14.9", found.get("控制器重量") or "")
        self.assertIn("14.9", found.get("重量要求") or "")
        self.assertIn("99.5", found.get("P1逆变器效率指标") or "")
        self.assertIn("99.9", found.get("P3逆变器效率指标") or "")
        self.assertIn("0.2", found.get("静态电流") or "")
        self.assertIn("2000mA", found.get("低压功耗要求") or "")
        self.assertFalse(
            _value_fits_field(
                "P1逆变器效率指标",
                "≥99.9%（@640V 最高效率）",
                "P3:≥99.9%",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "P3逆变器效率指标",
                "最高效率＞99%；平均效率至少 98.2%",
                "6.8.4.1 PEI P1 P1逆变器效率 Average efficiency at least 98.2%",
            )
        )
        self.assertTrue(
            _value_fits_field(
                "P3逆变器效率指标",
                "最高效率＞99%；综合效率≥98.25%@340V",
                "6.8.4.2 PEI P3 P3逆变器效率 combined efficiency 综合效率 ≥98.25% @340V",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "低压功耗要求",
                "0.2mA（未唤醒，仅低压上电）",
                "未唤醒@仅低压上电 0.2",
            )
        )
        self.assertTrue(
            _value_fits_field(
                "低压功耗要求",
                "唤醒@IGBT开管 2000mA",
                "唤醒@IGBT开管@高低压都上电 2000",
            )
        )

    def test_scan_ocr_weight_line_break_and_table(self) -> None:
        from electrical.extract import _store_cell
        from electrical.schema import empty_template_rows

        samples = [
            "动力控制模块_总成\n14.9\n14.9",
            "动力控制模块_总成 | kg | 14.9 |",
            "总成重量  14.9kg",
            "PCM assembly weight 14.9 kg",
        ]
        for text in samples:
            with self.subTest(text=text[:24]):
                rows = {c.seq: c for c in empty_template_rows()}
                excerpt_owner: dict[str, str] = {}
                value_owner: dict[str, str] = {}
                seen: set[tuple[str, str]] = set()
                extra: list = []
                for cell in _rule_cells(text, family="dpr"):
                    _store_cell(cell, text, rows, extra, seen, excerpt_owner, value_owner)
                found = {c.name: c.value for c in rows.values() if (c.value or "").strip()}
                self.assertIn("14.9", found.get("控制器重量") or "", found)
                self.assertIn("14.9", found.get("重量要求") or "", found)

    def test_p3_peak_torque_not_overwritten_by_stall(self) -> None:
        from electrical.extract import _store_cell
        from electrical.schema import empty_template_rows

        text = """
P3 电机峰值扭矩@600A（@10s@640V  P3 peak torque（@600A@10s@640V  Nm  400Nm @0-6500rpm
Locking strategy: P3, 85% (Tmax * 0.85) peak torque @ 3s @ 65 °C @ 10lpm @ (650-945) V
"""
        rows = {c.seq: c for c in empty_template_rows()}
        excerpt_owner: dict[str, str] = {}
        value_owner: dict[str, str] = {}
        seen: set[tuple[str, str]] = set()
        extra: list = []
        for cell in _rule_cells(text, family="dpr"):
            _store_cell(cell, text, rows, extra, seen, excerpt_owner, value_owner)
        found = {c.name: c.value for c in rows.values() if (c.value or "").strip()}
        self.assertIn("400Nm", found.get("P3峰值扭矩/时间/对应转速范围") or "")
        self.assertNotIn("85%", found.get("P3峰值扭矩/时间/对应转速范围") or "")
        self.assertIn("堵转", found.get("P3堵转扭矩/时间") or "")


class SixTableFixTests(unittest.TestCase):
    def test_p1_peak_torque_not_hvac_current(self) -> None:
        self.assertFalse(
            _value_fits_field(
                "P1峰值扭矩/时间/对应转速范围",
                "PEI P1: The XCM shall be able to measure the HVAC current "
                "consumed or generated PEI P1 within the range - 600A to +600A "
                "peak with measurement error less than ±3%（＞100A）or ±3A（0-100A）.",
                "控制器应能够测量- 600A至+600A峰值范围内消耗产生的P1逆变器高压交流电流，"
                "全生命周期测量误差小于±3%(>100A)或±3A (0-100A)。",
            )
        )
        self.assertTrue(
            _value_fits_field(
                "P1峰值扭矩/时间/对应转速范围",
                ">100Nm @80℃@10s@800V",
                "P1电机峰值扭矩@80℃@10s@800V | Nm | >100Nm",
            )
        )
        self.assertTrue(
            _value_fits_field(
                "相电流采样精度",
                "P1 高压交流 −600A~+600A；＞100A 误差±3%，0–100A 误差±3A",
                "控制器应能够测量- 600A至+600A峰值范围内消耗产生的P1逆变器高压交流电流，"
                "全生命周期测量误差小于±3%(>100A)或±3A (0-100A)。",
            )
        )

    def test_hvac_current_binds_to_phase_accuracy(self) -> None:
        chunk = (
            "The XCM shall be able to measure the HVAC current consumed or "
            "generated PEI P1 within the range - 600A to +600A peak with "
            "measurement error less than ±3% (>100A) or ±3A (0-100A).\n"
            "控制器应能够测量- 600A至+600A峰值范围内消耗产生的P1逆变器高压交流电流，"
            "全生命周期测量误差小于±3%(>100A)或±3A (0-100A)。"
        )
        found = {c.name: c.value for c in _rule_cells(chunk, family="dpr")}
        self.assertNotIn("P1峰值扭矩/时间/对应转速范围", found)
        self.assertIn("相电流采样精度", found)
        self.assertIn("600A", found["相电流采样精度"])
        self.assertNotIn("中文", found["相电流采样精度"])
        self.assertNotIn("需人工复核", found["相电流采样精度"])

    def test_placeholder_and_supplier_junk(self) -> None:
        self.assertTrue(_is_junk_value("暂无具体数值", "振动要求"))
        self.assertTrue(
            _is_junk_value("额定电压 500Vdc（容值供应商提供）", "薄膜电容容值")
        )
        self.assertTrue(
            _is_junk_value(
                "有 DC-link 过压保护（检测阈值由供应商提供）",
                "直流电压过压保护",
            )
        )
        self.assertFalse(_is_junk_value("125kW@320V-450V@10S", "P1峰值功率"))

    def test_vibration_needs_numeric_or_std(self) -> None:
        self.assertFalse(
            _value_fits_field(
                "振动要求",
                "暂无具体数值",
                "Table 1. Sinusoidal vibration frequency and acceleration",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "振动要求",
                "10G（10~200Hz）（DC 电容规范）",
                "Vibration G 10G (10~200Hz)",
            )
        )
        self.assertTrue(
            _value_fits_field(
                "振动要求",
                "按 Q/JLP 030600-10 2025A：温度循环与正弦+随机振动；每方向 4 个循环（32h）",
                "Perform the test according to Q/JLP 030600-10",
            )
        )

    def test_film_cap_needs_capacitance(self) -> None:
        self.assertFalse(
            _value_fits_field(
                "薄膜电容容值",
                "额定电压 500Vdc（容值供应商提供）",
                "DC capacitor 500Vd",
            )
        )

    def test_udc_13kw_rejected_in_chinese(self) -> None:
        self.assertFalse(
            _value_fits_field(
                "P3峰值功率",
                "13 kW",
                "在此UDC模式下，功率能力峰值为13 kW",
            )
        )

    def test_iso6469_not_pcm_dielectric(self) -> None:
        self.assertFalse(
            _value_fits_field(
                "高压安全-耐电压",
                "The XCM shall meet the withstand voltage capability test according to ISO 6469-32018.",
                "The XCM shall meet the withstand voltage capability test according to ISO 6469-32018.",
            )
        )

    def test_iso6469_1min_is_dielectric(self) -> None:
        excerpt = (
            "The XCM shall meet the withstand voltage capability test according to ISO 6469-32018. "
            "The following minimum AC test voltage of a frequency between 50 Hz and 60 Hz shall be applied for 1 min: "
            "(2U +1 000) VAC rms if basic insulation applies. A maximum working voltage of 500V shall be used."
        )
        self.assertTrue(
            _value_fits_field(
                "高压安全-耐电压",
                "按 ISO 6469-3-2018，1min，50–60Hz；(2U+1000) VAC rms",
                excerpt,
            )
        )

    def test_inverter_presence_not_found(self) -> None:
        chunk = (
            "DC link overvoltage\n"
            "DC current\nVoltage ripple\nCapacitance\nY-Capacitor\n"
            "DC capacitor 500Vdc Rated Voltage\n"
            "Vibration\nG\n10G (10~200Hz)\nDC capacitor"
        )
        found = {c.name: c.value for c in _rule_cells(chunk, family="inverter")}
        self.assertNotIn("直流电压过压保护", found)
        self.assertNotIn("母线直流电流检测", found)
        self.assertNotIn("薄膜电容容值", found)
        self.assertNotIn("振动要求", found)


class DownloadedSheetQualityTests(unittest.TestCase):
    """对照 2026-08-28 六份下载核对表里仍会标成「已检索到」的错绑。"""

    def test_overvoltage_circuit_analysis_rejected(self) -> None:
        self.assertTrue(
            _is_junk_value(
                "DC link overvoltage ( circuit analysis )",
                "直流电压过压保护",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "直流电压过压保护",
                "DC link overvoltage ( circuit analysis )",
                "DC link overvoltage ( circuit analysis )",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "直流电压过压保护",
                "continuous voltages higher than 945VDC or transient voltages higher than 510VDC",
                "The unit shall not generate continuous voltages higher than 945VDC or transient voltages higher than 510VDC on the HVDC bus.",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "静态电流",
                "0.1mA↓(@ Rated Voltage, 1min)",
                "Dark Current 0.1mA↓(@ Rated Voltage, 1min)",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "直流电压过压保护",
                "高压侧：＞1066V",
                "允许过压保护（可自动恢复） 高压侧：＞1066V",
            )
        )
        found = {
            c.name: c.value
            for c in _rule_cells("允许过压保护（可自动恢复） 高压侧：＞1066V", family="dpr")
        }
        self.assertNotEqual(found.get("直流电压过压保护"), "高压侧：＞1066V")
        self.assertNotIn("直流电压过压保护", found)
        self.assertFalse(
            _value_fits_field(
                "直流电压过压保护",
                "过压点",
                "PCM maximum efficiency @800V | % | P1:≥99.5%",
            )
        )
        self.assertTrue(_is_junk_value("过压点", "直流电压过压保护"))

    def test_cap_10g_not_pcm_vibration(self) -> None:
        self.assertFalse(
            _value_fits_field(
                "振动要求",
                "10G (10~200Hz)",
                "10G (10~200Hz)",
            )
        )
        found = {
            c.name: c.value
            for c in _rule_cells("Vibration 10G (10~200Hz)", family="inverter")
        }
        self.assertNotIn("振动要求", found)

    def test_ocr_o_to_flow_normalized(self) -> None:
        found = {
            c.name: c.value
            for c in _rule_cells("coolant flow: O to 10 liter/min", family="dpr")
        }
        self.assertEqual(found.get("冷却流量范围"), "0 to 10 liter/min")
        from electrical.extract import _store_cell
        from electrical.schema import ExtractedCell, empty_template_rows, load_template_fields

        rows = {c.seq: c for c in empty_template_rows()}
        names = {spec.seq: spec.name for spec in load_template_fields()}
        seq = next(s for s, n in names.items() if n == "冷却流量范围")
        cell = ExtractedCell(
            seq=seq,
            name="冷却流量范围",
            value="O to 10 liter/min",
            excerpt="coolant flow: O to 10 liter/min",
            confidence=0.9,
        )
        extra: list = []
        _store_cell(
            cell,
            "## 第 77 页\ncoolant flow: O to 10 liter/min",
            rows,
            extra,
            set(),
            {},
            {},
        )
        self.assertEqual(rows[seq].value, "0 to 10 liter/min")

    def test_p3_phase_current_not_boost_lv(self) -> None:
        self.assertFalse(
            _value_fits_field(
                "P3额定功率相电流",
                "250A（低压侧）",
                "额定输入电流 250A（低压侧）",
            )
        )

    def test_coolant_range_not_sensor_span(self) -> None:
        self.assertFalse(
            _value_fits_field(
                "冷却液温度范围",
                "-40°C to +100°C",
                "The coolant inlet temperature must be measurable in the range -40°C to +100°C",
            )
        )

    def test_static_current_not_cap_leak_or_under1(self) -> None:
        self.assertFalse(
            _value_fits_field(
                "静态电流",
                "0.1mA↓（DC 电容，额定电压 1min）",
                "Dark Current 0.1mA↓ (@ Rated Voltage, 1min) DC capacitor",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "静态电流",
                "板级 Dark Current <1 mA；DC 电容 0.1mA↓@额定电压 1min",
                "Under 1",
            )
        )

    def test_withstand_heading_not_18488_template(self) -> None:
        heading = "耐电压要求（电控） Withstand voltage requirements of PCM"
        found = {c.name: c.value for c in _rule_cells(heading, family="dpr")}
        self.assertNotIn("高压安全-耐电压", found)
        self.assertFalse(
            _value_fits_field(
                "高压安全-耐电压",
                "动力端子对壳体/信号端子：按 GB/T 18488-2024 表1，1min，无击穿，漏电流≤5mA；信号端子对壳体：500V 工频",
                "耐电压要求（电控）",
            )
        )

    def test_withstand_16935_not_18488(self) -> None:
        chunk = (
            "耐电压要求（电控） Withstand voltage requirements of PCM "
            "GB/T 16935.1-2023 试验持续时间1min，应无击穿现象，漏电流小于3.5mA。"
        )
        found = {c.name: c.value for c in _rule_cells(chunk, family="dpr")}
        val = found.get("高压安全-耐电压") or ""
        self.assertIn("16935", val)
        self.assertNotIn("18488", val)
        self.assertIn("3.5mA", val)

    def test_hvdc_rows_not_glued_numbers(self) -> None:
        found = {c.name: c.value for c in _rule_cells(ScanDprFixTests.CHUNK, family="dpr")}
        working = found.get("直流工作电压范围") or ""
        self.assertIn("380", working)
        self.assertIn("640", found.get("满功率(电流)工作电压") or "")
        self.assertNotIn("性能限制≥", working)
        self.assertIn("限制性能", working)
        self.assertIn("未给出", working)
        self.assertIn("冷启动", working)
        self.assertIn("最低：", working)
        self.assertIn("最高：", working)
        excerpt = next(
            c.excerpt for c in _rule_cells(ScanDprFixTests.CHUNK, family="dpr")
            if c.name == "直流工作电压范围"
        )
        self.assertNotRegex(excerpt, r"380 640 945")

    def test_pcm_busbar_range_beats_glued_hvdc(self) -> None:
        from electrical.extract import _better
        from electrical.schema import ExtractedCell

        glued = ExtractedCell(
            name="直流工作电压范围",
            value="性能限制≥380V；满功率640~945V",
            excerpt="Min level during cold ICE s 380 640 945",
            confidence=0.82,
        )
        busbar = ExtractedCell(
            name="直流工作电压范围",
            value="390~945V",
            excerpt="PCM busbar working voltage range | Vdc | 390~945 Vdc",
            confidence=0.88,
        )
        self.assertEqual(_better(glued, busbar).value, "390~945V")
        self.assertEqual(_better(busbar, glued).value, "390~945V")

    def test_inverter_table36_torque_altitude_not_cap_as_machine(self) -> None:
        chunk = """
Table 3.6 Inverter Performance Requirements
Torque control accuracy
±2% ↓ (0±0.4Nm @ Zero torque)
Altitude
m
5000
Dark Current
mA
Under 1
Y-Capacitor
450nF x 2EA
Y-capacitor : 1500 Vdc
Discharge time
sec
60 (Passive), 1 (Active)
Less than 30Vac or 60Vdc
Table 3.9 DC Capacitor Required Specifications
Rated Voltage
500Vdc
Insulation Resistance
㏁
100MΩ↑(@ Rated Voltage, 1min)
Dark Current
0.1mA↓(@ Rated Voltage, 1min)
Vibration
G
10G (10~200Hz)
Active/passive discharge resistor
DC link overvoltage ( circuit analysis )
Voltage Ripple on HV
100Hz~300kHz
15Vpp/30Vpp
Region I
"""
        found = {c.name: c.value for c in _rule_cells(chunk, family="inverter")}
        self.assertIn("0.4Nm", found.get("扭矩控制精度") or "")
        self.assertIn("5000", found.get("工作海拔高度") or "")
        self.assertNotIn("静态电流", found)
        self.assertNotIn("高压安全-绝缘电阻", found)
        self.assertNotIn("直流工作电压范围", found)
        self.assertNotIn("振动要求", found)
        self.assertNotIn("直流电压过压保护", found)
        self.assertNotEqual(found.get("高压安全-被动放电功能"), "Active/passive discharge resistor")
        self.assertIn("60", found.get("高压安全-被动放电功能") or "")
        self.assertNotIn("升压纹波电压", found)
        self.assertNotIn("直流母线纹波电压要求", found)
        self.assertNotIn("高压安全-纹波电压", found)
        self.assertIn("450nF", found.get("高压安全-Y电容指标") or "")
        self.assertFalse(
            _value_fits_field(
                "升压纹波电压",
                "100Hz~300kHz 15Vpp/30Vpp",
                "Voltage Ripple on HV | 100Hz~300kHz 15Vpp/30Vpp | Region I",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "直流母线纹波电压要求",
                "HV 纹波 15Vpp/30Vpp（100Hz~300kHz）",
                "Voltage Ripple on HV | 100Hz~300kHz 15Vpp/30Vpp | Region I",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "高压安全-被动放电功能",
                "Active/passive discharge resistor",
                "Active/passive discharge resistor",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "高压安全-绝缘电阻",
                "DC-link 电容：100MΩ↑（额定电压，1min）",
                "Insulation Resistance\n㏁\n100MΩ↑(@ Rated Voltage, 1min)",
            )
        )

    def test_ocr_garbage_excerpt_becomes_partial(self) -> None:
        from electrical.schema import ExtractedCell, STATUS_PARTIAL, finalize_retrieval_statuses

        excerpt = (
            "Min level for full power i# th#Hi#E&E Max level for full power "
            "I)#H#R#4E 945 945"
        )
        self.assertTrue(_looks_like_ocr_garbage(excerpt))
        cell = ExtractedCell(
            name="满功率(电流)工作电压",
            seq=6,
            value="945",
            excerpt=excerpt,
            page="27",
            confidence=0.9,
        )
        _downgrade_ocr_excerpt(cell)
        finalize_retrieval_statuses([cell])
        self.assertEqual(cell.review_status, STATUS_PARTIAL)
        self.assertIn("扫描识别花成", cell.note)
        self.assertIn("th#Hi#E&E", cell.note)
        self.assertIn("第 27 页", cell.note)
        self.assertNotIn("乱码", cell.note)

        stale = ExtractedCell(
            name="满功率(电流)工作电压",
            seq=6,
            value="945",
            excerpt=excerpt,
            page="27",
            confidence=0.9,
            note="原文摘录含扫描件乱码，请对照原页确认",
        )
        _downgrade_ocr_excerpt(stale)
        self.assertIn("扫描识别花成", stale.note)
        self.assertNotIn("乱码", stale.note)

    def test_markdown_heading_hashes_are_not_ocr_garbage(self) -> None:
        self.assertFalse(
            _looks_like_ocr_garbage("### Y-capacitor selection Y-电容选择")
        )
        self.assertFalse(
            _looks_like_ocr_garbage("### Vibration 振动要求 1）Temperature cycle温度循环")
        )
        self.assertFalse(
            _looks_like_ocr_garbage(
                "The XCM shall meet the withstand voltage capability test "
                "according to ISO 6469-32018."
            )
        )
        self.assertTrue(_looks_like_ocr_garbage("th#Hi#E&E I)#H#R#4E"))

        from electrical.schema import ExtractedCell, STATUS_FOUND, finalize_retrieval_statuses
        from electrical.extract import _scrub_false_ocr_note, scrub_cells_ocr_notes

        cell = ExtractedCell(
            name="高压安全-Y电容指标",
            seq=17,
            value="Y+≤660nF、Y-≤660nF（HVDC±对地）",
            excerpt="### Y-capacitor selection Y-电容选择",
            confidence=0.72,
            note="原文摘录含扫描件乱码，请对照原页确认",
        )
        _scrub_false_ocr_note(cell)
        self.assertNotIn("乱码", cell.note or "")
        self.assertNotIn("扫描识别花成", cell.note or "")
        self.assertGreaterEqual(cell.confidence, 0.82)
        finalize_retrieval_statuses([cell])
        self.assertEqual(cell.review_status, STATUS_FOUND)

        llm = ExtractedCell(
            name="高压安全-耐电压",
            seq=14,
            value="按 ISO 6469-3-2018，1min",
            excerpt=(
                "The XCM shall meet the withstand voltage capability test "
                "according to ISO 6469-32018."
            ),
            confidence=0.9,
            note="原文摘录含扫描件乱码，请对照原页确认",
        )
        scrub_cells_ocr_notes([llm])
        finalize_retrieval_statuses([llm])
        self.assertNotIn("乱码", llm.note or "")
        self.assertEqual(llm.review_status, STATUS_FOUND)


class Dhts160FillTests(unittest.TestCase):
    """DHTS160：勿把 HVDC/Boost 行误绑 P1 与纹波；电压表要读升压列。"""

    HVDC_TABLE = """
| Parameter | HVDC bus voltage [V] 非升压 | HVDC bus voltage [V] 升压 |
| --- | --- | --- |
| Min level during cold ICE start冷启动时的最低电压 | 160 | 160 |
| Min level for limited performance性能限制时的最低电压 | 200 | 160 |
| Min level for full current满电流时的最低电压 | 200 | 160 |
| Max level for full current满电流时的最高电压 | 450 | 450 |
| Min level for full power满功率时的最低电压 | 340 | 160 |
| Max level for full power满功率时的最高电压 | 450 | 450 |
| Max limited performance限制性能下可工作最高电压 | 500 | 500 |
HVDC peak power 高压直流峰值功率
125kW@320V-450V@10S
HVDC continuous power高压直流持续功率
62.5kW@320V
"""

    RIPPLE = """
2.3.3.3.3 Generated voltage ripple 产生电压纹波
The unit must not generate higher differential voltage ripple in the HVDC bus when the HV battery is connected than the one specified in Table below:
当连接高压电池时，控制器不得在高压直流母线上产生比下表规定的更高的电压纹波：
| Maximum differential ripple when the HV battery is switched on. 高压电池接通时的最大差分纹波 | V pk-pk | Rated operating conditions：16 额定工况：16 Peak operating conditio:：30 峰值工况：30 |
2.3.3.3.4 Generated voltage ripple UDC control 直流控制产生电压纹波
The unit must not generate higher differential voltage ripple in the HVDC bus when the HV battery is disconnected (battery contactors open)
| Maximum differential ripple when the HV battery is switched off. 高压电池关闭时的最大差分纹波 | V pk-pk | 30 |
| The ripple voltage on the bus caused by Boost Boost对母线造成的纹波电压 | 额定功率：16V_Vpp 峰值功率：30V_Vpp |  |
| BOOST output ripple voltage升压输出纹波电压 | ≤±16@输入300~380V输出450V | |
"""

    STALL = (
        "Locking strategy:  P3, 85% (Tmax * 0.85) peak torque @ 3s @ 65 ℃ "
        "@ 10lpm @ (300-450) V @ 4K, followed by 2 seconds to reduce to 50% "
        "peak torque for continuous locking.\n"
        "堵转策略：P3，85%（T_max*0.85）峰值扭矩@3s，随后需2s降到50%峰值扭矩持续堵转"
    )

    def test_hvdc_peak_is_not_p1_motor_power(self) -> None:
        found = {c.name: c.value for c in _rule_cells(self.HVDC_TABLE, family="dpr")}
        self.assertNotIn("P1峰值功率", found)
        self.assertNotIn("P1峰值功率持续时间", found)
        self.assertNotIn("P1额定功率", found)
        self.assertFalse(
            _value_fits_field(
                "P1峰值功率",
                "125kW@320V-450V@10S",
                "HVDC peak power 高压直流峰值功率 125kW@320V-450V@10S",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "P1额定功率",
                "62.5kW@320V",
                "HVDC continuous power高压直流持续功率 62.5kW@320V",
            )
        )

    def test_hvdc_reads_boost_column(self) -> None:
        found = {c.name: c.value for c in _rule_cells(self.HVDC_TABLE, family="dpr")}
        full = found.get("满功率(电流)工作电压") or ""
        self.assertIn("340", full)
        self.assertIn("160", full)
        self.assertIn("升压", full)
        working = found.get("直流工作电压范围") or ""
        self.assertIn("冷启动", working)
        self.assertIn("160", working)
        self.assertIn("最低：", working)
        self.assertIn("最高：", working)
        self.assertRegex(working, r"1\.冷启动最低：")
        self.assertRegex(working, r"2\.满功率最低：")
        derate = found.get("降额工作电压范围") or ""
        self.assertIn("200", derate)
        self.assertIn("160", derate)
        self.assertIn("限制性能", derate)
        self.assertNotRegex(derate, r"200V（上限500")
        self.assertRegex(full, r"1\.满功率最低：")
        self.assertIn("满电流", full)
        self.assertRegex(derate, r"1\.限制性能最低：")
        self.assertIn("500", derate)
        self.assertNotIn("最高：未给出", derate)
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(self.HVDC_TABLE, family="dpr"):
            _store_cell(cell, self.HVDC_TABLE, rows, extra, set(), {}, {})
        stored5 = next(c for c in rows.values() if c.name == "直流工作电压范围")
        stored6 = next(c for c in rows.values() if c.name == "满功率(电流)工作电压")
        stored7 = next(c for c in rows.values() if c.name == "降额工作电压范围")
        self.assertRegex(stored5.value, r"1\.冷启动最低：")
        self.assertIn("160", stored5.value)
        self.assertRegex(stored6.value, r"1\.满功率最低：")
        self.assertIn("满电流", stored6.value)
        self.assertRegex(stored7.value, r"1\.限制性能最低：")
        self.assertIn("500", stored7.value)
        self.assertNotIn("最高：未给出", stored7.value)

    def test_ripple_from_generated_not_boost(self) -> None:
        found = {c.name: c.value for c in _rule_cells(self.RIPPLE, family="dpr")}
        bus = found.get("直流母线纹波电压要求") or ""
        self.assertIn("16", bus)
        self.assertIn("30", bus)
        self.assertIn("接通", bus)
        self.assertNotIn("Boost", bus)
        safety = found.get("高压安全-纹波电压") or ""
        self.assertIn("断开", safety)
        self.assertIn("30", safety)
        self.assertNotIn("Boost", safety)
        self.assertNotEqual(bus, safety)
        boost = found.get("升压纹波电压") or ""
        self.assertIn("±16", boost)
        cells = {c.name: c for c in _rule_cells(self.RIPPLE, family="dpr")}
        self.assertEqual(cells["直流母线纹波电压要求"].clause, "2.3.3.3.3")
        self.assertEqual(cells["高压安全-纹波电压"].clause, "2.3.3.3.4")
        self.assertFalse(
            _value_fits_field(
                "直流母线纹波电压要求",
                "额定 16V_Vpp；峰值 30V_Vpp（Boost 引起）",
                "The ripple voltage on the bus caused by Boost 额定功率：16V_Vpp",
            )
        )

    def test_dhts_booster_450_is_boost_output_voltage(self) -> None:
        excerpt = "Target output voltage of booster 升压器的目标输出电压 | 450 | V |"
        self.assertTrue(_value_fits_field("升压输出电压", "450 V", excerpt))
        found = {c.name: c.value for c in _rule_cells(excerpt, family="dpr")}
        self.assertRegex((found.get("升压输出电压") or "").replace(" ", ""), r"450V")
        self.assertEqual(found.get("BOOST最高工作电压"), "450V（升压器目标输出）")

    def test_ripple_clause_from_switched_on_off_rows(self) -> None:
        chunk = """
Generated voltage ripple 产生电压纹波
当连接高压电池时，控制器不得在高压直流母线上产生比下表规定的更高的电压纹波：
| Maximum differential ripple when the HV battery is switched on. 高压电池接通时的最大差分纹波 | V pk-pk | Rated operating conditions：16 额定工况：16 Peak operating conditio:：30 峰值工况：30 |
Generated voltage ripple UDC control 直流控制产生电压纹波
| Maximum differential ripple when the HV battery is switched off. 高压电池关闭时的最大差分纹波 | V pk-pk | 30 |
"""
        cells = {c.name: c for c in _rule_cells(chunk, family="dpr")}
        self.assertEqual(cells["直流母线纹波电压要求"].clause, "2.3.3.3.3")
        self.assertEqual(cells["高压安全-纹波电压"].clause, "2.3.3.3.4")
        off_only = {
            c.name: c
            for c in _rule_cells(
                "高压电池关闭时的最大差分纹波 | V pk-pk | 30",
                family="dpr",
            )
        }
        self.assertEqual(off_only["高压安全-纹波电压"].clause, "2.3.3.3.4")

    def test_lv_clause_is_6_5_2_not_protection(self) -> None:
        chunk = """
修订记录：修改 6.5.2 低压功耗要求
6.4.2.4 Protection
The unit shall protect against overcurrent.
### LV power consumption 低压功耗
未唤醒@仅低压上电 | ≤0.5 |
唤醒@IGBT 开管@高低压都上电 | 18W@14V@WLTC |
"""
        cells = {c.name: c for c in _rule_cells(chunk, family="dpr")}
        self.assertEqual(cells["静态电流"].clause, "6.5.2")
        self.assertEqual(cells["低压功耗要求"].clause, "6.5.2")
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        static = next(c for c in rows.values() if c.name == "静态电流")
        lv = next(c for c in rows.values() if c.name == "低压功耗要求")
        self.assertEqual(static.clause, "6.5.2")
        self.assertEqual(lv.clause, "6.5.2")
        self.assertIn("0.5", static.value)
        self.assertIn("18W", lv.value)

    def test_lv_clause_kept_when_later_pass_has_6_5_2(self) -> None:
        lv_only = """
### LV power consumption 低压功耗
未唤醒@仅低压上电 | ≤0.5 |
唤醒@IGBT 开管@高低压都上电 | 18W@14V@WLTC |
"""
        with_rev = "修订记录：修改 6.5.2 低压功耗要求\n" + lv_only
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        owner: dict = {}
        val_owner: dict = {}
        for cell in _rule_cells(lv_only, family="dpr"):
            _store_cell(cell, lv_only, rows, extra, set(), owner, val_owner)
        for cell in _rule_cells(with_rev, family="dpr"):
            _store_cell(cell, with_rev, rows, extra, set(), owner, val_owner)
        static = next(c for c in rows.values() if c.name == "静态电流")
        lv = next(c for c in rows.values() if c.name == "低压功耗要求")
        self.assertEqual(static.clause, "6.5.2")
        self.assertEqual(lv.clause, "6.5.2")

    def test_p3_stall_keeps_85_percent_at_3s(self) -> None:
        found = {c.name: c.value for c in _rule_cells(self.STALL, family="dpr")}
        stall = found.get("P3堵转扭矩/时间") or ""
        self.assertIn("85%", stall)
        self.assertIn("3s", stall)
        self.assertIn("50%", stall)
        self.assertIn("300-450", stall)

    PDF_FLAT = """
HVDC Voltage Range 高压范围
HVDC bus voltage [V]
非升压
HVDC bus voltage [V]
升压
Min level during cold ICE start 冷启动时的最低电压
160
160
Min level for limited performance 性能限制时的最低
200
160
Min level for full current 满电流时的最低电压
200
160
Max level for full current 满电流时的最高电压
450
450
Min level for full power 满功率时的最低电压
340
160
Max level for full power 满功率时的最高电压
450
450
Max limited performance 限制性能下可工作最高电压
500
500
The insulation resistance value of XCM HV circuit and ground（enclosure）shall be ≥48 MΩ,。
控制器高压回路与地之间（外壳）绝缘电阻≥48MΩ。
热态绝缘电阻≥2.5 MΩ。
Y-capacitor selection
Y-电容选择
The Y-capacitors of the XCM shall be less then the values below :
HVDC+ to GND
HVDC- to GND
PCM 660nF
PCM 660nF
BOOST input continue
Boost:195A
；Bypass:200A
Cooling connections 冷却连接
Coolant input/output spigot specification 冷却液进水口/出水口
The coolant input and output of the unit shall be designed according to VDA standard. The spigot shall
have a NW12 interface.
LV power consumption 低压功耗
未唤醒@仅低压上电
≤0.5
唤醒@IGBT 开管@高低压都上电
18W@14V@WLTC
"""

    def test_pdf_flat_reads_boost_column_and_missed_fields(self) -> None:
        found = {c.name: c.value for c in _rule_cells(self.PDF_FLAT, family="dpr")}
        working = found.get("直流工作电压范围") or ""
        self.assertIn("冷启动", working)
        self.assertIn("160", working.replace(" ", ""))
        self.assertIn("升压", working)
        self.assertIn("最低：", working)
        full = found.get("满功率(电流)工作电压") or ""
        self.assertIn("340", full)
        self.assertIn("160", full)
        self.assertIn("升压", full)
        derate = found.get("降额工作电压范围") or ""
        self.assertIn("200", derate)
        self.assertIn("160", derate)
        self.assertIn("升压", derate)
        self.assertNotRegex(derate, r"200V（上限500")
        ins = found.get("高压安全-绝缘电阻") or ""
        self.assertIn("48", ins)
        self.assertIn("2.5", ins)
        self.assertIn("热态", ins)
        ycap = found.get("高压安全-Y电容指标") or ""
        self.assertIn("660", ycap)
        self.assertIn("nF", ycap)
        boost_in = found.get("BOOST输入额定电流") or ""
        self.assertIn("195", boost_in)
        self.assertIn("200", boost_in)
        cool = found.get("冷却接口") or ""
        self.assertIn("NW12", cool)
        self.assertIn("VDA", cool)
        self.assertIn("0.5", found.get("静态电流") or "")
        lv = found.get("低压功耗要求") or ""
        self.assertIn("18W", lv)
        self.assertNotIn("125kW", found.get("P1峰值功率") or "")

    def test_expert_marked_fields(self) -> None:
        chunk = """
Propulsion CAN bus shall support CAN-FD 5Mbit/s
动力CAN总线应支持 CAN-FD
6.2.4.6以太网
The controller should reserve one Ethernet interface for subsequent calibration.
控制器应预留一路以太网接口用于后续标定。
6.2.4.5 CPSR
CPSR is a relay control signal, and the controller should be able to control the relay to close and restore the closed state.
CPSR是一个继电器控制信号，控制器应能控制继电器吸合并回采吸合状态。
6.2.3.2 High Voltage DC connection
物理连接应能够支持10s@125kW@320V-450V
6.2.3.6 高压慢充连接器
XCM应该有一个高压慢充连接器
6.3.1.1 Measurement of Inverter temperature 逆变器温度测量
Temperatures of all IGBTs for both PEI 1 & PEI 3, shall be measured.
控制器应测量大多数温度关键部件的温度，包含测量P1和P3逆变器的所有IGBT的温度。
In the range -40°C to +100°C, the measurement error shall be less than ±5 °C.
在-40℃~ +100℃范围内，测量误差应小于±5℃。
In the range＞ +100°C , the measurement error shall be less than ±3 °C.
在大于100℃时，测量误差应小于±3℃。
6.3.1.2 Coolant inlet temperature measurement
6.3.1.3 EM temperature sensors 电机温度传感器
Sensors for motor temperature, one per motor.
电机温度传感器，每个电机一个。
In the range -40°C to +100°C, the measurement error shall be less than ±5 °C.
在-40℃~ +100℃范围内，测量误差应小于±5℃。
In the range＞ +100°C , the measurement error shall be less than ±3 °C.
在大于100℃时，测量误差应小于±3℃。
6.3.1.4 Boost电感温度测量
6.3.3.1 HVAC current measurement交流相电流测量
PEI P1: The XCM shall be able to measure the HVAC current consumed or generated PEI P1 within the range - 600A to +600A peak with measurement error less than ±3%（＞100A）or ±3A（0-100A）.
Measurement error less than ±1.5%（＞100A）or ±1.5A（0-100A）at room temperature and after calibration.
PEI P3: The XCM shall be able to measure the HVAC current consumed or generated PEI P3 within the range - 300A to +300A peak with measurement error less than ±3%（＞100A）or ±3A（0-100A）.
Vibration 振动要求
1）Temperature cycle温度循环
Perform the test according to Q/JLP 030600-10 2025A Perform 4 cycles in each direction (32 hours).
2）Sine-on-random vibration正弦加随机振动试验
Sinusoidal component：The scan is performed in X, Y, and Z directions for 30 hours in each direction, and the sweep rate is 0.5Oct/min.
3）Random vibration随机振动
The unit shall meet Q/JLY J7110922D -2024.
高压元件应设计成在车内形成屏蔽系统。
Transient immunity test along high voltage supply lines use Pulse B.
Ripple noise and transient immunity test along high voltage supply lines test method according to ISO TS 7637-4-2020.
未唤醒@仅低压上电 | ≤0.5 (PCM≤0.3；OD≤0.2) |
唤醒@IGBT 开管@高低压都上电 | 18W@14V@WLTC |
低压功耗为初版设计指标，供应商完成硬件设计后需提供静态电流和工作电流计算过程，最终结果需得到吉利认可。
Continuous HVDC withstand voltage 连续高压直流耐压
The unit must withstand continuous supply voltages of maximum 500V on the HVDC bus without any permanent damages.
设备必须能承受高压直流母线上最大500V的连续供电电压，且不能造成任何永久性损坏。
6.10.3.2 HV insulation requirements 高压绝缘要求
The XCM shall meet the withstand voltage capability test according to ISO 6469-32018. The following minimum AC test voltage of a frequency between 50 Hz and 60 Hz shall be applied for 1 min:
控制器应符合ISO 6469-3-2018的耐压能力测试。以下频率在50hz至60hz之间的最小交流试验电压应施加1分钟:
(2U +1 000) VAC rms if basic insulation applies.
A maximum working voltage of 500V shall be used.
The equivalent DC test voltage is 1.41 times the AC rms value.
Active discharge of HVDC bus 高压直流母线主动放电
The XCM shall have functionality to perform an active discharge of the entire HVDC bus. During an active discharge the HVDC bus shall be discharged to a safe level, defined as a voltage below 60VDC. The active discharge shall be completed within 1s of the triggering event (opening of the HV battery contactors).
Passive discharge of HVDC bus 高压直流母线的被动放电
The XCM shall have the possibility to passively discharge the HVDC bus.The passive discharge circuitry shall be dimensioned so that the HVDC voltage in the unit, i.e. the units own internal capacitance, is below 60VDC within 120 s after opening of battery contactors.
Overvoltage due to generated back-emf反电动势导致的过压
The XCM is required to have power switches that can withstand the maximum value of back-emf on the PEI P1 and PEI P3. The specific back electromotive force shall be based on the actual state achieved by the motor.
控制器要求电源开关能够承受P1逆变器和P3逆变器上的反电动势最大值。具体反电动势以电机实际达成为准。
6.8.4.1 PEI P1 P1逆变器效率
The max efficiency should be＞99%.
最高效率应该是大于99%。
Average efficiency at least 98.2%
平均效率至少为98%
6.8.4.2 PEI P3  P3逆变器效率
The efficiency of the PEI P3 shall be optimized for the following operation regions:
应针对以下工作期间优化PEI P3的效率
The max efficiency should be ＞99%.
最高效率应该是大于99%。
Motoring: 驱动工况
Interval 1:1000~4500rpm,20~100Nm,96.65%@340V．
区间1:1000~4500rpm,20~100Nm,96.65%@340V．
Interval 2:5000~8500 RPM,20~70Nm,99%@340V．
区间2：5000~8500rpm,20~70Nm,99%@340V．
Interval 3:9000~13000 RPM,20~30Nm,99.25%@340V．
区间3：9000-13000rpm,20-30Nm,99.25%@340V．
combined efficiency 综合效率：区间1均值*35%+区间2均值*35% +区间3均值*30% @340V ≥98.25%
| BOOST input peak current BOOST输入峰值电流 | 400A@10S | A |
| BOOST input continue current 升压输入持续电流 | Boost:195A  ；Bypass:200A | A |
| BOOST efficiency target　BOOST效率目标 | 最高效率： 99.5%@直通， 99%@升压 输入功率5-50kW，效率≥99.1%@300V直通 输入功率5-60kW，效率≥98.8%@升压至340V 输入功率5-40kW，效率≥98.5%@升压至400-450V | ％ |
| 表1：DHTS160--boost 峰值＞10S |  |  |  |  |  |  |  |  |
| 表3：DHT160S --boost    持续电流 |  |  |  |  |  |  |  |  |
Y-capacitor selection
Y-电容选择
PCM 660nF
HVDC peak power 高压直流峰值功率
125kW@320V-450V@10S
"""
        found = {c.name: c for c in _rule_cells(chunk, family="dpr")}
        val = {name: cell.value for name, cell in found.items()}
        self.assertIn("500V", val.get("高压安全-耐电压") or "")
        self.assertIn("永久性损坏", val.get("高压安全-耐电压") or "")
        self.assertNotIn("ISO 6469", val.get("高压安全-耐电压") or "")
        self.assertIn("660", val.get("高压安全-Y电容指标") or "")
        static = val.get("静态电流") or ""
        self.assertIn("0.5", static)
        self.assertIn("0.3", static)
        self.assertIn("0.2", static)
        lv = val.get("低压功耗要求") or ""
        self.assertIn("18W", lv)
        igbt = val.get("IGBT温度采样精度") or ""
        self.assertIn("±5", igbt)
        self.assertIn("±3", igbt)
        self.assertIn("IGBT", igbt)
        motor = val.get("电机温度采样精度") or ""
        self.assertIn("±5", motor)
        self.assertIn("±3", motor)
        p1_eta = val.get("P1逆变器效率指标") or ""
        self.assertIn("99", p1_eta)
        self.assertIn("98.2", p1_eta)
        p3_eta = val.get("P3逆变器效率指标") or ""
        self.assertIn("99", p3_eta)
        self.assertIn("98.25", p3_eta)
        self.assertIn("区间1", p3_eta)
        self.assertNotRegex(p3_eta, r"98\.2(?!\d)")
        self.assertNotIn("99.5", p3_eta)
        boost_eta = val.get("升压效率") or ""
        self.assertIn("99.5", boost_eta)
        self.assertIn("98.5", boost_eta)
        self.assertIn("99.1", boost_eta)
        boost_p = found.get("升压输出功率")
        self.assertIsNotNone(boost_p)
        self.assertIn("180kW", boost_p.value)
        self.assertIn("87.75kW", boost_p.value)
        self.assertIn("峰值功率", boost_p.value)
        self.assertIn("持续稳定功率", boost_p.value)
        self.assertIn("最大电压450V×最大电流400A@10s", boost_p.value)
        self.assertIn("最大电压450V×持续电流195A", boost_p.value)
        self.assertIn("195A", boost_p.value)
        self.assertNotIn("64", boost_p.value)
        self.assertNotIn("160", boost_p.value)
        self.assertNotRegex(boost_p.value, r"200A")
        self.assertNotRegex(boost_p.value, r"64\s*[–\-~～]\s*180")
        self.assertTrue((boost_p.note or "").startswith("由物理公式计算"))
        self.assertIn("最大电压450V×最大电流400A@10s", boost_p.note or "")
        self.assertIn("最大电压450V×持续电流195A", boost_p.note or "")
        self.assertEqual(boost_p.review_status, STATUS_PARTIAL)
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        stored68 = next(c for c in rows.values() if c.name == "升压输出功率")
        self.assertIn("180kW", stored68.value)
        self.assertIn("87.75kW", stored68.value)
        self.assertIn("最大电压450V×最大电流400A@10s", stored68.value)
        self.assertIn("195A", stored68.value)
        phase = val.get("相电流采样精度") or ""
        self.assertIn("600", phase)
        self.assertIn("300", phase)
        self.assertIn("P1", phase)
        self.assertIn("P3", phase)
        bemf = found.get("P1反电动势（Back EMF）")
        self.assertIsNotNone(bemf)
        self.assertIn("反电动势", bemf.value)
        self.assertEqual(bemf.review_status, STATUS_PARTIAL)
        cpsr = found.get("CPSR电压范围/采样精度/延时")
        self.assertIsNotNone(cpsr)
        self.assertIn("继电器", cpsr.value)
        self.assertIn("无", cpsr.value)
        self.assertEqual(cpsr.review_status, STATUS_PARTIAL)
        vibe = val.get("振动要求") or ""
        self.assertIn("030600", vibe)
        self.assertIn("正弦", vibe)
        self.assertIn("随机", vibe)
        emc = val.get("EMC等级") or ""
        self.assertIn("J7110922D", emc)
        self.assertIn("7637-4", emc)
        self.assertIn("屏蔽", emc)
        comm = val.get("通讯方式") or ""
        self.assertRegex(comm.replace(" ", ""), r"CAN-?FD")
        self.assertIn("以太网", comm)
        conn = found.get("高压连接器保护")
        self.assertIsNotNone(conn)
        self.assertIn("高压直流连接", conn.value)
        self.assertNotIn("125kW", conn.value)
        self.assertNotIn("62.5", conn.value)
        self.assertEqual(conn.clause, "6.2.3.2")
        self.assertEqual(conn.review_status, STATUS_PARTIAL)
        charge = found.get("升压充电功能")
        self.assertIsNotNone(charge)
        self.assertIn("慢充", charge.value)
        self.assertNotIn("三种", charge.value)
        self.assertEqual(charge.review_status, STATUS_PARTIAL)
        self.assertIn("连接器", charge.note)
        self.assertIn("拓扑", charge.note)
        active = val.get("高压安全-主动放电功能") or ""
        self.assertIn("60V", active.replace(" ", ""))
        self.assertRegex(active.replace(" ", ""), r"1s")
        passive_t = val.get("高压安全-被动放电功能") or ""
        self.assertIn("120", passive_t)
        self.assertIn("60", passive_t)
        self.assertNotIn("P1峰值功率", val)

    def _stored(self, chunk: str) -> dict[str, str]:
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        seen: set = set()
        excerpt_owner: dict = {}
        value_owner: dict = {}
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, seen, excerpt_owner, value_owner)
        return {
            cell.name: cell.value
            for cell in rows.values()
            if (cell.value or "").strip()
        }

    def test_ycap_not_dropped_when_excerpt_is_heading(self) -> None:
        self.assertTrue(
            _value_fits_field(
                "高压安全-Y电容指标",
                "Y+≤660nF、Y-≤660nF（HVDC±对地）",
                "### Y-capacitor selection  Y-电容选择",
            )
        )
        found = self._stored(self.PDF_FLAT)
        self.assertIn("660", found.get("高压安全-Y电容指标") or "")

    def test_pdf_linewrap_sampling_and_p3(self) -> None:
        chunk = """
The coolant inlet temperature must
be measurable in the range -40°C to +100°C.
冷却液入口温度必须在-40°C 到+100°C 的范围内测量。
The measurement error shall be less than ± 3°C in the range of -40°C to +85°C.
HVDC voltage should be measured within the full voltage range, with a measurement error of ± 3V for
voltages less than 300V and ± 1% for voltages above 300V.
高压直流电压应在全电压范围内测量，测量误差小于300V 为±3V，300V 以上±1%。
The 12V supply voltage used internally in the XCM, for actuators and sensors, must be measured with total
accuracy error <2% and resolution <= 0.01V.
控制器内部使用的12V 电源电压(用于执行器和传感器)，必须以总精度< 2%和分辨率<= 0.01 v 进行测量。
Req based on 8 poles and 20000rpm, PEI P3 must have full performance
基于8极20000转/分, P3逆变器必须在以下基本电气频率范围内具有完整的性能
During active short circuit the maximum allowed continuous current in the P3 EM is 310 Arms;The
requirement is applicable in the complete working speed range. PEI P3 shall be able to perform under this
condition during 20s.XCM must handle transient currents around 1300Arms@1ms
在主动短路时，P3 电机允许的最大连续电流为310，该要求适用于整个工作速度范围。P3 逆变器应能在此
条件下运行20 S。
PEI P3 must be able to handle continuous AC phase current of 250Arms.
逆变器P3 须能满足交流相电流250Arms 持续值。
The active discharge shall
be completed within 1s of the triggering event (opening of the HV battery contactors).
主动放电应在触发事件(高压电池接触器打开)的1s
内完成。DC电压低于60V。
|  | · Full coolant temperature range · 全冷却液温度范围 | -40°C to +85°C |
|  | · Normal coolant temperature range · 正常冷却液温度范围 | -30°C to +65°C |
"""
        found = self._stored(chunk)
        self.assertIn("-40", found.get("电驱回路水温/采样精度/延时") or "")
        self.assertIn("±3V", found.get("母线电压采样精度") or "")
        self.assertIn("0.01", found.get("低压供电电源电压采样精度") or "")
        self.assertIn("20000", found.get("P3最高工作转速") or "")
        p3 = next(c for c in _rule_cells(chunk, family="dpr") if c.name == "P3最高工作转速")
        self.assertEqual(p3.review_status, STATUS_PARTIAL)
        self.assertIn("交流基频", p3.note)
        self.assertIn("310", found.get("P3 ASC电流能力（是否整机提供？）") or "")
        self.assertIn("250", found.get("P3额定功率相电流") or "")
        self.assertIn("1s", (found.get("高压安全-主动放电功能") or "").replace(" ", ""))
        self.assertIn("60", found.get("高压安全-主动放电功能") or "")
        cool = found.get("冷却液温度范围") or ""
        self.assertIn("-40", cool)
        self.assertIn("-30", cool)

    def test_poles_rpm_is_partial_not_max_speed(self) -> None:
        from electrical.schema import finalize_retrieval_statuses

        chunk = """
6.5.7.5 AC Fundamental frequency PEI P1
Req based on 8 poles and 16000 Rpm, PEI P1 must have full performance in the following range of the fundamental electrical frequency
基于8极16000转/分, P1逆变器必须在以下基本电气频率范围内具有完整的性能
6.5.8.5 AC Fundamental frequency PEI P3
Req based on 8 poles and 20000rpm, PEI P3 must have full performance
基于8极20000转/分, P3逆变器必须在以下基本电气频率范围内具有完整的性能
"""
        cells = {c.name: c for c in _rule_cells(chunk, family="dpr")}
        p1 = cells["P1最高工作转速"]
        p3 = cells["P3最高工作转速"]
        self.assertIn("16000", p1.value)
        self.assertIn("20000", p3.value)
        self.assertEqual(p1.review_status, STATUS_PARTIAL)
        self.assertEqual(p3.review_status, STATUS_PARTIAL)
        self.assertIn("交流基频", p1.note)
        self.assertIn("交流基频", p3.note)
        finalize_retrieval_statuses([p1, p3])
        self.assertEqual(p1.review_status, STATUS_PARTIAL)
        self.assertEqual(p3.review_status, STATUS_PARTIAL)
        self.assertNotEqual(p1.review_status, STATUS_FOUND)
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        stored_p1 = next(c for c in rows.values() if c.name == "P1最高工作转速")
        stored_p3 = next(c for c in rows.values() if c.name == "P3最高工作转速")
        finalize_retrieval_statuses([stored_p1, stored_p3])
        self.assertEqual(stored_p1.review_status, STATUS_PARTIAL)
        self.assertEqual(stored_p3.review_status, STATUS_PARTIAL)
        self.assertIn("16000", stored_p1.value)
        self.assertIn("20000", stored_p3.value)

    def test_explicit_max_speed_table_is_found(self) -> None:
        from electrical.schema import finalize_retrieval_statuses

        chunk = """
the max speed of Pl@640V  P1 电机最高转速  rpm  16000（出电功率）  17000（随转）
the max speed of P3  P3电机最高转速  rpm  20000（出功率）  22000 随转
"""
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        p1 = next(c for c in rows.values() if c.name == "P1最高工作转速")
        p3 = next(c for c in rows.values() if c.name == "P3最高工作转速")
        self.assertIn("16000", p1.value)
        self.assertIn("20000", p3.value)
        self.assertNotIn("交流基频", p1.note or "")
        self.assertNotIn("交流基频", p3.note or "")
        finalize_retrieval_statuses([p1, p3])
        self.assertEqual(p1.review_status, STATUS_FOUND)
        self.assertEqual(p3.review_status, STATUS_FOUND)


class DhtsExpertClauseTests(unittest.TestCase):
    def test_markdown_page_heading_is_not_ocr_garbage(self) -> None:
        self.assertFalse(
            _looks_like_ocr_garbage(
                "## 第 59 页 The efficiency of the PEI P3 shall be optimized"
            )
        )
        self.assertFalse(
            _looks_like_ocr_garbage("### Cooling connections冷却连接")
        )

    def test_p3_page_prefers_excerpt_marker_over_page_one(self) -> None:
        chunk = (
            "## 第 1 页\n封面目录\n"
            "6.8.4.2 PEI P3  P3逆变器效率\n"
            "## 第 59 页\n"
            "The efficiency of the PEI P3 shall be optimized for the following operation regions:\n"
            "应针对以下工作期间优化PEI P3的效率\n"
            "The max efficiency should be ＞99%.\n"
        )
        raw = next(c for c in _rule_cells(chunk, family="dpr") if c.name == "P3逆变器效率指标")
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        _store_cell(raw, chunk, rows, extra, set(), {}, {})
        stored = rows[56]
        self.assertEqual(stored.page, "59")
        self.assertNotIn("乱码", stored.note or "")

    def test_p3_efficiency_reads_combined_not_p1_average(self) -> None:
        chunk = (
            "6.8.4.1 PEI P1 P1逆变器效率\n"
            "The max efficiency should be＞99%.\n"
            "最高效率应该是大于99%。\n"
            "Average efficiency at least 98.2%\n"
            "平均效率至少为98%\n"
            "6.8.4.2 PEI P3  P3逆变器效率\n"
            "The efficiency of the PEI P3 shall be optimized for the following operation regions:\n"
            "应针对以下工作期间优化PEI P3的效率\n"
            "The max efficiency should be ＞99%.\n"
            "最高效率应该是大于99%。\n"
            "Motoring: 驱动工况\n"
            "Interval 1:1000~4500rpm,20~100Nm,96.65%@340V．\n"
            "区间1:1000~4500rpm,20~100Nm,96.65%@340V．\n"
            "Interval 2:5000~8500 RPM,20~70Nm,99%@340V．\n"
            "区间2：5000~8500rpm,20~70Nm,99%@340V．\n"
            "Interval 3:9000~13000 RPM,20~30Nm,99.25%@340V．\n"
            "区间3：9000-13000rpm,20-30Nm,99.25%@340V．\n"
            "combined efficiency 综合效率：区间1均值*35%+区间2均值*35% +区间3均值*30% @340V ≥98.25%\n"
        )
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        p1 = rows[41]
        p3 = rows[56]
        self.assertIn("98.2", p1.value)
        self.assertIn("98.25", p3.value)
        self.assertIn("区间1", p3.value)
        self.assertIn("96.65", p3.value)
        self.assertNotRegex(p3.value, r"98\.2(?!\d)")
        self.assertEqual(p3.clause, "6.8.4.2")

    def test_p3_efficiency_does_not_copy_p1_average_when_p3_has_max_only(self) -> None:
        chunk = (
            "6.8.4.1 PEI P1 P1逆变器效率\n"
            "The max efficiency should be＞99%.\n"
            "Average efficiency at least 98.2%\n"
            "平均效率至少为98%\n"
            "6.8.4.2 PEI P3  P3逆变器效率\n"
            "The max efficiency should be ＞99%.\n"
            "最高效率应该是大于99%。\n"
        )
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        self.assertIn("98.2", rows[41].value)
        self.assertIn("＞99", rows[56].value)
        self.assertNotRegex(rows[56].value or "", r"98\.2")

    def test_pcm_table_eta_keeps_max_and_interval(self) -> None:
        """2.3.2 表：最高效率行与区间/平均效率行并存，不互相覆盖。"""
        super_evo = """
## 2.3.2 P&E 动力经济性
| PCM maximum efficiency @800V PCM最高效率 @800V | % | P1:≥99.5%； P3:≥99.8 %； |
| PCM P1 efficiency @800V PCM P1区间效率 @800V | % | 单挡：≥98.6%，-30- -60Nm@ 4500-9500rpm |
| PCM P3 efficiency @800V PCM P3区间效率 @800V | % | 区间占比：区间1、区间2、区间3 |
"""
        four_ldht = """
## 2.3.2 P&E 动力经济性
PCM maximum efficiency @640V  PCM 最高效率 @640V  %  P1:≥99.5%;  P3:≥99.9%;
PCM P1 efficiency @640V  PCM P1 区间效率 @640V  %  -40 ~ -80Nm@ 4000-8000rpm ≥98.5%
区间1:20-190Nm@0-4500rpm,≥96.9%
区间 2:20-130Nm@4500-7500rpm,≥98.6%
PCM P3 区间效率 @640V  PCM P3 efficiency @640V  %  区间 3:20-100Nm@7500-11500rpm,≥98%  总考核目标效率≥97.67%（目标效率权重=区间一*0.42+区间二*0.22+区间三*0.36）（以总考核目标效率进行验收）
PCM cooling  水冷
voltage utilization ratio
The matched motor parameter information is as follows:
"""

        def stored(chunk: str) -> dict:
            rows = {c.seq: c for c in empty_template_rows()}
            extra: list = []
            for cell in _rule_cells(chunk, family="dpr"):
                _store_cell(cell, chunk, rows, extra, set(), {}, {})
            return rows

        se = stored(super_evo)
        self.assertIn("99.5", se[41].value)
        self.assertIn("98.6", se[41].value)
        self.assertIn("单挡", se[41].value)
        self.assertNotIn("区间1", se[41].value)
        self.assertIn("99.8", se[56].value)
        self.assertIn("区间1", se[56].value)
        self.assertNotRegex(se[56].value, r"98\.2(?!\d)")
        self.assertEqual(se[41].clause, "2.3.2")
        self.assertEqual(se[56].clause, "2.3.2")

        ld = stored(four_ldht)
        self.assertIn("99.5", ld[41].value)
        self.assertIn("98.5", ld[41].value)
        self.assertIn("-40", ld[41].value)
        self.assertNotIn("96.9", ld[41].value)
        self.assertNotIn("97.67", ld[41].value)
        self.assertNotIn("区间1", ld[41].value)
        self.assertIn("99.9", ld[56].value)
        self.assertIn("96.9", ld[56].value)
        self.assertIn("97.67", ld[56].value)
        self.assertIn("区间1", ld[56].value)
        self.assertNotIn("-40", ld[56].value)
        self.assertNotRegex(ld[56].value, r"98\.2(?!\d)")
        self.assertTrue(
            _value_fits_field(
                "P1逆变器效率指标",
                "-40 ~ -80Nm@ 4000-8000rpm ≥98.5%",
                "PCM P1 efficiency @640V PCM P1 区间效率 @640V % -40 ~ -80Nm@ 4000-8000rpm ≥98.5%",
            )
        )
        self.assertTrue(
            _value_fits_field(
                "P3逆变器效率指标",
                "区间1:20-190Nm@0-4500rpm,≥96.9%；总考核目标效率≥97.67%",
                "PCM P3 区间效率 @640V PCM P3 efficiency @640V 总考核目标效率≥97.67%",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "P3逆变器效率指标",
                "最高效率＞99%；平均效率至少 98.2%",
                "6.8.4.1 PEI P1 P1逆变器效率 Average efficiency at least 98.2%",
            )
        )

    def test_coolant_drop_uses_6_8_3_not_interface_flow_resistance(self) -> None:
        chunk = (
            "Cooling flow resistance requirement for XCM: ≤ 35Kpa@65 ℃@10L/min;（with OD）\n"
            "6.2.3.1 XCM LV signal interfaces\n"
            "Coolant pressure drop 冷却回路压降\n"
            "The maximum allowed coolant pressure drop in the unit is 35Kpa at 10 liter/min "
            "and +65°C input temperature.\n"
            "当输入温度为+65℃，输入流量为10L /min时，控制器最大允许冷却回路压降为35Kpa。\n"
            "### Heat loss 热损失\n"
            "The maximum heat loss to be cooled by the water coolant circuit from the XCM "
            "shall be ≤ 6.17KW, at constant speed conditions.\n"
            "在恒速条件下，由控制器的水冷却回路冷却的最大热损失应≤6.17KW。\n"
        )
        cells = {c.name: c for c in _rule_cells(chunk, family="dpr") if c.name == "冷却回路压降"}
        self.assertTrue(cells)
        drop = None
        for cell in _rule_cells(chunk, family="dpr"):
            if cell.name == "冷却回路压降":
                drop = cell
        self.assertIsNotNone(drop)
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        owner: dict = {}
        val_owner: dict = {}
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), owner, val_owner)
        stored = rows[71]
        self.assertEqual(stored.clause, "6.8.3")
        self.assertIn("Coolant pressure drop", stored.excerpt)
        _store_cell(
            ExtractedCell(
                seq=2,
                name="设计范围是否包含OD上移功能",
                value="with OD",
                excerpt=(
                    "Cooling flow resistance requirement for XCM: ≤ 35Kpa@65 ℃@10L/min;"
                    "（with OD）, The pressure resistance of the waterway is ≥ 200KPa."
                ),
                clause="6.2.2",
                confidence=0.85,
            ),
            chunk,
            rows,
            extra,
            set(),
            owner,
            val_owner,
        )
        self.assertFalse((rows[2].value or "").strip())
        heat = rows[120]
        self.assertIn("6.17", heat.value)
        self.assertNotEqual(heat.clause, "6.8.3")
        self.assertFalse(heat.clause)

    def test_emc_summary_from_generic_clause_not_catalog(self) -> None:
        chunk = (
            "| Q/JLY J7110922D-2024 | Electromagnetic compatibility specification "
            "for high-voltage components of electric passenger vehicles |\n"
            "6.5.8.1 AC Active short circuit current PEI P3\n"
            "2.3.3.3  Generic EMC requirements电磁兼容总体要求\n"
            "2.3.3.3.1 EMC requirements 电磁兼容要求\n"
            "The unit shall meet Q/JLY J7110922D -2024.\n"
            "控制器应满足Q/JLY J7110922D -2024的要求。\n"
            "The HV components shall be designed to form a shielded system in the vehicle.\n"
            "高压元件应设计成在车内形成屏蔽系统。\n"
            "Transient immunity test along high voltage supply lines use Pulse B.\n"
            "Ripple noise and transient immunity test along high voltage supply lines "
            "test method according to ISO TS 7637-4-2020.\n"
        )
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        owner: dict = {}
        val_owner: dict = {}
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), owner, val_owner)
        emc = rows[76]
        self.assertEqual(emc.clause, "2.3.3.3.1")
        self.assertIn("J7110922D", emc.value)
        self.assertIn("屏蔽", emc.value)
        self.assertIn("7637-4", emc.value)
        self.assertNotIn("6.5.8", emc.clause)
        self.assertNotIn("J7110779", emc.value)

    def test_dielectric_prefers_continuous_hvdc_over_iso6469(self) -> None:
        chunk = (
            "Continuous HVDC withstand voltage 连续高压直流耐压\n"
            "The unit must withstand continuous supply voltages of maximum 500V "
            "on the HVDC bus without any permanent damages.\n"
            "6.10.3.2 HV insulation requirements 高压绝缘要求\n"
            "The XCM shall meet the withstand voltage capability test according to ISO 6469-32018. "
            "The following minimum AC test voltage of a frequency between 50 Hz and 60 Hz "
            "shall be applied for 1 min:\n"
            "(2U +1 000) VAC rms if basic insulation applies.\n"
        )
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        owner: dict = {}
        val_owner: dict = {}
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), owner, val_owner)
        cell = rows[14]
        self.assertEqual(cell.clause, "6.6.3")
        self.assertNotEqual(cell.clause, "6.10.3.2")
        self.assertIn("500V", cell.value or "")
        self.assertIn("永久性损坏", cell.value or "")
        self.assertNotIn("ISO 6469", cell.value or "")

    def test_hipot_clause_iso6469_stays_on_printed_section(self) -> None:
        """仅有 ISO 6469 时用当节号；有 18488 时 SuperEvo 不得改成 6.6.3。"""
        chunk = (
            "6.10.3.2 HV insulation requirements 高压绝缘要求\n"
            "The XCM shall meet the withstand voltage capability test according to ISO 6469-32018. "
            "The following minimum AC test voltage of a frequency between 50 Hz and 60 Hz "
            "shall be applied for 1 min:\n"
            "(2U +1 000) VAC rms if basic insulation applies.\n"
        )
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        owner: dict = {}
        val_owner: dict = {}
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), owner, val_owner)
        cell = rows[14]
        self.assertEqual(cell.clause, "6.10.3.2")
        self.assertIn("ISO 6469", cell.value or "")
        se = (
            "6.9.3.2 HV insulation requirements 高压绝缘要求\n"
            "耐电压要求 （电控） Withstand voltage requirements of PCM "
            "应能耐受GB/T 18488-2024中表1规定的试验电压。持续时间为1min，无击穿现象，漏电流限值应≤5mA。"
            "信号端子与外壳之间，应能耐受500V的工频耐电压试验。"
        )
        se_rows = {c.seq: c for c in empty_template_rows()}
        for cell in _rule_cells(se, family="dpr"):
            _store_cell(cell, se, se_rows, [], set(), {}, {})
        self.assertNotEqual(se_rows[14].clause, "6.6.3")
        self.assertIn("18488", se_rows[14].value or "")

    def test_18488_beats_continuous_hvdc_950(self) -> None:
        chunk = (
            "6.6.3 Continuous HVDC withstand voltage 连续高压直流耐压\n"
            "The unit must withstand continuous supply voltages of maximum 950V "
            "on the HVDC bus without any permanent damages.\n"
            "6.9.3.2 HV insulation requirements 高压绝缘要求\n"
            "耐电压要求 （电控） Withstand voltage requirements of PCM "
            "应能耐受GB/T 18488-2024中表1规定的试验电压。持续时间为1min，无击穿现象，漏电流限值应≤5mA。"
            "信号端子与外壳之间，应能耐受500V的工频耐电压试验。"
        )
        rows = {c.seq: c for c in empty_template_rows()}
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, [], set(), {}, {})
        cell = rows[14]
        self.assertIn("18488", cell.value or "")
        self.assertNotEqual(cell.clause, "6.6.3")
        self.assertNotIn("950", cell.value or "")

    def test_charge_boost_fn_connector_is_partial_not_definition(self) -> None:
        from electrical.schema import STATUS_FOUND, finalize_retrieval_statuses

        chunk = (
            "6.2.3.6 高压慢充连接器\n"
            "XCM应该有一个高压慢充连接器\n"
        )
        found = {c.name: c for c in _rule_cells(chunk, family="dpr")}
        cell = found.get("升压充电功能")
        self.assertIsNotNone(cell)
        self.assertIn("慢充", cell.value)
        self.assertNotIn("三种", cell.value)
        self.assertEqual(cell.review_status, STATUS_PARTIAL)
        self.assertIn("连接器", cell.note)
        finalize_retrieval_statuses([cell])
        self.assertEqual(cell.review_status, STATUS_PARTIAL)
        self.assertNotEqual(cell.review_status, STATUS_FOUND)

    def test_charge_boost_fn_prefers_charging_buck_boost_heading(self) -> None:
        from electrical.schema import STATUS_FOUND, finalize_retrieval_statuses

        chunk = (
            "Charging Buck/Boost Function Requirements\n"
            "充电升压/降压功能需求\n"
            "6.2.3.6 高压慢充连接器\n"
            "XCM应该有一个高压慢充连接器\n"
        )
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        stored = next(c for c in rows.values() if c.name == "升压充电功能")
        self.assertIn("Charging Buck/Boost", stored.value)
        self.assertNotIn("连接器", stored.value)
        finalize_retrieval_statuses([stored])
        self.assertEqual(stored.review_status, STATUS_FOUND)

    def test_hvdc_peak_power_is_not_connector_protection(self) -> None:
        self.assertFalse(
            _value_fits_field(
                "高压连接器保护",
                "高压直流连接：物理连接支持 10s@125kW@320V-450V 峰值输入、62.5kW@320V 持续输入",
                "6.2.3.2 High Voltage DC connection 物理连接应能够支持10s@125kW@320V-450V",
            )
        )
        self.assertTrue(
            _value_fits_field(
                "高压连接器保护",
                "高压直流连接",
                "6.2.3.2 High Voltage DC connection 物理连接应能够支持10s@125kW@320V-450V",
            )
        )
        chunk = """
6.2.3.2 High Voltage DC connection 高压直流连接
物理连接应能够支持10s@125kW@320V-450V
HVDC peak power 高压直流峰值功率
125kW@320V-450V@10S
HVDC continuous power高压直流持续功率
62.5kW@320V
"""
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        conn = next(c for c in rows.values() if c.name == "高压连接器保护")
        self.assertIn("高压直流连接", conn.value or "")
        self.assertNotIn("125kW", conn.value or "")
        self.assertNotIn("62.5", conn.value or "")
        self.assertEqual(conn.clause, "6.2.3.2")
        self.assertEqual(conn.review_status, STATUS_PARTIAL)
        finalize_retrieval_statuses([conn])
        self.assertEqual(conn.review_status, STATUS_PARTIAL)
        self.assertNotEqual(conn.review_status, STATUS_FOUND)

    def test_llm_high_conf_cannot_upgrade_poles_or_connector(self) -> None:
        chunk = """
6.5.7.5 AC Fundamental frequency PEI P1
Req based on 8 poles and 16000 Rpm, PEI P1 must have full performance in the following range of the fundamental electrical frequency
6.5.8.5 AC Fundamental frequency PEI P3
Req based on 8 poles and 20000rpm, PEI P3 must have full performance
6.2.3.6 高压慢充连接器
XCM应该有一个高压慢充连接器
"""
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        overlays = (
            ExtractedCell(
                name="P1最高工作转速",
                value="16000 Rpm",
                excerpt=(
                    "Req based on 8 poles and 16000 Rpm, PEI P1 must have full "
                    "performance in the following range of the fundamental electrical frequency"
                ),
                confidence=0.85,
                extra=True,
            ),
            ExtractedCell(
                name="P3最高工作转速",
                value="20000rpm",
                excerpt="Req based on 8 poles and 20000rpm, PEI P3 must have full performance",
                confidence=0.9,
                extra=True,
            ),
            ExtractedCell(
                name="升压充电功能",
                value="有高压慢充连接器",
                excerpt="6.2.3.6 高压慢充连接器",
                confidence=0.82,
                extra=True,
            ),
        )
        for cell in overlays:
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        p1 = next(c for c in rows.values() if c.name == "P1最高工作转速")
        p3 = next(c for c in rows.values() if c.name == "P3最高工作转速")
        charge = next(c for c in rows.values() if c.name == "升压充电功能")
        finalize_retrieval_statuses([p1, p3, charge])
        self.assertEqual(p1.review_status, STATUS_PARTIAL)
        self.assertEqual(p3.review_status, STATUS_PARTIAL)
        self.assertEqual(charge.review_status, STATUS_PARTIAL)
        self.assertIn("交流基频", p1.note or "")
        self.assertIn("连接器", charge.note or "")
        self.assertNotEqual(p1.review_status, STATUS_FOUND)
        self.assertNotEqual(charge.review_status, STATUS_FOUND)

    def test_lv_clause_from_table_after_protection_no_heading(self) -> None:
        chunk = """
修订记录：修改 6.5.2 低压功耗要求
6.4.2.4 Protection
The unit shall protect against overcurrent.
| 状态@12V | 电流mA | | --- | --- | | 未唤醒@仅低压上电 | ≤0.5 (PCM≤0.3；OD≤0.2) | | 唤醒@IGBT开管@高低压都上电 | 18W@14V@WLTC |
"""
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        static = next(c for c in rows.values() if c.name == "静态电流")
        lv = next(c for c in rows.values() if c.name == "低压功耗要求")
        self.assertEqual(static.clause, "6.5.2")
        self.assertEqual(lv.clause, "6.5.2")
        self.assertIn("0.5", static.value)
        self.assertIn("18W", lv.value)

    HVDC_AFTER_PROTECTION = """
6.4.2.4 Protection 保护
Some clarification on protection requirements.
Protecting the hardware against damage at occurrence of faults.
### LVDC Voltage Range 低压范围
The XCM voltage range according to ISO 16750-2:CodeA(6~16V)
### LV power consumption 低压功耗
未唤醒@仅低压上电 | ≤0.5 |
唤醒@IGBT开管@高低压都上电 | 18W@14V@WLTC |
### HVDC Voltage Range 高压范围
|  | HVDC bus voltage [V] 非升压 | HVDC bus voltage [V] 升压 |
| --- | --- | --- |
| Min level during cold ICE start冷启动时的最低电压 | 160 | 160 |
| Min level for limited performance性能限制时的最低电压 | 200 | 160 |
| Min level for full current满电流时的最低电压 | 200 | 160 |
| Max level for full current满电流时的最高电压 | 450 | 450 |
| Min level for full power满功率时的最低电压 | 340 | 160 |
| Max level for full power满功率时的最高电压 | 450 | 450 |
| Max limited performance限制性能下可工作最高电压 | 500 | 500 |
"""

    def test_hvdc_voltage_clause_not_protection(self) -> None:
        cells = {c.name: c for c in _rule_cells(self.HVDC_AFTER_PROTECTION, family="dpr")}
        working = cells["直流工作电压范围"]
        full = cells["满功率(电流)工作电压"]
        derate = cells["降额工作电压范围"]
        self.assertIn("冷启动", (working.value or ""))
        self.assertIn("160", (working.value or "").replace(" ", ""))
        self.assertIn("最低：", working.value or "")
        self.assertIn("340", full.value or "")
        self.assertIn("200", derate.value or "")
        self.assertNotEqual(working.clause, "6.4.2.4")
        self.assertNotEqual(full.clause, "6.4.2.4")
        self.assertNotEqual(derate.clause, "6.4.2.4")
        self.assertFalse(working.clause)
        self.assertFalse(full.clause)
        self.assertFalse(derate.clause)
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(self.HVDC_AFTER_PROTECTION, family="dpr"):
            _store_cell(cell, self.HVDC_AFTER_PROTECTION, rows, extra, set(), {}, {})
        overlay = ExtractedCell(
            name="直流工作电压范围",
            value="冷启动160V；性能限制最低非升压200V/升压160V",
            excerpt="HVDC bus voltage [V] 非升压 | Min level during cold ICE start冷启动时的最低电压 | 160 | 160",
            clause="6.4.2.4",
            confidence=0.9,
        )
        _store_cell(overlay, self.HVDC_AFTER_PROTECTION, rows, extra, set(), {}, {})
        stored = next(c for c in rows.values() if c.name == "直流工作电压范围")
        self.assertNotEqual(stored.clause, "6.4.2.4")
        self.assertFalse(stored.clause)

    def test_printed_hvdc_range_clause_is_kept(self) -> None:
        chunk = """
6.5.3 HVDC Voltage Range
HVDC bus voltage [V]
Min level during cold ICE start
Min level for limited performance
Min level for full power
Max level for full power
Max limited performance
380
640
945
945
Full power is a condition where the unit can perform without any power derating.
"""
        cells = {c.name: c for c in _rule_cells(chunk, family="dpr")}
        self.assertEqual(cells["直流工作电压范围"].clause, "6.5.3")
        self.assertEqual(cells["满功率(电流)工作电压"].clause, "6.5.3")
        self.assertEqual(cells["降额工作电压范围"].clause, "6.5.3")

    def test_word_outline_hvdc_clause_not_cleared_by_unnumbered_name(self) -> None:
        chunk = self.HVDC_AFTER_PROTECTION.replace(
            "### HVDC Voltage Range 高压范围",
            "### 6.5.3 HVDC Voltage Range 高压范围",
        )
        cells = {c.name: c for c in _rule_cells(chunk, family="dpr")}
        self.assertEqual(cells["直流工作电压范围"].clause, "6.5.3")
        self.assertEqual(cells["满功率(电流)工作电压"].clause, "6.5.3")
        self.assertNotEqual(cells["直流工作电压范围"].clause, "6.4.2.4")

    def test_printed_lv_heading_is_6_5_2(self) -> None:
        chunk = """
### 6.5.2 LV power consumption 低压功耗
未唤醒@仅低压上电 | 0.5 |
唤醒@IGBT开管@高低压都上电 | 3000 |
"""
        cells = {c.name: c for c in _rule_cells(chunk, family="dpr")}
        self.assertEqual(cells["静态电流"].clause, "6.5.2")
        self.assertEqual(cells["低压功耗要求"].clause, "6.5.2")

    def test_performance_table_rows_keep_printed_2_3_2(self) -> None:
        """2.3.2 性能表后段 P3 行仍挂 2.3.2，不因超 1600 字丢号，也不发明 6.5.x。"""
        pad = (
            "P1 continuous generate power @60C@640V kW 70kW@7500rpm "
            "P1 peak generate power@60C@10s@350Arms kW 140kW,10500rpm-16000rpm\n"
        ) * 45
        chunk = (
            "### 2.3.2 Performance 性能指标\n"
            + pad
            + "P3 continuous drive power (80degC@640V) kW 120kW @ 13000rpm "
            "P3 电机额定驱动功率 @80℃@640V\n"
            "P3 peak torque (@600A@10s@640V Nm 400Nm @0-6500rpm "
            "P3 电机峰值扭矩@600A@10s@640V\n"
            "P3 continuous torque (60degC) @640V Nm 200Nm @ 0-6000rpm "
            "P3 电机额定扭矩 @60℃@640V\n"
        )
        self.assertGreater(chunk.find("120kW"), 1600)
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        rated = next(c for c in rows.values() if c.name == "P3额定功率")
        peak_t = next(c for c in rows.values() if c.name == "P3峰值扭矩/时间/对应转速范围")
        cont_t = next(c for c in rows.values() if c.name == "P3额定扭矩")
        self.assertIn("120", rated.value or "")
        self.assertIn("400", peak_t.value or "")
        self.assertIn("200", cont_t.value or "")
        self.assertEqual(rated.clause, "2.3.2")
        self.assertEqual(peak_t.clause, "2.3.2")
        self.assertEqual(cont_t.clause, "2.3.2")

    def test_p3_peak_power_duration_from_power_row_keeps_2_3_2(self) -> None:
        """4LDHT：@10sec 写在峰值功率行里，不靠 320 字内的扭矩行；条款仍是 2.3.2。"""
        pad = ("P1 continuous generate power @60C@640V kW 70kW@7500rpm\n") * 40
        far = ("P3 continuous torque (60degC) @640V Nm 200Nm @ 0-6000rpm\n") * 12
        chunk = (
            "### 2.3.2 P&E 动力经济性\n"
            + pad
            + "P3 peak drive power (@60℃@640V@10sec) kW 260kW@640V，@6500-11000rpm\n"
            "P3 电机峰值驱动功率@60℃@640V@10s\n"
            + far
            + "P3 peak torque (@600A@10s@640V Nm 400Nm @0-6500rpm\n"
        )
        self.assertGreater(chunk.find("260kW"), 1600)
        self.assertGreater(chunk.find("400Nm") - chunk.find("260kW"), 320)
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        power = next(c for c in rows.values() if c.name == "P3峰值功率")
        dur = next(c for c in rows.values() if c.name == "P3峰值功率持续时间")
        self.assertIn("260", power.value or "")
        self.assertEqual(dur.value, "10s")
        self.assertEqual(power.clause, "2.3.2")
        self.assertEqual(dur.clause, "2.3.2")
        self.assertFalse(
            _value_fits_field(
                "P3峰值功率持续时间",
                "10s",
                "PCM P3 peak current Arms 600Ams@10s",
            )
        )

    def test_p1_peak_duration_and_current_keep_2_3_2(self) -> None:
        """4LDHT：P1 @≥10s 在发电功率行；峰值电流是 Arms 不是 Ams。同表挂 2.3.2。"""
        pad = ("P1 continuous generate power @60C@640V kW 70kW@7500rpm\n") * 40
        chunk = (
            "### 2.3.2 P&E 动力经济性\n"
            + pad
            + "PCM P1 peak current  Arms  350Arms@10s\n"
            "PCM P1 峰值电流\n"
            "PCM P3 peak current  Arms  600Ams@10s\n"
            "P1 peak generate power@60℃@≥10s@350Arms  kW  140kW,10500rpm-16000rpm\n"
            "P1 电机峰值发电功率 @60℃@≥10s@350Arms\n"
        )
        self.assertGreater(chunk.find("350Arms@10s"), 1600)
        self.assertGreater(chunk.find("140kW"), 1600)
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        power = next(c for c in rows.values() if c.name == "P1峰值功率")
        dur = next(c for c in rows.values() if c.name == "P1峰值功率持续时间")
        current = next(c for c in rows.values() if c.name == "P1逆变器交流电流峰值")
        p3_current = next(c for c in rows.values() if c.name == "P3逆变器交流电流峰值")
        self.assertIn("140", power.value or "")
        self.assertEqual(dur.value, "≥10s")
        self.assertIn("350", current.value or "")
        self.assertNotIn("600", current.value or "")
        self.assertIn("600", p3_current.value or "")
        self.assertEqual(power.clause, "2.3.2")
        self.assertEqual(dur.clause, "2.3.2")
        self.assertEqual(current.clause, "2.3.2")
        self.assertFalse(
            _value_fits_field(
                "P1峰值功率持续时间",
                "10s",
                "PCM P1 peak current Arms 350Arms@10s",
            )
        )

    def test_p1_peak_generate_wrap_keeps_duration(self) -> None:
        """OCR 把 P1 peak generate 与 power@≥10s 折行时，仍从功率行收时长。"""
        chunk = (
            "### 2.3.2 P&E 动力经济性\n"
            "P1 peak generate\n"
            "power@60℃@≥10s@350Arms  kW  140kW,10500rpm-16000rpm\n"
        )
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        dur = next(c for c in rows.values() if c.name == "P1峰值功率持续时间")
        power = next(c for c in rows.values() if c.name == "P1峰值功率")
        self.assertIn("140", power.value or "")
        self.assertEqual(dur.value, "≥10s")
        self.assertEqual(dur.clause, "2.3.2")

    def test_drivability_table_rows_keep_printed_2_3_5(self) -> None:
        """2.3.5 驾驶性表后段扭矩响应仍挂 2.3.5，不因超 1600 字丢号。"""
        pad = ("Restart times 启动次数 | 1,000,000 times start (1300rpm&100Nm)\n") * 40
        chunk = (
            "### 2.3.5 驾驶性\n"
            + pad
            + "| P1 torque accuracy 发电机（P1)扭矩控制精度 | / | "
            "±3Nm@P1 e-motor torque≤100Nm ≤±3%@P1 e-motor torque＞100Nm |\n"
            "| Response time of P1 peak torque P1峰值扭矩响应时间 | ms | 100-300ms |\n"
            "| P3Tmax 电机扭矩响应时间 | ms | 0-90%持续扭矩≤40ms |\n"
        )
        self.assertGreater(chunk.find("100-300ms"), 1600)
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        resp = next(c for c in rows.values() if c.name == "扭矩响应时间")
        acc = next(c for c in rows.values() if c.name == "扭矩控制精度")
        self.assertIn("100-300ms", resp.value or "")
        self.assertEqual(resp.clause, "2.3.5")
        if acc.value:
            self.assertEqual(acc.clause, "2.3.5")
        self.assertEqual(
            _clause_for_index(chunk, chunk.find("100-300ms")),
            "2.3.5",
        )

    def test_flame_heading_4_6_not_ageing_4_3_3(self) -> None:
        """行首已印 4.6 阻燃不得沿用上一节 4.3.3 老化。"""
        pad = ("Environment cycle ageing requirement text.\n") * 45
        chunk = (
            "### 4.3.3 Environment Cycles Ageing Requirement环境循环老化要求\n"
            + pad
            + "## 4.6 Flame Retardance Requirement阻燃要求\n"
            "According Q/JLY J7110335C-2022 Limit requirements and test methods "
            "for flame retardant automotive non-metallic materials.\n"
            "根据Q/JLY J7110335C-2022汽车非金属材料阻燃性限值要求及试验方法，并提供阻燃报告。\n"
        )
        self.assertGreater(chunk.find("Flame Retardance"), 1600)
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        flame = next(c for c in rows.values() if c.name == "阻燃要求")
        self.assertIn("J7110335", flame.value or "")
        self.assertEqual(flame.clause, "4.6")
        self.assertNotEqual(flame.clause, "4.3.3")

    def test_line_start_quantity_is_not_heading_clause(self) -> None:
        chunk = "12.5 kW peak generate\nY-capacitors 660nF HVDC+ to GND\n"
        at = chunk.find("660nF")
        self.assertEqual(_heading_clause_before(chunk, at)[0], "")
        self.assertNotEqual(_clause_for_index(chunk, at), "12.5")

    def test_printed_heat_loss_clause_is_6_8_4(self) -> None:
        chunk = (
            "### 6.8.3 Coolant pressure drop 冷却回路压降\n"
            "The maximum allowed coolant pressure drop in the unit is 35Kpa at 10 liter/min "
            "and +65°C input temperature.\n"
            "### 6.8.4 Heat loss 热损失\n"
            "The maximum heat loss to be cooled by the water coolant circuit from the XCM "
            "shall be ≤ 6.17KW, at constant speed conditions.\n"
        )
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        self.assertEqual(rows[71].clause, "6.8.3")
        self.assertIn("6.17", rows[120].value)
        self.assertEqual(rows[120].clause, "6.8.4")
        self.assertNotEqual(rows[120].clause, "6.8.3")


class SuperEvoQualityGateTests(unittest.TestCase):
    YCAP_CHUNK = (
        "### 6.5.8 Y-capacitor selection Y-电容选择\n\n"
        "All components connected to HV network including Y-capacitors must have capacitor properties documented. "
        "Geely shall have the possibility to change the Y-capacitor values.\n\n"
        "The Y-capacitors of the PCM shall be less then the values below : 控制器的Y型电容应小于以下值：\n\n"
        "| HVDC+ to GND | HVDC- to GND |\n| --- | --- |\n"
        "| Y+≤130nF & Y-≤130nF | Y+≤130nF & Y-≤130nF |\n\n"
        "注：130nF为目标值，如不能满足Y电容要求，须满足结构要求\n\n"
        "### 6.5.9 Discharge放电\n"
    )

    def test_supervo_ycap_table_stores_as_found(self) -> None:
        """SuperEvo 2026-09-16：规则命中 130nF 却因拼出的摘录不在原文被丢，#17 必漏。"""
        chunk = self.YCAP_CHUNK
        cells = [c for c in _rule_cells(chunk, family="dpr") if c.name == "高压安全-Y电容指标"]
        self.assertTrue(cells)
        for cell in cells:
            self.assertTrue(_value_in_source(cell.value, cell.excerpt, chunk), cell.excerpt)
        rows = {c.seq: c for c in empty_template_rows()}
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, [], set(), {}, {})
        ycap = next(c for c in rows.values() if c.name == "高压安全-Y电容指标")
        self.assertIn("130nF", ycap.value)
        self.assertNotIn("批准", ycap.value)
        self.assertEqual(ycap.clause, "6.5.8")
        # 「Y+≤130nF & Y-≤130nF」两边带空格的 & 不是扫描花字，不得降成局部对应
        self.assertFalse(_looks_like_ocr_garbage(ycap.excerpt))
        self.assertNotIn("扫描识别花成", ycap.note or "")
        self.assertNotEqual(ycap.review_status, STATUS_PARTIAL)
        # 贴着字母的 & 仍是花字
        self.assertTrue(_looks_like_ocr_garbage("th#Hi#E&E I)#H#R#4E"))
        self.assertTrue(_looks_like_ocr_garbage("Y&E&E&F"))

    def test_ac_phase_current_cannot_be_derived_from_dc_bus(self) -> None:
        """SuperEvo #54 被算成 86.6Arms（120kW/√3/800Vdc）；交流相电流不得由 P 与 Vdc 推算。"""
        for name in (
            "P3额定功率相电流",
            "P1逆变器持续交流电流",
            "P3逆变器交流电流峰值",
            "P1逆变器交流主动短路电流",
            "P3 ASC电流能力（是否整机提供？）",
            "P3逆变器堵转电流",
        ):
            self.assertFalse(
                _derived_fits_field(name, "86.6Arms", "P3 rated drive power 120kW @ 800V"),
                name,
            )
        # 直流侧电流与功率仍可推算；原文写明的相电流仍按正常路径收
        self.assertTrue(_derived_fits_field("BOOST输入额定电流", "250A", "Boost 200kW @ 800V"))
        self.assertTrue(
            _value_fits_field(
                "P3额定功率相电流", "250Arms持续", "PEI P3 must be able to handle continuous AC phase current of 250Arms."
            )
        )
        rows = {c.seq: c for c in empty_template_rows()}
        seq = next(c.seq for c in rows.values() if c.name == "P3额定功率相电流")
        derived = ExtractedCell(
            seq=seq,
            name="P3额定功率相电流",
            value="86.6Arms",
            excerpt="P3 continuous drive power (80degC) P3电机额定驱动功率 @80℃ | kW | 120kW @ 8000~15000rpm @ 800V",
            note="由物理公式计算：I=P/(√3U)（代入 P=120kW, U=800V）",
            confidence=0.7,
        )
        chunk = "| P3 continuous drive power (80degC) P3电机额定驱动功率 @80℃ | kW | 120kW @ 8000~15000rpm @ 800V |"
        _store_cell(derived, chunk, rows, [], set(), {}, {})
        self.assertEqual(rows[seq].value, "")

    def test_integer_kg_stores_through_value_fits(self) -> None:
        chunk = SuperEvoFixTests.CHUNK
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        mass = next(c for c in rows.values() if c.name == "控制器重量")
        self.assertIn("12kg", mass.value)
        weight = next(c for c in rows.values() if c.name == "重量要求")
        self.assertIn("12kg", weight.value)

    def test_ipxxb_fills_connector_not_negative_hvil(self) -> None:
        chunk = (
            "电驱系统高压连接器：应满足GB/T4208-2017中IPXXB等级要求，"
            "若连接器采用螺栓连接，可判定满足防直触要求。\n"
            "高压互锁装置 HVIL connection | PCM 无机械互锁HVDC HVIL电路。"
            "The PCM without machine of HVIL connection\n"
        )
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        conn = next(c for c in rows.values() if c.name == "高压连接器保护")
        self.assertIn("IPXXB", conn.value)
        self.assertIn("防直触", conn.value)
        self.assertNotIn("支持 HVIL", conn.value)

    def test_ipxxb_wins_over_hvdc_connection_clause(self) -> None:
        chunk = """
6.2.3.2 High Voltage DC connection 高压直流连接
物理连接应能够支持10s@125kW@320V-450V
电驱系统高压连接器：应满足GB/T4208-2017中IPXXB等级要求，若连接器采用螺栓连接，可判定满足防直触要求。
"""
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        conn = next(c for c in rows.values() if c.name == "高压连接器保护")
        self.assertIn("IPXXB", conn.value)
        self.assertNotIn("125kW", conn.value or "")
        self.assertNotEqual(conn.clause, "6.2.3.2")

    def test_pss_fills_active_fuse(self) -> None:
        chunk = (
            "需要在三相铜排其中两相（暂定U相及V相）增加PSS（Power Safety Switch）功能，"
            "一旦检测到异常，可触发主动点爆进而保护系统的功能。"
        )
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        fuse = next(c for c in rows.values() if c.name == "主动保险功能")
        self.assertIn("PSS", fuse.value)
        self.assertIn("主动点爆", fuse.value)

    def test_superevo_lv_does_not_invent_6_5_2(self) -> None:
        chunk = """
### LV power consumption 低压功耗
未唤醒@仅低压上电 | 0.5 |
唤醒@IGBT开管@高低压都上电 | 3000 |
"""
        cells = {c.name: c for c in _rule_cells(chunk, family="dpr")}
        self.assertNotEqual(cells["静态电流"].clause, "6.5.2")
        self.assertFalse(cells["静态电流"].clause)
        self.assertFalse(cells["低压功耗要求"].clause)

    def test_cooling_skips_external_5_3_10_and_guiding_pins(self) -> None:
        chunk = """
（参考Q/JLY J7110218D-2025的5.3.10）
6.2.1.5 Guiding pins 定位销
The PCM shall have guiding pins or guiding holes to secure mounting to the DHT structure.
### Cooling connections冷却连接
The coolant inlet and outlet interfaces of the controller shall be designed in accordance with VDA standards.
"""
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        cool = next(c for c in rows.values() if c.name == "冷却接口")
        self.assertTrue(cool.value)
        self.assertNotEqual(cool.clause, "5.3.10")
        self.assertNotEqual(cool.clause, "6.2.1.5")
        self.assertFalse(cool.clause)

    def test_glued_622_cooling_heading_not_guiding_pins(self) -> None:
        """扫描件 6.2.2Cooling 粘在条款号后，不得抄上一节定位销 6.2.1.5。"""
        chunk = """
6.2.1.5 Guiding pins 定位销
The PCM shall have guiding pins or guiding holes to secure mounting to the DHT structure.
6.2.2Cooling connections 冷却连接 Coolant input/output spigot specification 冷却液进水口/出水口
The coolant input and output of the unit shall be designed according to VDA standard. NW12
"""
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        cool = next(c for c in rows.values() if c.name == "冷却接口")
        self.assertTrue(cool.value)
        self.assertEqual(cool.clause, "6.2.2")
        self.assertNotEqual(cool.clause, "6.2.1.5")

    def test_4ldht_scan_20260921_must_fix_cells(self) -> None:
        """2026-09-21 11:16 扫描件：#39 漏持续电流、#31/#48 只写一侧转速、#107 堵转水温。"""
        chunk = """
### 2.3.2 Performance
PCM P1 峰值电流 PCM P1 peak current Arms 350Arms@10s PCM P1 Continuous Current Arms 210Arms@30min PCM P3 peak current Arms 600Ams@10s
the max speed of P1@640V P1 电机最高转速@640V rpm 17000（随转） 16000（出电功率）
the max speed of P3 P3 电机最高转速 rpm 20000（出功率） 22000 随转
P1 continuous generate power@60℃@640V kW 70kW@7500rpm -12000rpm
85%峰值扭矩@3s 持续，4s-5s 功率降低 50% @65℃冷却水温 Stall Safety 堵转安全
"""
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        p1_cont = next(c for c in rows.values() if c.name == "P1逆变器持续交流电流")
        p1_max = next(c for c in rows.values() if c.name == "P1最高工作转速")
        p3_max = next(c for c in rows.values() if c.name == "P3最高工作转速")
        rated = next(c for c in rows.values() if c.name == "P1 额定转速")
        cool_t = next(c for c in rows.values() if c.name == "冷却液温度范围")
        self.assertIn("210", p1_cont.value or "")
        self.assertIn("30min", p1_cont.value or "")
        self.assertIn("16000", p1_max.value or "")
        self.assertIn("17000", p1_max.value or "")
        self.assertIn("20000", p3_max.value or "")
        self.assertIn("22000", p3_max.value or "")
        self.assertFalse((rated.value or "").strip())
        self.assertNotEqual((cool_t.value or "").strip(), "65℃")

    def test_hvdc_range_beats_pcm_busbar(self) -> None:
        chunk = """
PCM busbar working voltage range PCM母线工作电压范围 | Vdc | 530V~1150V
PCM 母线满功率电压范围 | Vdc | 800V~1066V@465Arms max 1066V~1150V,1150V线性降额至0
### HVDC Voltage Range 高压范围
| Min level during cold ICE start冷启动时的最低电压 | 530V |
| Min level for limited performance性能限制时的最低电压 | 530V |
| Min level for full power满功率时的最低电压 | 800V |
| Max level for full power满功率时的最高电压 | 1066V |
| Max limited performance限制性能下可工作最高电压 | 1125V |
Full power is a condition where the unit can perform without any power derating.
"""
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        working = next(c for c in rows.values() if c.name == "直流工作电压范围")
        full = next(c for c in rows.values() if c.name == "满功率(电流)工作电压")
        derate = next(c for c in rows.values() if c.name == "降额工作电压范围")
        self.assertIn("冷启动", working.value)
        self.assertIn("最低：", working.value)
        self.assertIn("最高：", working.value)
        self.assertNotRegex(working.value.replace(" ", ""), r"^530V[~～-]1150V$")
        self.assertIn("800", full.value)
        self.assertIn("1066", full.value)
        self.assertRegex(full.value, r"1\.满功率最低：")
        self.assertIn("1125", derate.value)
        self.assertRegex(derate.value, r"1\.限制性能最低：")
        self.assertFalse(working.clause)

    def test_connecting_kl30_is_not_backup_supply(self) -> None:
        self.assertFalse(
            _value_fits_field(
                "备份电源功能",
                "KL30接通/断开不得激活输出",
                "Connecting the KL30 (battery) must not activate outputs. "
                "Disconnecting KL30 (battery) must not activate outputs.",
            )
        )
        self.assertTrue(
            _value_fits_field(
                "备份电源功能",
                "有；KL30丢失时备用供电",
                "Back-up supply voltage if KL30 is lost KL30丢失备用电源电压",
            )
        )

    def test_scrub_pcm_boost_control_when_charge_spec_present(self) -> None:
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        chunk = (
            "PCM includes transmission control, motor control, thermal management "
            "control, boost control, and integrates power distribution module. "
            "PCM must have variants tailored to the BOOST architecture."
        )
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        drive = next(c for c in rows.values() if c.name == "设计范围是否包含驱动升压功能")
        self.assertTrue((drive.value or "").startswith("是"))
        self.assertIn("boost control", (drive.value or "").lower())
        _scrub_drive_boost_if_charge_spec(
            rows,
            chunk + "\nCharging Buck/Boost Function Requirements充电升压/降压功能需求",
        )
        drive = next(c for c in rows.values() if c.name == "设计范围是否包含驱动升压功能")
        self.assertFalse(drive.value)

    def test_llm_alias_dump_is_not_overvoltage_or_ripple(self) -> None:
        self.assertFalse(
            _value_fits_field(
                "直流电压过压保护",
                "过压点",
                "| PCM maximum efficiency @800V PCM最高效率 @800V | % | P1:≥99.5%； P3:≥99.8 %； |",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "直流母线纹波电压要求",
                "电压纹波 / 直流纹波 / 峰峰值纹波 / bus ripple / HVDC ripple",
                "Q/JLY J7211010B-2024 High voltage safety requirements",
            )
        )
        self.assertFalse(
            _value_fits_field(
                "高压安全-纹波电压",
                "接触器断开 / 断开状态纹波 / 电池断开纹波 / HV safety ripple / battery connected",
                "Q/JLY J7211010B-2024 High voltage safety requirements",
            )
        )

    def test_pcm_hvac_uses_800_and_1200_not_xcm_600(self) -> None:
        chunk = """
### HVAC Current measurements交流电流测量
PEI P1: The PCM shall be able to measure the HVAC current consumed or generated PEI P1 within the range - 800A to +800A peak with measurement error less than ±3%（＞100A）or ±3A（0-100A）.
控制器应能够测量- 800A至+800A峰值范围内消耗产生的P1逆变器高压交流电流，全生命周期测量误差小于±3%(>100A)或±3A (0-100A)。
PEI P3: The PCM shall be able to measure the HVAC current consumed or generated PEI P3 within the range - 1200A to +1200A peak with measurement error less than ±3%（＞100A）or ±3A（0-100A）.
控制器应能够测量- 1200A至+1200A峰值范围内消耗产生的P3逆变器高压交流电流，全生命周期测量误差小于±3%(>100A)或±3A (0-100A)。
"""
        found = {c.name: c.value for c in _rule_cells(chunk, family="dpr")}
        phase = found.get("相电流采样精度") or ""
        self.assertIn("800", phase)
        self.assertIn("1200", phase)
        self.assertNotIn("600A", phase)
        self.assertNotIn("300A", phase)
        self.assertNotIn("需人工复核", phase)
        self.assertNotIn("中文 −", phase)
        self.assertNotIn("英文 −", phase)
        self.assertNotIn("同档精度", phase)
        self.assertNotIn("P1峰值扭矩/时间/对应转速范围", found)
        self.assertFalse(
            _value_fits_field(
                "P1峰值扭矩/时间/对应转速范围",
                "PEI P1: The PCM shall be able to measure the HVAC current "
                "consumed or generated PEI P1 within the range - 800A to +800A "
                "peak with measurement error less than ±3%（＞100A）or ±3A（0-100A）.",
                "控制器应能够测量- 800A至+800A峰值范围内消耗产生的P1逆变器高压交流电流",
            )
        )

    def test_hvac_bilingual_conflict_writes_both_and_needs_review(self) -> None:
        chunk = """
6.3.3.1 HVAC current measurement交流相电流测量
PEI P1: The XCM shall be able to measure the HVAC current consumed or generated PEI P1 within the range - 600A to +600A peak with measurement error less than ±3%（＞100A）or ±3A（0-100A）.
控制器应能够测量- 180A至+180A峰值范围内消耗产生的P1逆变器高压交流电流，全生命周期测量误差小于±3%(>100A)或±3A (0-100A)。
室温标定后测量误差要求小于±1.5%（＞100A）or ±1.5A（0-100A）；
PEI P3: The XCM shall be able to measure the HVAC current consumed or generated PEI P3 within the range - 300A to +300A peak with measurement error less than ±3%（＞100A）or ±3A（0-100A）.
控制器应能够测量- 1000A至+1000A峰值范围内消耗产生的P3逆变器高压交流电流，全生命周期测量误差小于±3%(>100A)或±3A (0-100A)。
"""
        cells = {c.name: c for c in _rule_cells(chunk, family="dpr")}
        self.assertIn("相电流采样精度", cells)
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        stored = next(c for c in rows.values() if c.name == "相电流采样精度")
        val = stored.value or ""
        self.assertIn("180", val)
        self.assertIn("1000", val)
        self.assertIn("600A", val)
        self.assertIn("300A", val)
        self.assertIn("中文", val)
        self.assertIn("英文", val)
        self.assertIn("全生命周期", val)
        self.assertIn("±3%", val)
        self.assertIn("±1.5%", val)
        self.assertNotIn("同档精度", val)
        self.assertRegex(val, r"P3：.*±3%")
        self.assertIn("需人工复核", stored.note or "")
        self.assertEqual(stored.review_status, STATUS_PARTIAL)
        self.assertIn("180A", stored.excerpt or "")
        self.assertIn("1000A", stored.excerpt or "")
        self.assertIn("600A", stored.excerpt or "")
        self.assertIn("300A", stored.excerpt or "")

    def test_hvac_single_language_does_not_write_both(self) -> None:
        en_only = """
PEI P1: The XCM shall be able to measure the HVAC current consumed or generated PEI P1 within the range - 600A to +600A peak with measurement error less than ±3%（＞100A）or ±3A（0-100A）.
PEI P3: The XCM shall be able to measure the HVAC current consumed or generated PEI P3 within the range - 300A to +300A peak with measurement error less than ±3%（＞100A）or ±3A（0-100A）.
"""
        en_cell = next(c for c in _rule_cells(en_only, family="dpr") if c.name == "相电流采样精度")
        self.assertIn("600A", en_cell.value)
        self.assertIn("300A", en_cell.value)
        self.assertNotIn("中文", en_cell.value)
        self.assertNotIn("英文", en_cell.value)
        self.assertNotIn("需人工复核", en_cell.note or "")
        self.assertNotEqual(en_cell.review_status, STATUS_PARTIAL)

        cn_only = """
控制器应能够测量- 180A至+180A峰值范围内消耗产生的P1逆变器高压交流电流，全生命周期测量误差小于±3%(>100A)或±3A (0-100A)。
控制器应能够测量- 1000A至+1000A峰值范围内消耗产生的P3逆变器高压交流电流，全生命周期测量误差小于±3%(>100A)或±3A (0-100A)。
室温标定后测量误差要求小于±1.5%（＞100A）or ±1.5A（0-100A）；
"""
        cn_cell = next(c for c in _rule_cells(cn_only, family="dpr") if c.name == "相电流采样精度")
        self.assertIn("180", cn_cell.value)
        self.assertIn("1000", cn_cell.value)
        self.assertNotIn("600A", cn_cell.value)
        self.assertNotIn("300A", cn_cell.value)
        self.assertNotIn("英文", cn_cell.value)
        self.assertNotIn("需人工复核", cn_cell.note or "")
        self.assertNotEqual(cn_cell.review_status, STATUS_PARTIAL)

    def test_emc_from_transmission_body_not_catalog(self) -> None:
        chunk = """
| Q/JLY J7110922D-2024 | Electromagnetic compatibility specification for high-voltage components of electric passenger vehicles |
The electrical properties of the entire transmission and related electrical components shall meet the following requirements: Q/JLY J7110922D-2024, Q/JLY J7110779E-2023. The test requirements shall be subject to the signed EMC test plan.
变速器整机及相关电器零部件的电气属性均须满足以下要求Q/JLY J7110922D-2024，Q/JLY J7110779E-2023，测试要求以签订的EMC测试计划为准。
EMC testing requirements EMC测试要求：
"""
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        emc = next(c for c in rows.values() if c.name == "EMC等级")
        self.assertIn("J7110922D", emc.value)
        self.assertIn("J7110779E", emc.value)
        self.assertNotEqual(emc.clause, "2.3.3.3.1")
        catalog_only = (
            "| Q/JLY J7110922D-2024 | Electromagnetic compatibility specification "
            "for high-voltage components of electric passenger vehicles |\n"
        )
        cat = {c.name: c.value for c in _rule_cells(catalog_only, family="dpr")}
        self.assertNotIn("EMC等级", cat)

    def test_anticorrosion_keeps_l1_f3_not_xcm_heading(self) -> None:
        chunk = """
Parts anti-corrosion requirement零件防腐要求
PCM shall be meet Q/JL J160003-2024乘用车零部件防腐技术要求 L1-F3。
PCM需要满足标准Q/JL J160003-2024乘用车零部件防腐技术要求中L1-F3要求
"""
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        req = next(c for c in rows.values() if c.name == "防腐要求")
        grade = next(c for c in rows.values() if c.name == "防腐等级")
        self.assertIn("L1-F3", req.value)
        self.assertNotIn("XCM", req.value)
        self.assertEqual(grade.value, "L1-F3")

    def test_back_emf_table_skips_shown_in_hv_safety_cite(self) -> None:
        chunk = """
| P1 Back EMF(@peek speed@20℃) | Vdc | 反电势＜1200V@16500rpm，20℃，开关频率＜15kHz |
| P3 Back EMF(@peek speed@20℃) | Vdc | ＜1400V，@ 20000rpm，开关频率10kHz |
All units connected on the HVDC bus must withstand at least five (5) voltage
transient pulses without any permanent damages,as shown in 2.3.12.2
高压直流母线上连接的所有设备必须至少承受五次电压瞬变脉冲，详见2.3.12.2 HV safety 高压安全章节。
### Maximum allowed generated HVDC 允许产生的最大直流高压
The unit shall not generate continuous voltages higher than 950VDC.
### Overvoltage due to generated back-emf反电动势导致的过压
The PCM is required to have power switches that can withstand the maximum value of back-emf on the PEI P1 and PEI P3. The specific back electromotive force shall be based on the actual state achieved by the motor.
控制器要求电源开关能够承受P1逆变器和P3逆变器上的反电动势最大值。具体反电动势以电机实际达成为准。
"""
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        _fill_peak_bemf_from_motors(rows)
        p1 = next(c for c in rows.values() if c.name == "P1反电动势（Back EMF）")
        p3 = next(c for c in rows.values() if c.name == "P3 反电动势（Back EMF）")
        peak = next(c for c in rows.values() if c.name == "反电动势峰值")
        self.assertIn("1200V", p1.value)
        self.assertIn("1400V", p3.value)
        self.assertIn("1200V", peak.value)
        self.assertNotIn("1400V", peak.value)
        self.assertNotEqual(p1.clause, "2.3.12.2")
        self.assertNotEqual(p3.clause, "2.3.12.2")
        self.assertFalse(p1.clause)
        self.assertFalse(p3.clause)

    def test_peak_bemf_copies_p1_when_blank(self) -> None:
        rows = {c.seq: c for c in empty_template_rows()}
        p1 = next(c for c in rows.values() if c.name == "P1反电动势（Back EMF）")
        rows[p1.seq] = ExtractedCell(
            seq=p1.seq,
            name=p1.name,
            value="≤1000V（控制器耐受 1200V）",
            excerpt="P1 Back EMF | Vdc | ≤1000（控制器耐受 1200V）",
            confidence=0.9,
        )
        _fill_peak_bemf_from_motors(rows)
        peak = next(c for c in rows.values() if c.name == "反电动势峰值")
        self.assertIn("1000V", peak.value)
        self.assertEqual(peak.name, "反电动势峰值")


class StdRefWhenDprMissingTests(unittest.TestCase):
    """当份未给出时，方法号只写备注，抽出值仍未检索到。"""

    @classmethod
    def setUpClass(cls) -> None:
        from electrical.extract import _enterprise_manifest, _std_ref_by_seq

        if not _enterprise_manifest().get("enterprise"):
            raise unittest.SkipTest("需要 electrical-krow 已发布企标清单")
        if 13 not in _std_ref_by_seq():
            raise unittest.SkipTest("企标未挂绝缘电阻方法标准")

    def test_empty_insulation_writes_method_std_as_partial(self) -> None:
        from electrical.extract import _fill_std_ref_when_dpr_missing

        rows = {c.seq: c for c in empty_template_rows()}
        _fill_std_ref_when_dpr_missing(rows)
        cell = rows[13]
        self.assertFalse((cell.value or "").strip())
        self.assertIn("J7211010", cell.note)
        self.assertEqual(cell.review_status, STATUS_MISS)
        self.assertIn("企标方法对照", cell.note)
        self.assertNotIn("局部对应", cell.note)
        self.assertIn("030602", cell.note)
        self.assertNotIn("8000", cell.value or "")
        self.assertNotIn("8000", cell.note)
        finalize_retrieval_statuses([cell])
        self.assertEqual(cell.review_status, STATUS_MISS)

    def test_does_not_overwrite_dpr_value(self) -> None:
        from electrical.extract import _fill_std_ref_when_dpr_missing

        rows = {c.seq: c for c in empty_template_rows()}
        rows[13].value = "冷态≥48MΩ"
        rows[13].confidence = 0.9
        _fill_std_ref_when_dpr_missing(rows)
        self.assertEqual(rows[13].value, "冷态≥48MΩ")
        self.assertNotIn("企标方法对照", rows[13].note)

    def test_cooling_and_other_empty_write_method_std(self) -> None:
        from electrical.extract import _fill_std_ref_when_dpr_missing

        rows = {c.seq: c for c in empty_template_rows()}
        _fill_std_ref_when_dpr_missing(rows)
        heat = rows[72]
        self.assertFalse((heat.value or "").strip())
        self.assertIn("030600-11", heat.note)
        self.assertEqual(heat.review_status, STATUS_MISS)
        self.assertIn("企标方法对照", heat.note)
        self.assertNotIn("6.17", heat.value or "")
        self.assertNotIn("6.17", heat.note or "")
        self.assertFalse((rows[20].value or "").strip())
        self.assertIn("J7111029", rows[20].note)
        self.assertEqual(rows[20].review_status, STATUS_MISS)
        self.assertFalse((rows[98].value or "").strip())
        self.assertEqual(rows[98].review_status, STATUS_MISS)
        self.assertFalse((rows[5].value or "").strip())
        self.assertIn("030001-24", rows[5].note)
        self.assertEqual(rows[5].review_status, STATUS_MISS)
        self.assertFalse((rows[90].value or "").strip())
        self.assertFalse((rows[94].value or "").strip())
        self.assertNotIn("8000", rows[20].note)
        self.assertNotIn("8000", rows[98].note)
        self.assertNotRegex(rows[5].note or "", r"13\.5\s*V")
        self.assertIn("030600-11", rows[120].note)
        self.assertEqual(rows[120].review_status, STATUS_MISS)
        finalize_retrieval_statuses([rows[5], rows[20], rows[72], rows[90], rows[98], rows[120]])
        self.assertEqual(rows[72].review_status, STATUS_MISS)
        self.assertEqual(rows[20].review_status, STATUS_MISS)
        self.assertEqual(rows[98].review_status, STATUS_MISS)
        self.assertEqual(rows[120].review_status, STATUS_MISS)
        self.assertEqual(rows[90].review_status, STATUS_MISS)

    def test_humidity_writes_method_std_as_partial(self) -> None:
        from electrical.extract import _fill_std_ref_when_dpr_missing, _enterprise_manifest

        _enterprise_manifest.cache_clear()
        rows = {c.seq: c for c in empty_template_rows()}
        _fill_std_ref_when_dpr_missing(rows)
        cell = rows[99]
        self.assertFalse((cell.value or "").strip())
        self.assertIn("J7111029", cell.note)
        self.assertEqual(cell.review_status, STATUS_MISS)
        self.assertNotIn("8000", cell.note)

    def test_life_writes_method_not_typical_hours(self) -> None:
        from electrical.extract import _fill_std_ref_when_dpr_missing

        rows = {c.seq: c for c in empty_template_rows()}
        _fill_std_ref_when_dpr_missing(rows)
        cell = rows[107]
        self.assertFalse((cell.value or "").strip())
        self.assertIn("IEC 60068-2-2", cell.note)
        self.assertNotIn("8000", cell.note)
        self.assertNotRegex(cell.note or "", r"15\s*年")
        self.assertEqual(cell.review_status, STATUS_MISS)

    def test_hipot_and_emc_get_enterprise_method(self) -> None:
        from electrical.extract import _fill_std_ref_when_dpr_missing

        rows = {c.seq: c for c in empty_template_rows()}
        _fill_std_ref_when_dpr_missing(rows)
        self.assertFalse((rows[14].value or "").strip())
        self.assertFalse((rows[76].value or "").strip())
        self.assertIn("J7110218", rows[14].note)
        self.assertIn("J7110779", rows[76].note)
        self.assertEqual(rows[14].review_status, STATUS_MISS)
        self.assertEqual(rows[76].review_status, STATUS_MISS)


class ExpertReviewMissAscTempHvTests(unittest.TestCase):
    """专家复核：空项给下一步、ASC 电机/逆变器分列、温度量程、高压 3.3/3.4。"""

    def test_overvoltage_without_threshold_is_unretrieved_with_next_step(self) -> None:
        from electrical.extract import _fill_miss_next_step, _is_junk_value

        chunk = (
            "XCM shall protect itself from excess voltage build-up that might be "
            "caused by the rotation of the EMs. This can be done for example by "
            "using active short circuit."
        )
        self.assertTrue(
            _is_junk_value(
                chunk,
                "直流电压过压保护",
            )
        )
        found = {c.name: c.value for c in _rule_cells(chunk, family="dpr")}
        self.assertNotIn("直流电压过压保护", found)
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        _fill_miss_next_step(rows)
        ovp = next(c for c in rows.values() if c.name == "直流电压过压保护")
        self.assertFalse((ovp.value or "").strip())
        self.assertEqual(ovp.review_status, STATUS_MISS)
        self.assertIn("人工复核", ovp.note)
        self.assertNotIn("525", ovp.value or "")
        self.assertNotIn("525", ovp.note or "")
        self.assertNotIn("8000", ovp.note or "")

    def test_empty_without_method_gets_manual_review(self) -> None:
        from electrical.extract import (
            _enterprise_manifest,
            _fill_miss_next_step,
            _std_ref_by_seq,
        )

        if not _enterprise_manifest().get("enterprise") or 13 not in _std_ref_by_seq():
            raise unittest.SkipTest("需要 electrical-krow 已发布企标清单")
        rows = {c.seq: c for c in empty_template_rows()}
        _fill_miss_next_step(rows)
        ovp = next(c for c in rows.values() if c.name == "直流电压过压保护")
        self.assertFalse((ovp.value or "").strip())
        self.assertIn("人工复核", ovp.note)
        ins = rows[13]
        self.assertIn("企标方法对照", ins.note)
        self.assertNotIn("人工复核", ins.note)
        self.assertEqual(ins.review_status, STATUS_MISS)

    def test_hv_safety_clauses_33_and_34_are_not_shared(self) -> None:
        chunk = """
3.3 Insulation resistance 绝缘电阻
出厂检测值应大于100MΩ；全寿命>20MΩ。
3.4 Withstand voltage 耐电压
The XCM shall meet the withstand voltage capability test according to ISO 6469-32018. The following minimum AC test voltage of a frequency between 50 Hz and 60 Hz shall be applied for 1 min. A maximum working voltage of 500V shall be used.
3.5 Active discharge of HVDC bus 高压直流母线主动放电
The XCM shall have functionality to perform an active discharge of the entire HVDC bus. During an active discharge the HVDC bus shall be discharged to a safe level, defined as a voltage below 60VDC. The active discharge shall be completed within 1s of the triggering event.
"""
        rows = {c.seq: c for c in empty_template_rows()}
        extra: list = []
        for cell in _rule_cells(chunk, family="dpr"):
            _store_cell(cell, chunk, rows, extra, set(), {}, {})
        by_name = {c.name: c for c in rows.values() if (c.value or "").strip()}
        ins = by_name.get("高压安全-绝缘电阻")
        hipot = by_name.get("高压安全-耐电压")
        disc = by_name.get("高压安全-主动放电功能")
        self.assertIsNotNone(ins)
        self.assertIsNotNone(hipot)
        self.assertIsNotNone(disc)
        self.assertEqual(ins.clause, "3.3")
        self.assertEqual(hipot.clause, "3.4")
        self.assertEqual(disc.clause, "3.5")
        self.assertNotEqual(ins.clause, hipot.clause)

    def test_asc_motor_253_not_written_as_inverter_250(self) -> None:
        chunk = (
            "主动短路期间，P1电磁最大允许稳态电流为253Arms有效值。"
            "该要求适用于全工作速度范围。"
            "P1逆变器应能在250Arms条件下工作3.5秒。"
        )
        cells = list(_rule_cells(chunk, family="dpr"))
        found = {c.name: c for c in cells}
        asc = found.get("P1 ASC电流能力")
        rms = found.get("P1逆变器交流主动短路电流")
        self.assertIsNotNone(asc)
        self.assertIn("250", asc.value)
        self.assertNotIn("253", asc.value)
        self.assertIn("253", asc.note)
        self.assertIn("250", rms.value)
        self.assertNotIn("253", rms.value)
        self.assertFalse(
            _value_fits_field(
                "P1 ASC电流能力",
                "稳态 253Arms，全转速可持续 3.5s",
                chunk,
            )
        )

    def test_p1_asc_does_not_take_continuous_200(self) -> None:
        chunk = """
6.5.7.1  AC Active short circuit current PEI P1  P1逆变器交流主动短路电流
During active short circuit the maximum allowed steady state current in the P1 EM is 250A rms. The requirement is applicable in the complete working speed range. PEI P1 shall be able to perform under this condition during 3.5s. the software switches to fw for protection after 3.5s.
主动短路期间，P1电磁最大允许稳态电流为250Arms有效值。该要求适用于全工作速度范围。P1逆变器应能在此条件下工作3.5秒。3.5s后由软件切换为FW进行保护。
Worst case transient peak current is 830A@1ms;
短时峰值电流为830Arms@1ms；
Active short circuit may be performed on the two XCM outputs P1 EM and P3 EM at the same time.
两个控制器输出P1电机和P3电机可以同时进行主动短路。

6.5.7.2 AC current continuous PEI P3  P1逆变器持续交流电流
PEI P1 must be able to handle continuous AC phase current of 200Arms.
逆变器P1须能满足交流相电流200Arms持续值。
"""
        found = {c.name: c for c in _rule_cells(chunk, family="dpr")}
        rms = found.get("P1逆变器交流主动短路电流")
        cap = found.get("P1 ASC电流能力")
        cont = found.get("P1逆变器持续交流电流")
        self.assertIsNotNone(rms)
        self.assertIsNotNone(cap)
        self.assertIsNotNone(cont)
        self.assertIn("250", rms.value)
        self.assertNotIn("200", rms.value)
        self.assertNotIn("830", rms.value)
        self.assertIn("250", cap.value)
        self.assertNotIn("200", cap.value)
        self.assertIn("830", cap.value)
        self.assertIn("可与 P3 同时", cap.value)
        self.assertIn("200", cont.value)
        self.assertFalse(
            _value_fits_field(
                "P1 ASC电流能力",
                "稳态 200Arms，全转速可持续 3.5s",
                chunk,
            )
        )
        self.assertFalse(
            _value_fits_field(
                "P1逆变器交流主动短路电流",
                "830Arms有效值，可持续3.5秒",
                chunk,
            )
        )

    def test_motor_temp_range_200_not_controller_120(self) -> None:
        chunk = """
6.3.1.1 Measurement of Inverter temperature 逆变器温度测量
Temperatures of all IGBTs for both PEI 1 & PEI 3, shall be measured.
控制器温度传感器量程120℃。
In the range -40°C to +100°C, the measurement error shall be less than ±5 °C.
In the range＞ +100°C , the measurement error shall be less than ±3 °C.
6.3.1.3 EM temperature sensors 电机温度传感器
Sensors for motor temperature, one per motor.
电机温度传感器量程至少200℃。
In the range -40°C to +100°C, the measurement error shall be less than ±5 °C.
In the range＞ +100°C , the measurement error shall be less than ±3 °C.
"""
        found = {c.name: c.value for c in _rule_cells(chunk, family="dpr")}
        motor = found.get("电机温度采样精度") or ""
        igbt = found.get("IGBT温度采样精度") or ""
        self.assertIn("200", motor)
        self.assertNotIn("120", motor)
        self.assertIn("120", igbt)
        self.assertNotIn("200", igbt)
        self.assertIn("±5", motor)
        self.assertIn("±5", igbt)
        self.assertFalse(
            _value_fits_field(
                "电机温度采样精度",
                "量程120℃",
                "控制器温度传感器量程120℃",
            )
        )


class OffListRequirementTests(unittest.TestCase):
    def test_collects_unlisted_shall_not_template_or_process(self) -> None:
        from electrical.schema import empty_template_rows

        rows = {c.seq: c for c in empty_template_rows()}
        rows[15].value = "接触器打开后 2s 内 HVDC 低于 60VDC"
        rows[15].excerpt = (
            "The PCM shall have the possibility to passively discharge "
            "the HVDC bus below 60VDC within 120 s after opening of battery contactors."
        )
        markdown = """
## 第 3 页
Contents
1 Scope
2 Requirements

## 第 12 页
The PCM shall have the possibility to passively discharge the HVDC bus below 60VDC within 120 s after opening of battery contactors.

## 第 20 页
冷却流量 shall be 0 to 10 LPM. TBD by supplier.

## 第 88 页
9.2.1 Traceability
生产追溯码应打印在壳体右侧。
The diagnostic connector pin assignment shall follow vehicle ICD-09.
Supplier to provide the remaining durability target.

## 第 90 页
4.2.2 涂镀层
涂镀层外观应平整光滑、均匀、连续。
所有涉及到的原材料禁止使用和添加回料。
"""
        extra: list = []
        _collect_off_list_requirements(markdown, rows, extra, set())
        by_name = {c.name: c for c in extra}
        self.assertIn("生产追溯码", by_name)
        self.assertEqual(by_name["生产追溯码"].value, "打印在壳体右侧")
        self.assertIn("ICD-09", " ".join(c.value for c in extra))
        self.assertTrue(any("平整光滑" in c.value for c in extra))
        self.assertTrue(any(c.value.startswith("禁止") and "回料" in c.value for c in extra))
        self.assertEqual(by_name["生产追溯码"].page, "88")
        coating = next(c for c in extra if "平整光滑" in c.value)
        self.assertEqual(coating.page, "90")
        self.assertGreaterEqual(len(extra), 3)
        self.assertFalse(any("passively discharge" in (c.value + c.name) for c in extra))
        self.assertFalse(any("TBD" in c.value for c in extra))
        self.assertFalse(any("Supplier to provide" in c.value for c in extra))
        self.assertFalse(any("0 to 10" in c.value for c in extra))
        for cell in extra:
            self.assertTrue(is_off_list_requirement(cell))
            self.assertNotEqual(cell.name, cell.value)
            self.assertNotRegex(cell.name, r"(?i)\bshall\b|\bmust\b|应")
            self.assertIn(cell.value, markdown)
            self.assertIn(cell.excerpt, markdown)
            self.assertNotIn("待供应商", cell.value)

    def test_off_list_skips_cad_deliverables_and_splits_item(self) -> None:
        self.assertIsNone(
            _split_off_list_item(
                "",
                "The supplier must provide a 3D model of the component to GEELY.",
            )
        )
        self.assertIsNone(
            _split_off_list_item("", "供应商必须向吉利提供该部件的3D模型。")
        )
        self.assertIsNone(
            _split_off_list_item("", "There shall be separation of the losses in at least the following categories:")
        )
        self.assertIsNone(
            _split_off_list_item("", "For analog I/O, the signal voltage range shall be described.")
        )
        self.assertIsNone(
            _split_off_list_item(
                "",
                "The unit must be able to withstand maximum applied dV/dt on the HVDC input as specified in Table below:",
            )
        )
        self.assertIsNone(
            _split_off_list_item("", "The vehicle shall not require the development of any new \"Special Service Tools\".")
        )
        self.assertTrue(_is_off_list_process("The 2D drawing shall contain all measurements."))
        self.assertTrue(_is_off_list_process("The supplier must present current and power consumption test results to Geely."))
        pair = _split_off_list_item("Traceability", "生产追溯码应打印在壳体右侧。")
        self.assertEqual(pair, ("生产追溯码", "打印在壳体右侧"))
        self.assertEqual(
            _split_off_list_item("涂镀层", "涂镀层外观应平整光滑、均匀、连续。"),
            ("涂镀层外观", "平整光滑、均匀、连续"),
        )
        self.assertEqual(
            _split_off_list_item("", "所有涉及到的原材料禁止使用和添加回料。"),
            ("所有涉及到的原材料", "禁止使用和添加回料"),
        )
        self.assertIsNone(
            _split_off_list_item("", "The thermal table shall be provided by the supplier.")
        )
        self.assertIsNone(_split_off_list_item("", "可再生材料的使用应不少于xx%。"))
        self.assertIsNone(
            _split_off_list_item(
                "",
                "连接器的尺寸必须正确，以便在故障情况下，既不会超过绝缘材料的故障温度，也不会超过连接线的故障温度。验证方法1A0010 FET中规定的高侧驱动输出故障条件。",
            )
        )
        self.assertTrue(
            _is_off_list_process(
                "连接器的尺寸必须正确，以便在故障情况下，既不会超过绝缘材料的故障温度。"
            )
        )
        self.assertEqual(
            _split_off_list_item("", "在最终组装过程中，不得在零件上添加胶水/润滑剂。"),
            ("胶水/润滑剂", "不得在零件上添加胶水/润滑剂"),
        )

    def test_maps_active_discharge_to_template(self) -> None:
        self.assertTrue(
            _maps_to_template_field(
                "The PCM shall have the possibility to passively discharge "
                "the HVDC bus below 60VDC within 120 s"
            )
        )
        self.assertTrue(_maps_to_template_field("被动放电应在接触器打开后 120s 内完成。"))
        self.assertFalse(
            _maps_to_template_field("生产追溯码应打印在壳体右侧。")
        )
        self.assertTrue(
            _maps_to_template_field("The PEI P1 shall be able to provide 200 Arms continuously.")
        )
        self.assertTrue(
            _maps_to_template_field("The PEI P3 shall be able to provide 250 Arms continuously.")
        )
        self.assertTrue(
            _maps_to_template_field(
                "Passive discharge of the HVDC bus shall be possible down to 500VDC."
            )
        )
        self.assertTrue(
            _maps_to_template_field("The coolant circuit shall operate between -40℃ and 70℃.")
        )
        self.assertTrue(_maps_to_template_field("最高效率应该是大于99%。"))

    def test_off_list_drops_template_electrical_and_fills_page(self) -> None:
        from electrical.schema import empty_template_rows

        rows = {c.seq: c for c in empty_template_rows()}
        markdown = """
## 第 10 页
The PEI P1 shall be able to provide 200 Arms continuously.
The PEI P3 shall be able to provide 250 Arms continuously.
Passive discharge of the HVDC bus shall be possible down to 500VDC.
The coolant circuit shall operate between -40℃ and 70℃.
最高效率应该是大于99%。
The thermal table shall be provided by the supplier.
可再生材料的使用应不少于xx%。

## 第 91 页
所有涉及到的原材料禁止使用和添加回料。
"""
        extra: list = []
        _collect_off_list_requirements(markdown, rows, extra, set())
        blob = " ".join(f"{c.name} {c.value}" for c in extra)
        self.assertFalse(any(re.search(r"200|250", c.value) for c in extra))
        self.assertNotIn("99%", blob)
        self.assertNotIn("xx%", blob)
        self.assertNotIn("thermal table", blob.lower())
        self.assertFalse(any("500VDC" in (c.value + c.name) for c in extra))
        banned = next(c for c in extra if "回料" in c.value)
        self.assertTrue(banned.value.startswith("禁止"))
        self.assertEqual(banned.page, "91")

    def test_off_list_dedupes_bilingual_and_drops_hipot_junk(self) -> None:
        from electrical.schema import empty_template_rows

        self.assertTrue(_maps_to_template_field("控制器应符合ISO 6469-3-2018的耐压能力测试。"))
        self.assertTrue(
            _maps_to_template_field(
                "The component shall be designed so that all existing voltages are within the limits of class B voltage requirements according to ISO 6469-3-2018."
            )
        )
        self.assertTrue(
            _maps_to_template_field(
                "在电基频范围≤3Hz时，控制器必须能够提供至少10s的0.95*I peck电流。"
            )
        )
        self.assertIsNone(
            _split_off_list_item("", "This document shall include the following:本文件应包括以下内容:")
        )
        self.assertIsNone(
            _split_off_list_item("", "Special attention must be taken to campaign prevention history.")
        )
        self.assertIsNone(_split_off_list_item("", "注意，必须考虑连续进料下的部件或部件。"))
        self.assertIsNone(_split_off_list_item("", "由供应商根据SAE/USCAR-37:2008-08进行测试"))
        carb = _split_off_list_item("", "控制器应能够根据CARB的立法支持2019年型号等诊断。")
        self.assertIsNotNone(carb)
        self.assertEqual(carb[0], "CARB诊断")
        self.assertTrue(carb[1].startswith("根据CARB"))
        self.assertFalse(carb[1].startswith("够"))

        rows = {c.seq: c for c in empty_template_rows()}
        markdown = """
## 第 4 页
4.2.2 涂镀层
涂镀层外观应平整光滑、均匀、连续。
生产追溯码应打印在壳体右侧。

## 第 80 页
An internal fault in any HV Component shall not lead to hazardous events.
a single point failure shall not lead to a hazardous event.
任何高压部件的内部故障不得导致危险事件，即单点故障不得导致危害事件。
控制器应符合ISO 6469-3-2018的耐压能力测试。以下频率在50hz至60hz之间的最小交流试验电压应施加1分钟。
Wiring components shall be designed in according to SAE/USCAR-12 revision 3.
布线部件应按照SAE/USCAR-12第3版设计。
Electrical and electronic components shall fulfil IPC/EIA J-STD-001G class 3.
电气和电子部件应符合IPC/EIA J-STD-001G class 3。
This document shall include the following:本文件应包括以下内容:
The following cooling conditions shall be used for verification of requirements.
当要求中提到下列冷却条件要求时，应使用下列冷却条件对要求进行验证。
供应商应提供所有电气+12V负载的电力消耗数据，所有功能的部件。
根据车内实际位置的热任务剖面，应根据IEC TR 62380在电子部件级别上执行平均故障间隔时间预测(MTBF)。
"""
        extra: list = []
        _collect_off_list_requirements(markdown, rows, extra, set())
        blob = " ".join(f"{c.name} {c.value}" for c in extra)
        self.assertTrue(any("平整光滑" in c.value for c in extra))
        self.assertTrue(any("打印" in c.value for c in extra))
        self.assertNotIn("耐压", blob)
        self.assertNotIn("This document", blob)
        self.assertFalse(any("USCAR-12" in f"{c.value}{c.excerpt}" for c in extra))
        self.assertFalse(any("J-STD-001" in f"{c.value}{c.excerpt}" for c in extra))
        self.assertFalse(any(re.search(r"危险|hazardous", f"{c.name}{c.value}", re.I) for c in extra))
        self.assertFalse(any("冷却条件" in f"{c.name}{c.value}" for c in extra))
        self.assertFalse(any("功耗" in f"{c.name}{c.value}" for c in extra))
        self.assertFalse(any(re.search(r"MTBF|平均故障间隔", f"{c.name}{c.value}") for c in extra))

    def test_off_list_name_and_value_same_language(self) -> None:
        from electrical.schema import empty_template_rows

        pair = _split_off_list_item(
            "Internal fault in HV Component",
            "任何高压元件的内部故障不应导致元件内的连续故障。",
        )
        self.assertEqual(pair, ("任何高压元件的内部故障", "不应导致元件内的连续故障"))
        self.assertEqual(
            _split_off_list_item(
                "",
                "NVH将在整车水平上进行测试，应达到吉利评级量表中定义为8级的良好NVH性能。",
            ),
            ("NVH评级", "8级"),
        )
        noise = _split_off_list_item(
            "",
            "分析程序应是在凸台界面表面施加x、y、z方向单位力的频率响应分析。TOP-60cm噪声不大于50dB(A)。",
        )
        self.assertEqual(noise, ("TOP-60cm噪声", "不大于50dB(A)"))
        en = _split_off_list_item("", "The MCU shall have minimum 32-bit registers and data-bus.")
        self.assertEqual(en, ("MCU", "have minimum 32-bit registers and data-bus"))
        self.assertIsNone(
            re.search(r"[\u4e00-\u9fff]", "".join(en or ("", "")))
        )
        zh = _split_off_list_item("", "所有涉及到的原材料禁止使用和添加回料。")
        self.assertEqual(zh, ("所有涉及到的原材料", "禁止使用和添加回料"))

        rows = {c.seq: c for c in empty_template_rows()}
        markdown = """
## 第 80 页
6.10.1.4 Internal fault in HV Component
任何高压元件的内部故障不应导致元件内的连续故障。
The MCU shall have minimum 32-bit registers and data-bus.
"""
        extra: list = []
        _collect_off_list_requirements(markdown, rows, extra, set())
        for cell in extra:
            name_zh = bool(re.search(r"[\u4e00-\u9fff]", cell.name))
            value_zh = bool(re.search(r"[\u4e00-\u9fff]", cell.value))
            self.assertEqual(name_zh, value_zh, f"{cell.name!r} / {cell.value!r}")
        self.assertTrue(any(c.name == "MCU" for c in extra))
        self.assertFalse(any("内部故障" in c.name for c in extra))
        self.assertFalse(any(c.name.startswith("Internal") and re.search(r"[\u4e00-\u9fff]", c.value) for c in extra))

    def test_off_list_merges_same_name_answers(self) -> None:
        from electrical.schema import empty_template_rows

        rows = {c.seq: c for c in empty_template_rows()}
        markdown = """
## 第 40 页
The MCU shall have minimum 32-bit registers and data-bus.
The MCU shall have minimum 4 cores, four with lock-step.
The MCU shall support a minimum of 8 CAN buses.
The development CAN bus shall support CAN-HS at 5Mbit/s.
"""
        extra: list = []
        _collect_off_list_requirements(markdown, rows, extra, set())
        mcu = [c for c in extra if c.name == "MCU"]
        self.assertEqual(len(mcu), 1)
        self.assertIn("32-bit", mcu[0].value)
        self.assertIn("4 cores", mcu[0].value)
        self.assertIn("8 CAN", mcu[0].value)
        self.assertTrue(any("5Mbit" in c.value for c in extra if c.name != "MCU"))

    def test_off_list_keeps_only_useful_product_items(self) -> None:
        from electrical.schema import empty_template_rows

        rows = {c.seq: c for c in empty_template_rows()}
        markdown = """
## 第 4 页
| 条目 | 要求 |
| --- | --- |
| 涂镀层 | 涂镀层外观应平整光滑、均匀、连续。 |
| 追溯 | 生产追溯码应打印在壳体右侧。 |
所有涉及到的原材料禁止使用和添加回料。
车内关重件塑料件制造禁止使用回料。
在最终组装过程中，不得在零件上添加胶水/润滑剂。
The MCU shall have minimum 32-bit registers and data-bus.
The development CAN bus shall support CAN-HS at 5Mbit/s.
The diagnostic connector pin assignment shall follow vehicle ICD-09.
Each I/O shall be deactivated in a controlled way when switching off KL15/CEM and PNC wakeup.

## 第 80 页
任何高压部件的内部故障不得导致危险事件。
布线部件应按照SAE/USCAR-12第3版设计。
电气和电子部件应符合IPC/EIA J-STD-001G class 3。
连接器的尺寸必须正确，以便在故障情况下不超过故障温度。
The fault current shall be considered to be 135% for Mini fuse type.
NVH将在整车水平上进行测试，应达到吉利评级量表中定义为8级的良好NVH性能。
分析程序应是在凸台界面表面施加x、y、z方向单位力的频率响应分析。TOP-60cm噪声不大于50dB(A)。
冷却液回路必须能够承受3.25 bar的绝对压力。
控制器应能够根据CARB的立法支持2019年型号等诊断。
Certain safety rules must be followed.
The pitch must be maintained as close as possible but maximum within 50 mm of any in-line or component connector.
带有接地触点的焊接继电器的电子元件应具有OCPD，以保护接地电路免受过载和短路至+12V。
"""
        extra: list = []
        _collect_off_list_requirements(markdown, rows, extra, set())
        blob = " ".join(f"{c.name} {c.value}" for c in extra)
        self.assertTrue(any("平整光滑" in c.value for c in extra))
        self.assertTrue(any("打印" in c.value for c in extra))
        self.assertTrue(any("回料" in c.value for c in extra))
        self.assertTrue(any("胶水" in c.name or "润滑剂" in c.name for c in extra))
        self.assertTrue(any(c.name == "MCU" for c in extra))
        self.assertTrue(any("5Mbit" in c.value for c in extra))
        self.assertIn("ICD-09", blob)
        self.assertTrue(any("KL15" in c.value for c in extra))
        self.assertTrue(any("3.25" in c.value for c in extra))
        self.assertTrue(any(c.name == "CARB诊断" and "CARB" in c.value for c in extra))
        nvh = next(c for c in extra if c.name == "NVH评级")
        self.assertEqual(nvh.value, "8级")
        self.assertNotIn("The objective", nvh.value)
        noise = next(c for c in extra if c.name == "TOP-60cm噪声")
        self.assertEqual(noise.value, "不大于50dB(A)")
        self.assertNotIn("凸台", noise.value)
        self.assertFalse(any("将在整车" in c.name for c in extra))
        self.assertFalse(any(c.name == "分析程序" for c in extra))
        self.assertNotIn("USCAR", blob)
        self.assertNotIn("J-STD", blob)
        self.assertNotIn("危险", blob)
        self.assertNotIn("135%", blob)
        self.assertNotIn("safety rules", blob.lower())
        self.assertFalse(any(c.name.lower() == "pitch" for c in extra))
        self.assertNotIn("OCPD", blob)
        self.assertLessEqual(len(extra), 20)

    def test_off_list_keeps_early_design_hardware_extras(self) -> None:
        from electrical.schema import empty_template_rows

        self.assertEqual(
            _split_off_list_item("", "MCU闪存应不小于2 MB。"),
            ("MCU闪存", "不小于2 MB"),
        )
        self.assertEqual(
            _split_off_list_item("", "The MCU Flash shall be at least 2 MB."),
            ("MCU Flash", "at least 2 MB"),
        )
        self.assertEqual(
            _split_off_list_item("", "调试口应提供JTAG和SWD。"),
            ("调试口", "提供JTAG和SWD"),
        )
        self.assertEqual(
            _split_off_list_item("", "冷却液应为体积比50%的乙二醇水溶液。"),
            ("冷却液", "50%的乙二醇"),
        )
        self.assertEqual(
            _split_off_list_item("", "爬电距离应不小于8 mm。"),
            ("爬电距离", "不小于8 mm"),
        )
        self.assertEqual(
            _split_off_list_item("", "接地电阻应不大于10 mΩ。"),
            ("接地电阻", "不大于10 mΩ"),
        )
        self.assertIsNone(_split_off_list_item("", "爬电距离应满足2.5 kV耐压要求。"))
        self.assertIsNone(
            _split_off_list_item("", "The software shall be flashed via the diagnostic connector.")
        )

        rows = {c.seq: c for c in empty_template_rows()}
        markdown = """
## 第 30 页
MCU闪存应不小于2 MB。
SRAM应不小于512 KB。
MCU主频应为160 MHz。
调试口应提供JTAG和SWD。
冷却液应为体积比50%的乙二醇水溶液。
壳体应设置防水透气阀。
爬电距离应不小于8 mm。
电气间隙应不小于4 mm。
接地电阻应不大于10 mΩ。
接地点数量应为2个。

## 第 80 页
控制器绝缘电阻应当不小于48 MΩ。
The coolant circuit shall operate between -40℃ and 70℃.
爬电距离应满足2.5 kV耐压要求。
The software shall be flashed via the diagnostic connector.
The pitch must be maintained as close as possible but maximum within 50 mm of any in-line or component connector.
"""
        extra: list = []
        _collect_off_list_requirements(markdown, rows, extra, set())
        by_name = {c.name: c for c in extra}
        blob = " ".join(f"{c.name} {c.value}" for c in extra)
        self.assertEqual(by_name["MCU闪存"].value, "不小于2 MB")
        self.assertEqual(by_name["SRAM容量"].value, "不小于512 KB")
        self.assertEqual(by_name["MCU主频"].value, "为160 MHz")
        self.assertEqual(by_name["调试口"].value, "提供JTAG和SWD")
        self.assertEqual(by_name["冷却液"].value, "50%的乙二醇")
        self.assertTrue(any("透气阀" in c.name and "透气阀" in c.value for c in extra))
        self.assertEqual(by_name["爬电距离"].value, "不小于8 mm")
        self.assertEqual(by_name["电气间隙"].value, "不小于4 mm")
        self.assertEqual(by_name["接地电阻"].value, "不大于10 mΩ")
        self.assertEqual(by_name["接地点"].value, "2个")
        self.assertNotIn("48", blob)
        self.assertNotIn("-40", blob)
        self.assertNotIn("2.5 kV", blob)
        self.assertNotIn("flashed", blob.lower())
        self.assertFalse(any(c.name.lower() == "pitch" for c in extra))
        self.assertTrue(_maps_to_template_field("控制器绝缘电阻应当不小于48 MΩ。"))
        self.assertTrue(_maps_to_template_field("The coolant circuit shall operate between -40℃ and 70℃."))

    def test_off_list_names_come_from_spec_chinese(self) -> None:
        from electrical.schema import empty_template_rows

        rows = {c.seq: c for c in empty_template_rows()}
        bilingual = """
## 第 40 页
The MCU shall have minimum 32-bit registers and data-bus.
微控制器单元应具有最小的32位寄存器和数据库 The MCU shall incorporate a floating point unit.
微控单元应包含一个浮点单元。
The development CAN bus shall support CAN-HS at 5Mbit/s.
开发CAN总线应支持5Mbit/s的CAN-HS。
Each I/O shall be deactivated in a controlled way when switching off KL15/CEM and PNC wakeup.
当关闭KL15/CEM和PNC唤醒时，每个I/O应以受控方式停用。
Shield termination shall have a contact resistance <10 mΩ to secure EMC performance.
屏蔽终端应具有<10 mΩ的接触电阻。
所有涉及到的原材料禁止使用和添加回料。
"""
        extra: list = []
        _collect_off_list_requirements(bilingual, rows, extra, set())
        names = [c.name for c in extra]
        by_name = {c.name: c for c in extra}
        self.assertIn("微控制器单元", names)
        self.assertNotIn("微控制器", names)
        self.assertNotIn("MCU", names)
        self.assertIn("开发CAN总线", names)
        self.assertFalse(any("development" in n.lower() for n in names))
        self.assertIn("每个I/O", names)
        self.assertFalse(any(n == "Each I/O" for n in names))
        self.assertEqual(sum(1 for n in names if n == "屏蔽终端"), 1)
        self.assertFalse(any(n.lower().startswith("shield") for n in names))
        self.assertNotIn("输入输出", names)
        self.assertNotIn("电控单元", names)
        self.assertIn("微控制器单元应具有最小的32位寄存器和数据库", by_name["微控制器单元"].excerpt)
        self.assertNotIn("The MCU shall", by_name["微控制器单元"].excerpt)
        self.assertNotIn("floating point", by_name["微控制器单元"].excerpt)
        self.assertIn("开发CAN总线应支持5Mbit/s的CAN-HS", by_name["开发CAN总线"].excerpt)
        self.assertNotIn("The development CAN", by_name["开发CAN总线"].excerpt)
        self.assertIn("每个I/O应以受控方式停用", by_name["每个I/O"].excerpt)
        self.assertNotIn("Each I/O shall", by_name["每个I/O"].excerpt)
        self.assertIn("屏蔽终端应具有<10 mΩ的接触电阻", by_name["屏蔽终端"].excerpt)
        self.assertNotIn("Shield termination", by_name["屏蔽终端"].excerpt)

        en_rows = {c.seq: c for c in empty_template_rows()}
        english = """
## 第 40 页
The MCU shall have minimum 32-bit registers and data-bus.
The development CAN bus shall support CAN-HS at 5Mbit/s.
"""
        en_extra: list = []
        _collect_off_list_requirements(english, en_rows, en_extra, set())
        self.assertTrue(any(c.name == "MCU" for c in en_extra))
        self.assertTrue(any("development CAN" in c.name for c in en_extra))
        self.assertFalse(any(re.search(r"[\u4e00-\u9fff]", c.name) for c in en_extra))
        self.assertTrue(any("The MCU shall" in (c.excerpt or "") for c in en_extra))


class ModelUnavailableTests(unittest.TestCase):
    def test_unavailable_model_is_not_a_chunk_skip(self) -> None:
        from electrical.extract import ExtractModelError, _parse_model_json

        def boom(*_args, **_kwargs):
            raise ExtractModelError("识别模型当前不可用，请改选其他 chat 模型。")

        with self.assertRaises(ExtractModelError):
            _parse_model_json(boom, "prompt", 1.0)


class AssistantTextTests(unittest.TestCase):
    def test_reasoning_content_used_when_content_empty(self) -> None:
        self.assertEqual(
            _assistant_text(
                {"content": "", "reasoning_content": '{"rows":[{"seq":14}]}'}
            ),
            '{"rows":[{"seq":14}]}',
        )
        self.assertEqual(_assistant_text({"content": '{"rows":[]}'}), '{"rows":[]}')
        self.assertEqual(_assistant_text({"content": ""}), "")


if __name__ == "__main__":
    unittest.main()
