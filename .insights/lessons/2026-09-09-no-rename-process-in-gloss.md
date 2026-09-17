# 2026-09-09 条款卡不写「甲方将正式名改为」

- 状态：active
- 条目：#4 设计范围是否包含行车升压功能；知识库条款卡片 gloss
- 闸门：`tests/test_knowledge.py`（`test_clause_gloss_is_current_meaning_not_rename`）；`tests/test_clause_lexicon.py`（`test_item_4_renamed_to_traction_boost`）；`scripts/publish_knowledge.py` `_assert_no_process_copy`

## 代价

#4 正式名已是「行车升压」。卡片语义写成「甲方将本条正式名由「充电升压」改为「行车升压」」。对表的人先看到改名过程，看不到本条仍是充电 Boost/Buck 范围判断。

## 反事实

不把改名过程从 gloss / notes / 人读语义里拿掉，下次条款卡和清单写法仍会把内部更名通知当成条目说明；工位知识库页也会把这句话展示出去。

## 二级依据

- 清单现行名：#4「设计范围是否包含行车升压功能」。抽出仍按充电 Boost/Buck 做范围判断，充电拓扑/电压/电流/时长见 #115。交叉 `2026-09-08-item4-renamed-traction-boost`。
- 知识库卡片回答当前语义与互斥，不回答「甲方哪天改过名」。改名过程只留在 lessons。

## 闸门

- #4 `gloss` / `split_harm` 不含「将正式名」「甲方将本条正式名」。
- `browse_catalog` 第 4 条同样不含改名过程，仍写清见 #115。
- 发布时 `_assert_no_process_copy` 扫 gloss / notes / split_harm。
