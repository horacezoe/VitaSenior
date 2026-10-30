# B 公共适配申请

基线：`f1-reviewed-v1` → `1034c7698de4394b3e7695a3a820df2dcfeaf28b`。2026-10-31。

1. **未来任务停用**：DailyTask 没有 active/cancelled 状态。删除未来 slot、停用计划或缩短日期范围时，已有任务可能已有通知/FK；不能删除历史，也不能在 plan_snapshot 偷放状态。请 A 定义持久化停用字段及 DTO/统计约定。适配前 B 对需要撤销已生成任务的修改明确返回 501，事务回滚，不伪造成功。
2. **每日快照完成标记**：只靠 daily_tasks 无法区分“当天已生成且某类别不适用”和“尚未生成”。旧日期不能用新计划或新设置反推历史分母。请 A 冻结每日目标生成批次/日期标记方案。适配前 B 只物化今天及未来；历史仅使用已保存任务，不按现行计划补写。没有保存过的历史目标无法恢复，日报不推断漏服。
3. **完整播放证明**：NotificationEvent 仅 event_id/event_type/snooze_minutes，没有 client_id、播放成功/已播放次数。无法校验 repeat_count=2/3 的完整播放或缺失音频。请 A 冻结完整播放计数、可播放素材及无音频降级约定；适配前禁止无音频的 playback_completed，多次播放不能只凭一个事件猜测已完成。
4. **组装与 ports**：请 A0 冻结任务读取、计划/设置/取消/列表/汇总等 HTTP 所需入口及 Notification 事件/系统扫描入口。ServiceBundle 尚只有窄写 port，routers/flows 不可导入实现。构造器需注入同一 Clock、AccessPort、MemoryPort/MediaPort/ChangePort；扫描入口用系统方法，不伪造 Actor。ChangeService 应在授权提案应用时调用 B 的受控变更入口，不能放松普通 child apply_change。

## 已合入 A0 后的准确缺口

已正常 merge `f1-shared-v1`，无冲突；B1 服务提交 `9299f2c`。共享文件仍只由 A 修改。请以普通后续提交补齐，不移动标签。

5. **composition 实际未注入 B**：目前仍为 MedicationService()/CheckinService()/ReportService()/NotificationService()。已实现构造器：前三者均接 `clock`；medication/checkins 关键字 `access,media,memory`；reports 关键字 `access,memory`；notifications 将接 `clock, *, access,media,changes`。请统一连线，不能把 FakeClock 流程与服务 SystemClock 混用。B 不在 flow 中重新组装或修改全局服务。
6. **健康读/纠正 port 尚缺**：请把本域已有方法冻结进对应 Protocol：MedicationPort.list(tx,actor,elder_id,active=None)->PlanList、settings(...)->ReminderSettings、update_settings(...,expected_version,patch:SettingsPatch)->ReminderSettings；CheckinPort.list(...,day,category=None,limit=20,cursor=None)->Page[Checkin]、cancel(...,checkin_id,expected_version)->CancelledCheckin；ReportPort.calendar(...,month)->Calendar、dashboard(...,day=None)->Dashboard；NotificationPort.presence(...,body:PresenceWrite)->Presence、query(...,task_state=None,limit=20,cursor=None)->Page[Notification]。方法均使用同一 tx/actor，不自行提交。
7. **Task/History 写入白名单**：A0 新建 task_service.py/history_service.py 但原任务单没有授予 B 写这两个文件；B 按用户要求严格保留白名单。可由 A 明确补充白名单，或将现有 TaskPort 连到 B 的 CheckinService.today（B 可在 health_service.py 提供同签名），HistoryPort 连到 health_service.py 的 HistoryService。后者不需 B 改白名单之外文件。
8. **系统扫描组装**：main 中 Scanner 仍无 factory/bundle 参数。B 将提供 `Scanner(..., factory=None, services=None)` 和 `scan_due(factory,services,now)`；请 A 在 lifespan 创建 factory 后绑定 scanner（或通过既有 tick_hook）。系统生成提醒需 NotificationPort 的明确 enqueue_system(tx,source_key,payload) 内部入口；不伪造老人 Actor。
9. **亲情录音所有权**：MediaPort.get_asset 只返回公共 MediaAsset，不能验证是否“发起人本人上传”，只能验证访问权；请 A 冻结引用校验 port 或明确 get_asset 对 voice_message 写入引用的所有权约定。B 不直接读取 A 的媒体表或猜路径。

B 分支会保持可合并提交；可用 `git fetch origin backend/health` 获取。未登记能力的 HTTP 继续501。原有公共测试和 schema 保留。

## 合入 A1/A2（72d7610）后的实际验证与请求

正常 merge 提交 `998ec83`；两个 B 文件的冲突已保留业务实现，并补齐 A2 的 get_plan/mark_proposal_handled/bind。本域48项已通过；增加真实 A 建档→B计划/历史导入 HTTP 测试也通过（测试显式 composition）。

10. **公共能力一致性实际失败**：`python -m pytest tests -q --tb=short --basetemp=.pytest_cache/b-integrated` → **1 failed / 153 passed / 42 deselected**。失败是 `tests/framework/test_all_routes.py::test_every_p0_route_matches_its_capability[CHANGE04]`：B 的 mark_proposal_handled 已真实实现，使拒绝返回200；A仍登记CHANGE04=false，公共断言要求501。B没有改该公共测试，也没有把正常钩子改回桩。建议 A 对未验收入口统一能力门禁，或接齐依赖后实测并登记。B 的 perform 已在权限核对后按 capability 与同一 Clock 门禁。
11. **A2 接真实 DTO 的代码审查问题**：ChangeService.create 使用 `notification.id`，但 Notification DTO 的真实字段是 `notification_id`（A测试替身有id，未覆盖此差异）。需要 A 修正；B不为通过测试给 DTO 偷加别名。另 `_apply` 的 medication 分支无论 operation 都 get_plan(target_id)：create 的 target_id=None，deactivate 传 EmptyPatch 而 MedicationPort 冻结为None；请 A 分支按冻结契约处理。
12. **A2 系统入口与鉴权**：ChangeService._system_actor 当前构造老人 Actor 供扫描使用，未满足任务单“系统任务不伪造用户Actor”；mark_played 自身也未核对 actor/elder。B只通过 apply_due(tx,now) 调 A，不在 B复制这些状态机。请 A提供明确内部授权应用入口并复核 mark_played 权限。
13. **A2 通知音频**：create 只传文字、不传audio；B禁止无音频的playback_completed，因此实际60秒窗口尚无法由前端完整走通。请 A/C冻结事务外 TTS或预制演示音频准备流程。B不在写锁内调用TTS、不把无音频的完成当成完整播报。

可直接采用的 composition 接线（所有编辑仍由 A执行；先正常合入B与C）：

```python
access = AccessService()
media = MediaService(clock, settings)
memory = MemoryService(clock, access)  # C已发布的构造器
medication = MedicationService(clock, access=access, media=media, memory=memory)
checkins = CheckinService(clock, access=access, media=media, memory=memory)
changes = ChangeService(clock, settings)
notifications = NotificationService(clock, access=access, media=media, changes=changes)
reports = ReportService(clock, access=access, memory=memory)
changes.bind(medication=medication, notifications=notifications, memory=memory)
# ServiceBundle: tasks=checkins, history=checkins；其余用上方实例。
```

CheckinService.today / import_demo_history 已在白名单 health_service.py 实现 A0 两个准确 port，无需 B 改 task_service.py/history_service.py。历史导入按 demo_id+elder 的 task.source_key 一次性去重、明确demo_seed、不建通知；多个药物计划或slot不匹配时不猜 fixture 的plan_index。当前实时扫描使用 `notifications.scan(tx, now)` 确定性内部方法；A可在现有tick_hook内同tx协调它与changes.apply_due，或补入正式系统port后交B接线。勿同时启用两套tick导致重复结算。
