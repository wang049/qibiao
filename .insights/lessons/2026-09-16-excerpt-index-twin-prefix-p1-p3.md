# 2026-09-16 摘录定位遇 P1/P3 同形开头要选最长公共前缀，#55/#57 不再必漏

- 状态：active
- 条目：#55 P3 ASC电流能力（核对表 51）；#57 P3逆变器交流主动短路电流（核对表 53）；对照 #40/#42（核对表 36/38）
- 闸门：`electrical/extract.py` `_find_longest_prefix_hit` / `_excerpt_index`；`electrical/tests/test_extract_quality.py::JunkAndFitTests.test_excerpt_index_prefers_longest_prefix_twin`；`electrical/examples/golden/dhts160_dpr.json` #51/#53 改为已检索到并 `value_must_not: ["1370", …]`；`tests/test_eval_golden.py` 钉状态与条款

## 代价

DHTS160 6.5.8.1 原文明确写 P3 ASC：`maximum allowed continuous current in the P3 EM is 310 Arms … during 20s … transient currents around 1300Arms@1ms`。规则 `_rule_cells` 早就能命中并生成两格，但每一份出表 #51/#53 都是「未检索到」，09-15 专家稿也照抄了这个漏，黄金集随之把漏冻成了「正确」。13:52 那份模型碰巧填对了 310 Arms，反而被黄金判 FAIL。

## 根因

`_excerpt_index` 用摘录**前 48 字**在原文里 `find` 首次出现。6.5.7.1（P1）与 6.5.8.1（P3）开头 48 字完全相同：`During active short circuit the maximum allowed `。P3 摘录被定位到先出现的 P1 句，随后 `_store_cell` 把摘录展开成 P1 原句，`_motor_label_ok` 看到「P3 条目配 P1 原文」正确拒格。守卫没错，错在定位。模型路径要看它给的摘录开头是否恰好与规则不同，所以时进时不进。

## 反事实

- 不改定位、只放宽 `_motor_label_ok`：P3 格会真的挂上 P1 的 250A 原文，比漏更贵。
- 不改定位、把前缀从 48 拉到 64：这份能过，下一份英文同模板的两节还是可能在 64 字内同形；按最长公共前缀选是通式。
- 不动黄金：修好后规则路径每次填 #51/#53，黄金每次判 FAIL，闸门变成噪音。
- 不得反过来用清单示例 `稳态310A/20s，瞬态1370A/1ms` 填格：当份是 1300，不是 1370；黄金 `value_must_not` 已禁 1370。

## 二级依据

- 当份 6.5.8.1 英中两段：310 Arms；20s；1300Arms@1ms；可与 P1 同时 ASC。
- 当份 6.5.7.1 同结构写 P1：250A rms；3.5s；830A@1ms → #40/#42 一直「已检索到」，P3 这对空着本身不合理。
- 清单 #55 D 列「需明确 P3 主动短路保护稳态和瞬态电流能力」；#57「需明确 P3 ASC 电流能力」。
- 交叉 `2026-09-09-asc-this-condition-not-continuous`（ASC 窗口与「在此条件下」归属，本次不改）、`2026-09-09-expert-miss-asc-temp-hv-clause`（电机与逆变器分列）、`2026-09-16-select-chunks-by-gap-and-split-retry`（当时记「#53 是黄金集保守」，现已查明是定位 bug）。

## 闸门

- `_find_longest_prefix_hit`：前 n 字多处命中时选与整段摘录公共前缀最长的一处；只给 48 字时退回首次出现。
- 规则路径整份 DPR 仅规则跑：#51 `310Arms（主动短路连续）`、#53 `310Arms，可持续20s；进入ASC瞬态约1300Arms@1ms`，条款 6.5.8.1；其余行无变化。
- 黄金 #51/#53 状态已检索到、条款 6.5.8.1、值含 310/1300、禁 1370；#51 另禁 250（P3 持续相电流不得串入）。
- 黄金此两格标「待专家复核确认」：依据是当份原文，不是专家稿。
- 回归：SuperEvo / Inverter SR 仅规则修前修后逐格比对，唯一变化是 SuperEvo #76 EMC 条款 2.3.15 → 2.3.16——原文「电气属性均须满足…J7110922D」句在 `### 2.3.16 EMC 电磁兼容` 之下（2.3.15 是 ELP 电气属性），修后才对。
