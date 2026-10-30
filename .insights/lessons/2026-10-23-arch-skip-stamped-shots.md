# 2026-10-23 斜章盖住的截图不放进表

- 状态：active
- 条目：电驱需求拆解
- 闸门：`tests/test_arch_shots.py`（`test_stamp_overlap_drops_the_covered_clip_only`）

## 代价

职责表截图被斜章「Corresponding to the Assy Product drawing」盖住，格子里的字看不清，截图仍然放进需求清单。

## 反事实

不按浅色斜章的纵向范围丢掉重叠的截图，下次被章挡住的行仍会带上一张看不清的图。章没有盖到的行仍应截图。原文摘录不因截图被丢掉而删除。

## 二级依据

- `260605_SX3id_HPCU_LDC_SR_VER1.0_보안해제.pdf` 第 12 页，约 y=271 到 y=610 有浅橙色斜章。该范围以上的表头行没有这层颜色。
- `架构对照-20261023-113645.xlsx` 中 REQ-20261023-054 起的职责行，截图被章挡住，原文摘录仍有「HMC：○」「供应商：○」。
