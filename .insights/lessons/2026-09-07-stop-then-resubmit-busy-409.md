# 2026-09-07 点「结束」后再出同一份，不得把全站锁当成失败

- 状态：active
- 条目：工位出表任务锁（非清单格子）
- 闸门：`tests/test_jobs.py`（`test_stop_conflict_says_ending`、`test_health_exposes_active_job_and_clears_after_done`）；`tests/test_gateway.py`（`waitUntilIdle` / `isBusyConflict`）；`electrical/tests/test_job_control.py`（结束立刻跑 stop callback）

## 代价

点「结束」后立刻再点「开始出表」，页面把 `409 已有任务在出表（全站同时一份）` 当成「未能完成出表」。锁其实还在：结束只在批次之间生效，本批 LLM 最长约 90 秒；状态已是 `done` 时 `_remember` 写盘结束前锁也还没放。

## 反事实

不把「忙碌」从失败里拆出去、结束后不收在途 HTTP、出表完成不等 `busy=false` 再露出「开始出表」，下次仍会：点了结束却弹出全站一份提示，以为新提交失败。

## 二级依据

- 产品口径：全站同时一份；「结束」= 停抽并按已抽出内容出表，不是立刻开第二份。
- 用户操作：结束 → 同一份再出。应等待上一份收尾后自动开这份，不要把 409 当失败页。
- 代码：`JobStore._run_lock` 在 `_run` 的 `finally` 才 `release()`；`checkpoint()` 只在段间查看停止标志。

## 闸门

- 进行中再提交仍 409 且含「全站同时一份」；点结束后 409 文案改为「上一份正在结束出表」。
- `/api/health` 忙碌时带 `active_job`；任务 `done` 且锁释放后 `busy` 为 false，第二份可 200。
- 工位页：409/忙碌时写「上一份正在结束，结束后立即开始这份」并重试，不进失败页；`done` 后 `waitUntilIdle` 再露出「开始出表」。
- `JobControl.add_stop_callback` 在点结束时立刻调用（断开在途 HTTP）。
