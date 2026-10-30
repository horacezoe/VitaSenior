# B 公共适配申请

## 当前待 A/C（合入 integration/f1@51dc555 后，本节覆盖旧申请）

此前 ports、clock/composition、Task/History绑定、C2启用、cancelled_at/DailyGoalBatch、录音所有权均已落地。B已完成剩余路由与模型适配，实际默认组装验收后开启16项health能力；A此前指出的7项全部开启。旧申请作为追溯保留，不再以那些已解决事项阻塞。

B最新代码 `be0ae4c` 已合入A `51dc555` 与C `1e31bb6`；最终全量 **266 passed / 42 deselected / 1 xfailed**，真实默认Uvicorn网络冒烟通过。1项strict xfail就是下面第2项，不算通过。NOTI03因第1项保持false；其他16项health已启用。

1. **A：提案提示音不能触发自动生效窗口。** `app/fixtures/announcement.py` 的0.8秒双音不包含修改内容；`CHANGE01` 当前把它登记成通知音频。B不能把播放提示音当作“完整播报提案”。因此暂不登记NOTI03（其service/普通回执已实测），避免通过该入口启动窗口。请A/C准备与本次提案内容一致的真实中文语音，并冻结可信的内容/播放完成校验约定；未能播报时保留pending_notice及明确接受/拒绝。B不在写事务调用TTS，也不伪造完成。

   最新又合入A `6774083` 的接口7.1补充，但文档把提示音表述为可完成完整播报，没有改变它仅为双音的代码事实。该文档描述需一并修正。C `1e31bb6` 已提供特定例子的真实语音素材，可供A匹配相应提案使用；它不能作为任意新提案均已播报的证据。
2. **A：设置提案绕过B入口，未来目标未更新。** 真实HTTP回归见 `backend/tests/health/test_shared_settings_gap.py`，明确strict xfail，不算通过：先生成明日运动目标(expected=1) → 子女提案关闭运动 → 老人明确accept返回applied、settings.enabled=false → 明日报表expected仍为1。`ChangeService._apply` settings分支当前直接写JSON；请在同tx调用已冻结 `medication.update_settings(tx, actor, elder_id, base_version, SettingsPatch(...))`，让版本/来源失效/未来任务停用一起完成。不要重复bump版本或复制B的目标逻辑。修复后strict xfail会XPASS失败，由B移除标记并复验。
3. **A：超时应用仍构造老人Actor。** `_principal_for_timeout` 只是对原 `_system_actor` 改名，仍未给B/C提供明确系统授权入口。请统一冻结系统变更/来源失效的授权方式，B继续只调用ChangePort.apply_due(tx,now)。
4. **A：联调脚本药物时刻/选择条件。** 当前 `integration_smoke.round_two` 在12:00HK创建当天08:00新计划；B按“新计划不补造过去义务”不生成这个过期任务，故REC02显示PENDING。请改成未来时刻/餐后任务，并按新建plan_id选择对应task，避免选到其他计划同名slot；NOTI03前还需发送NOTI01 visible心跳。B的默认组装回归已验证未来13:00任务→明确taken→唯一记录→日报completed=1。
5. **A/C：Agent来源标记。** CheckinPort仍没有可信来源参数，C确认动作产生的真实记录source只能是user。请A冻结内部来源传递，C固定传agent_confirmed，B复用该参数保存；不增加客户端可自行宣称来源的字段。

当前B自维护的文件均在原白名单；共享定义未直接编辑。NOTI04已支持本人录音优先、四个与文字一致的真实中文演示WAV、未知文字明确audio_asset_id=null。SAPI只用于离线生成素材；所有音频准备/受控素材读取在写事务外。

---

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

正常 merge 提交 `998ec83`；两个 B 文件的冲突已保留业务实现，并补齐 A2 的 get_plan/mark_proposal_handled/bind。最新代码 `9cfe39b` 本域57项已通过，包含真实 A 建档→B计划/历史导入、已有提案的回执→A窗口/拒绝/重启结算（显式测试 composition）。未注入 Clock 的服务明确501，不自行回退 SystemClock。

10. **公共能力一致性实际失败**：`python -m pytest tests -q --tb=short --basetemp=.pytest_cache/b-integrated` → **1 failed / 153 passed / 42 deselected**。失败是 `tests/framework/test_all_routes.py::test_every_p0_route_matches_its_capability[CHANGE04]`：B 的 mark_proposal_handled 已真实实现，使拒绝返回200；A仍登记CHANGE04=false，公共断言要求501。B没有改该公共测试，也没有把正常钩子改回桩。建议 A 对未验收入口统一能力门禁，或接齐依赖后实测并登记。B 的 perform 已在权限核对后按 capability 与同一 Clock 门禁。

    最新全量复验（`--basetemp=.pytest_cache/b-delivery-final`）为 **1 failed / 165 passed / 42 deselected**；同一项失败，未放宽断言。其余最新验证与未完成项以交接/B.md为准。
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
