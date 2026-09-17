# 2026-09-09 源表绝缘电阻/耐电压重复项从出表删除

- 状态：active
- 条目：#13 高压安全-绝缘电阻；#14 高压安全-耐电压（源表 #18/#19 已删）
- 闸门：`tests/test_clause_lexicon.py`（`test_loads_active_frames_without_duplicate_insulation_hipot`）；`tests/test_knowledge.py`（retrieve 只开 #14、企标 6.2→#13、6.3→#14）；`electrical/tests/test_extract_quality.py`（模板无 #18/#19）；`scripts/publish_knowledge.py` 拒绝把已删除序号写入企标/物理 `see_seq` 或选段名单

## 代价

源表 #18 与 #13、#19 与 #14 完全同名同值。继续当两条填、再互相拷贝，核对表会出现两格相同的绝缘电阻和两格相同的耐电压。

## 反事实

不把 #18/#19 标成 `dropped`、不做出表跳过这两行，下次仍会：绝缘电阻写两遍、耐电压写两遍，选段命中 #14 的同时再命中 #19。

## 二级依据

- 清单 gloss：#13 高压安全-绝缘电阻；#14 高压安全-耐电压。源表审查备注已写明与 #18/#19 完全同名同值。
- 用户确认：18 项、19 项与 13 项、14 项重复，可以删除。序号不重排，#20 仍是 #20。

## 闸门

- YAML `dropped: true` 的 #18/#19 不进 `clause_lexicon.json`。
- 出表 `load_template_fields` 跳过 18、19；核对表 118 行。
- 企标 6.2 只挂 #13，6.3 只挂 #14。选段只开 #14。
- 同名同步不再覆盖绝缘电阻/耐电压（条目已不存在）；冷却压降等同名对仍同步。
