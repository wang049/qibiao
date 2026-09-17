# 2026-09-09 #3 驱动升压抽出值写结论不要只写是

- 状态：active
- 条目：#3 设计范围是否包含驱动升压功能
- 闸门：`electrical/tests/test_extract_quality.py`（`test_drive_boost_scope_writes_conclusion`、`test_scan_env_and_boost_scope`）；`electrical/extract.py` `_drive_boost_conclusions` / `_drive_boost_scope_score`

## 代价

DHTS 6.5.4 已写明：HVDC 输入电压较低时把高压输入升到更高电压，以改善 TM 性能。核对表第 3 行抽出值只写「是」，现场无法对照用途，也容易和 #4 行车升压、充电 Boost/Buck 看成同一句。

## 反事实

不把 shall boost HV input 写成「是；HVDC…以改善 TM 性能」、不挡住高置信度的单字「是」，下次第 3 行仍只有「是」，对表的人看不到低电压升压用途。

## 二级依据

- 当份：`The XCM shall be able to boost the HV input voltage to a higher voltage in order to improve the TM performance when HVDC input voltage is low.` 条款 6.5.4。
- 清单 gloss：#3 是驱动工况母线升压的范围判断，不是充电 Boost。交叉 `2026-09-08-item4-renamed-traction-boost`、`2026-09-07-no-printed-652-no-external-5310`。
- TM 按当份英文写牵引电机性能，不把 TM 改成变速器。

## 闸门

- 命中 HV 升压句时，#3 抽出值以「是；」开头，含 HVDC / TM，不得等于「是」。
- `_better`：详细结论压过置信度更高的单字「是」。
- 仅 `boost control` 的扫描稿仍可填 #3，但同样写结论，不单写「是」。
