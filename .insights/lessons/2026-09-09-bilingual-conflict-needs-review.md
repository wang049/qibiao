# 2026-09-09 中英数字不一致写两种并复核

- 状态：active
- 条目：#90 相电流采样精度（中英对照）
- 闸门：`electrical/tests/test_extract_quality.py`（`test_hvac_bilingual_conflict_writes_both_and_needs_review`、`test_hvac_single_language_does_not_write_both`、`test_pcm_hvac_uses_800_and_1200_not_xcm_600`）；`electrical/extract.py` `_hvac_phase_accuracy` / `_hvac_peak_phrase`

## 代价

DHTS 6.3.3.1 英文仍是 P1 ±600A、P3 ±300A，中文已改为 P1 ±180A、P3 ±1000A。只留中文会把英文量程藏掉，对表的人看不到冲突；只留英文则和中文描述对不上。

## 反事实

不把冲突的中英数字都写入抽出值、不标局部对应/需人工复核，下次仍会只出一边（中文或英文），核对表看不出当份两种语言写了不同安培。仅一种语言时若仍套「中文：/英文：」或人工复核，会把无冲突的格子标成待核。

## 二级依据

- 当份同时有：英文 `PEI P1 … -600A to +600A`、`PEI P3 … -300A to +300A`；中文 P1「测量- 180A至+180A」、P3「测量- 1000A至+1000A」。
- 清单 #90：相电流采样精度要量程 + ±%。交叉 `2026-09-07-pcm-hvac-amps-not-xcm-600`（安培仍按当份，不写死）。
- SuperEvo 中英均为 P1 800A、P3 1200A，按一种值写，不标语言冲突复核。

## 闸门

- 同段中英峰值数字不同：抽出值含两侧安培（180/1000 与 600/300），备注「中英文量程不一致，需人工复核」，核对状态局部对应；摘录两侧原句都留。
- 只有中文、只有英文、或中英数字相同：抽出值一种量程，不写「中文：/英文：」，不因此标人工复核。
