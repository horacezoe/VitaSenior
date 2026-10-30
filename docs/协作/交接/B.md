# B 健康域交接

## 最新进展（本节覆盖下方此前交接）

已正常快进合入 `integration/f1@51dc555`（A/C真实组装与共享ports/模型）。剩余health路由已接齐，B已按默认组装真实HTTP验证开启16项能力：PLAN01–03、SET01–02、TASK01、REC01–04、DASH01、CAL01、REPORT01、NOTI01/02/04。A此前提到的7项pending接口均已开启；health_capabilities不再为空。

NOTI03的service、幂等与普通录音回执已实测，暂不启用公开能力：A的提案音频仍是提示音，没有播报修改内容，不能启动60秒窗口。剩余准确依赖见 [变更申请/B.md](../变更申请/B.md) 顶部。现有完整播放窗口服务集成测试从明确的已持久化提案/音频fixture开始，不替代真实提案内容播报。

- 适配cancelled_at与DailyGoalBatch：保留已发生/有记录/已送达快照；撤销/重加尚未发生的未来目标复用行；空类别生成也落批次，不用新设置回写旧日期。
- 亲情提醒通过A媒体port验证本人录音，并将受控字节分享给目标家庭；否则采用B白名单fixtures/health内四个固定中文演示语音。精确文本与SHA-256可复核，绝不使用提示音替代内容。未知文字保留文字/audio=null。所有音频准备在写事务外。
- 更新服务对不合法旧计划返回422；允许合法schedule patch修复旧数据，不放宽schema。原公共fixture空slots曾触发500，已用业务校验处理，公共测试未改。
- 最新本域命令：`python -m pytest tests/health -q --tb=short -rx --basetemp=.pytest_cache/b-verified-routing` → **85 passed / 1 xfailed**。xfail是上述A设置提案未来目标不同步的已复现问题，不算通过。
- 契约和架构检查通过，hash仍为A发布的 `4b7ade26f590902a4eb131920589184b95e0b54a293e9df80ac9f8aa4859532c`。
- `integration_smoke --strict` 当前 **34 OK / 4 PENDING / 0 FAIL，退出1**：3个NOTI03待A真实播报，另1个为脚本中午创建08:00计划的过去任务问题，详见申请。不将严格联调声明为通过。

下一步合入刚发布的C修正 `1e31bb6`（包括用药任务ID持久化）并复跑全量；完整P0仍待共享事项解决，P1推送未启动。

---

日期：2026-10-31。**B 域服务及已冻结 port 的 flow 已交付；生产 P0 全链路尚未完成，health 能力仍为 false。** 不能把替身验证或单个状态机通过当成三轮集成验收通过。剩余公共依赖已有具体申请，见 [变更申请/B.md](../变更申请/B.md)。

## 1. 分支、基线与提交

- 远端分支：`origin/backend/health`（https://github.com/horacezoe/VitaSenior/tree/backend/health）。独立 checkout：`E:/CUHKSZ/project/vitasenior/.health-work`；根目录原文件与 `.framework-review` 未改。
- 已执行 `git fetch origin --tags`；从 `f1-reviewed-v1` 创建分支，标签解引用为 `1034c7698de4394b3e7695a3a820df2dcfeaf28b`，其父提交为已复验代码 `497fc4ce6ede5ee951c57cd06913197391633f56`。
- A0 标签 `f1-shared-v1` 解引用为 `10d51af92715354a2ecd1d5469810272a406c621`，正常 merge 为 `aae25c4`；未 reset、未移动标签。
- A1/A2 `origin/backend/platform` 的 `72d7610` 已正常 merge 为 `998ec83`。两个 B 文件的冲突保留业务实现，并实现 A 新增的准确 get_plan/mark_proposal_handled/bind 签名。共享文件的变更仅来自正常 merge，B未直接编辑。

| 批次 | 提交 |
| --- | --- |
| B1 服务 + 24项初验 | `9299f2c` |
| A0 适配缺口 | `728825e` |
| B2 服务/扫描/HTTP协调 + 43项本域验证 | `6ef7e66` |
| 合入A1/A2，补冻结钩子 | `998ec83` |
| 演示历史、未来目标边界、公共缺口 | `b1535f8` |
| 真实A窗口/拒绝/重启验证、禁用未注入时钟的回退 | `9cfe39b1f367d4685fc172fc039982536fa491a8` |

## 2. 实际改动文件

白名单内：

- `backend/app/services/{health,medication,notification,report}_service.py`
- `backend/app/application/health_flows.py`、`backend/app/routers/health.py`、`backend/app/scheduler.py`
- `backend/tests/health/{__init__,conftest,helpers,test_b1,test_b2,test_history,test_http,test_change_integration}.py`
- `docs/协作/交接/B.md`、`docs/协作/变更申请/B.md`

未直接改动 core/models/schemas/contracts/main/composition/依赖/公共测试。task_service.py/history_service.py 不在原白名单，B没有修改；A可将 TaskPort/HistoryPort 接到同一 CheckinService 实例的 today/import_demo_history。

## 3. 服务与可调用入口

已有正式 port 的实际实现：

| Port | 入口 |
| --- | --- |
| MedicationPort | import_draft / apply_change / get_plan |
| CheckinPort | create_or_update |
| ReportPort | daily |
| NotificationPort | enqueue / handle_event / mark_proposal_handled |
| TaskPort | CheckinService.today |
| HistoryPort | CheckinService.import_demo_history |

本域已测试方法、待 A 加入正式 port：MedicationService.list/settings/update_settings，CheckinService.list/cancel，ReportService.calendar/dashboard，NotificationService.presence/query/scan。准确建议签名与 composition 样例在变更申请中，B未另造共享 DTO/Protocol。

- 同餐替换并增加版本；运动多条；具体药物任务唯一。校验 elder/type/date/plan/task/slot；taken 仅来自明确输入；not_taken 和未记录分别表达。过期版本、错关联与重复药物记录无部分提交。
- 记录修订 JSON 重新赋值；纠正/取消在同 tx 调 C MemoryPort，失败整笔回滚。日报/日历/看板用同一计算入口。
- 已保存任务作为历史分母；不按新计划补写过去。新建/改期不回填已过去的用药义务。需要撤销已生成未来任务但共享模型没有状态时明确501，不删记录或偷放 JSON 标志。
- 历史仅显式 demo 导入，source=demo_seed，按 demo_id+elder 的稳定 task.source_key 去重；不生成历史来电、不覆盖用户记录；多个计划/slot不匹配时不猜历史用药。
- 每10秒可发可见心跳，有效期25秒；多页任一有效即可。查询无送达副作用；回执 event_id 持久化幂等，子女/其他老人不可代发。
- displayed→answered→played 单向。每个新的 playback_completed.event_id 代表一次完整播放，累计到 repeat_count 才调用 A mark_played；重放不累计。该逐次回执约定仍需 A/前端确认；无音频不允许完成。
- task_state 与 delivery_state 分离；提案只能走 A明确接受/拒绝；听完/handled 均不创建服药记录。
- scan(tx,now) 是本域内部系统入口，不伪造 Actor；仅生成当天到期待办，餐后无餐不生成，source_key 去重、纠正后已送达不重新来电。Scanner 可在同一短事务调用 A apply_due 和确定性 scan_hook。无 TTS/推送/模型慢调用。
- 服务需要 Clock 时必须注入，未接线返回501；不会自己创建 SystemClock，避免 FakeClock 混用。

已接 flow：PLAN02/03、TASK01、REC02/03、REPORT01、NOTI03。权限在写事务内复核；幂等结果与业务同提交。TASK/report 物化快照使用 BEGIN IMMEDIATE 防并发重复。生产能力未验收时权限核对后明确501；**其余健康 HTTP 保留占位，尚未登记任何 health 能力**。

## 4. 最新实际验证

Windows / Python 3.11.5，使用既有 `.review-venv` 的锁定依赖；测试全部 tmp_path SQLite，临时基目录在本 checkout 的 `.pytest_cache`。初批 `.tmp-b1` 已清理。未创建或清空任何人的运行库；未启动持久服务，预留端口8002。将来运行使用本 checkout 独立 `backend/data/health` 及其 SQLite，不复用 A/C 数据目录。

以下在 backend 目录执行；python 为 `../../.review-venv/Scripts/python.exe`：

| 命令 | 实际结果 |
| --- | --- |
| python -m pytest tests/health -q --tb=short --basetemp=.pytest_cache/b-health-clock-final | **57 passed**，1个既有警告 |
| python -m pytest tests -q --tb=short --basetemp=.pytest_cache/b-delivery-final | **165 passed / 1 failed / 42 deselected**，1个既有警告 |
| python -m pytest tests/framework -q -m f0_stage --basetemp=.pytest_cache/b-f0-stage | **42 skipped / 70 deselected**（A1能力已开启，按A的阶段规则） |
| python -m app.tools.export_contract --check | matches，`6a2de0894ef6de2094799d9e3c1d4cef884d317cc62c336c98f535dd1527720d` |
| python -m app.tools.check_architecture | Architecture OK |
| python -m pip check | No broken requirements found |
| git diff --check | 无错误 |

唯一全量失败：`test_every_p0_route_matches_its_capability[CHANGE04]`。B关闭通知钩子落地后，A的拒绝路径返回200，但 A仍登记CHANGE04=false，公共契约要求501。B保留此失败与公共断言，已申请由 A修正能力门禁/接线后验收登记。**全量测试尚未全绿。**

57项包含真实 HTTP 鉴权/幂等/并发/回滚；真实 A建档→B计划/历史导入与重复确认；从已持久化提案出发，B回执→真实 A mark_played→59/61秒边界、拒绝、服务重启后结算。Media/Memory 的隔离测试使用明确替身；未接真实 C记忆、TTS或设备播放。真实 A创建提案另有 DTO 字段问题，详见申请；该路径没有冒充验收成功。

既有警告：Starlette TestClient/httpx 弃用提示，未屏蔽。未运行完整 AC01–AC14、三轮跨三域集成、手机HTTPS/录音/真实播放、真实provider或WebPush。P0未通过，因此未尝试P1推送；push_state保持unsupported。

## 5. 给 A/C 的调用样例与后续

```python
# 使用真实 actor，调用方拥有同一个 tx；构造器只由 composition 连线。
plans = services.medication.import_draft(tx, actor, elder_id, confirmed_plans)
record = services.checkins.create_or_update(tx, actor, elder_id, confirmed_checkin_write)
tasks = services.tasks.today(tx, actor, elder_id, hk_day)
report = services.reports.daily(tx, actor, elder_id, hk_day)
receipt = services.notifications.handle_event(tx, actor, notification_id, event, clock.now())
# 业务写入、动作保存、来源失效、幂等成功记录完成后，应用层统一 commit。
```

A接手顺序：正常合入 backend/health → 按申请连 composition/Task/History 与缺失 ports → 解决未来任务停用/每日快照标记 → 修正 A提案 DTO/内部授权/音频流程与能力门禁 → B补齐剩余路由并实测后登记 health。不要移动已发布标签，不要删公共测试。真实生产接线和完整P0仍是未完成项。
