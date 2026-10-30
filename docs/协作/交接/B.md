# B 健康域交接

分支 `backend/health`，独立 checkout `.health-work`。共同基线 `f1-reviewed-v1` → `1034c7698de4394b3e7695a3a820df2dcfeaf28b`，包含复验代码 `497fc4ce6ede5ee951c57cd06913197391633f56`。测试使用 Python 3.11.5 / requirements.lock 对应的已有 `.review-venv`，独立 tmp_path SQLite；运行端口保留8002，未启动持久服务。

## B1 第一批（服务交付）

- 修改：health_service.py、medication_service.py、report_service.py、tests/health/conftest.py、tests/health/test_b1.py、变更申请/B.md。
- 已有冻结 port：MedicationService.import_draft/apply_change、CheckinService.create_or_update、ReportService.daily，签名与 F0 一致。补充本域方法提供任务、列表、设置、取消、看板和日历，等待 A0 port 冻结再接路由。
- 无服务自行 commit/rollback/创建连接；纠正/取消通过 MemoryPort 在同 tx 失效来源。测试替身的审计实际写入临时 SQLite，失败验证整笔回滚。
- 同餐替换、运动多条、用药唯一且 taken 必须显式输入；历史任务仅从保存快照读取，新计划不回填旧分母。
- 当前 HTTP 仍保留501，尚未登记任何 health 能力；未声称业务全链路完成。

实际验证（backend目录，`python` 指上述解释器）：

| 命令 | 结果 |
| --- | --- |
| python -m pytest tests/health -q --basetemp=tests/health/.tmp-b1 | 24 passed |
| python -m pytest tests/framework -q --basetemp=.pytest_cache/b-framework | 63 passed，1个既有 Starlette/httpx 弃用警告 |
| python -m app.tools.export_contract --check | matches，73f9920606bdd8c6338c67327e72adef1ea1a474352aa4c22c949e071ad75657 |
| python -m app.tools.check_architecture | Architecture OK |

给 A/C 的调用样例（须传真实 actor、同一调用方 tx；构造器 clock/memory/media 由 composition 统一注入）：

```python
plans = services.medication.import_draft(tx, actor, elder_id, confirmed_plans)
record = services.checkins.create_or_update(tx, actor, elder_id, confirmed_checkin_write)
report = services.reports.daily(tx, actor, elder_id, hk_day)
# 由应用 flow 在业务写入/动作保存/幂等完成后统一提交。
```

依赖缺口见 `docs/协作/变更申请/B.md`。首次 fetch 无 A0；第二次 fetch 已看到 f1-shared-v1，下一步保留 B1 提交后正常 merge、读取实际签名并继续适配与 B2。

## B2 服务与已冻结端口的 HTTP 交付

- B1 提交 `9299f2c`；A0 正常合入 `d616ef1`（以 git log 实际记录为准）；适配请求提交 `728825e` 已推至 `origin/backend/health`。
- 已实现 NotificationService.enqueue/handle_event，以及本域 presence/query/scan；扫描通过明确系统入口选取当天目标，不创建 Actor，不请求 TTS/推送。Scanner 支持 factory/services/scan_hook，由集成人接线。
- 回执逐次完整播放计数：每次完整播放发送一个新的 playback_completed.event_id；相同 ID 重放不累计。累计到 repeat_count 才置 played、同 tx 调 A mark_played。无素材、无可见心跳、未接听均不能启动窗口。该约定未增加 DTO 字段，需前端/A 确认；不声称真实设备播放已验收。
- 已接存在的 typed ports 对应 PLAN02/03、TASK01、REC02/03、REPORT01、NOTI03 应用 flow；共享 Clock 未接时明确501。缺少 port 的其它 HTTP 尚为占位，所有 health 能力仍为 false。
- 实际合跑：`python -m pytest tests/health tests/framework -q --basetemp=.pytest_cache/b-all-2` → **113 passed / 42 deselected / 1个既有警告**（health 43，framework 70）。HTTP 使用真实鉴权/SQLite/幂等，测试中显式注入本域服务及 MemoryPort 替身；非生产组装。
- 仍未完成：生产 composition、缺失读/取消/设置 ports、任务停用/历史日期完成标记、亲情录音所有权与文字转音频、真实 A/C 全链路、P1 推送、手机回执。均未冒充通过。

第三次 fetch 看到 A1/A2 已发布至 `origin/backend/platform`（72d7610）；下一步正常合入，按新增 get_plan/mark_proposal_handled 补实现并验证真实依赖。
