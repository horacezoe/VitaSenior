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
