# 2026-09-09 #90 同档精度要写出 ±%

- 状态：active
- 条目：#90 相电流采样精度
- 闸门：`electrical/tests/test_extract_quality.py` `test_hvac_bilingual_conflict_writes_both_and_needs_review`；`electrical/extract.py` `_hvac_phase_accuracy`

## 代价

抽出值 P3 只写「同档精度」，对表的人看不到 ±3% / ±3A、室温标定 ±1.5%。原文 P3 中文句已经写了同一套误差。

## 反事实

P1 写了全生命周期误差后仍把 P3 收成「同档精度」，下次核对表第 90 行 P3 仍没有具体精度数字。

## 二级依据

- 当份 6.3.3.1：P1、P3 中文均为全生命周期 ±3%（＞100A）或 ±3A（0–100A），室温标定后 ±1.5%/±1.5A。
- 清单 #90：相电流采样精度要量程 + ±%。

## 闸门

P1、P3 抽出值都写精度档数字，禁止用「同档精度」代替。
