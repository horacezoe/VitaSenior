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
