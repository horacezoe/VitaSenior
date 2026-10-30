# B 公共适配申请

基线：`f1-reviewed-v1` → `1034c7698de4394b3e7695a3a820df2dcfeaf28b`。2026-10-31。

1. **未来任务停用**：DailyTask 没有 active/cancelled 状态。删除未来 slot、停用计划或缩短日期范围时，已有任务可能已有通知/FK；不能删除历史，也不能在 plan_snapshot 偷放状态。请 A 定义持久化停用字段及 DTO/统计约定。适配前 B 对需要撤销已生成任务的修改明确返回 501，事务回滚，不伪造成功。
2. **每日快照完成标记**：只靠 daily_tasks 无法区分“当天已生成且某类别不适用”和“尚未生成”。旧日期不能用新计划或新设置反推历史分母。请 A 冻结每日目标生成批次/日期标记方案。适配前 B 只物化今天及未来；历史仅使用已保存任务，不按现行计划补写。没有保存过的历史目标无法恢复，日报不推断漏服。
3. **完整播放证明**：NotificationEvent 仅 event_id/event_type/snooze_minutes，没有 client_id、播放成功/已播放次数。无法校验 repeat_count=2/3 的完整播放或缺失音频。请 A 冻结完整播放计数、可播放素材及无音频降级约定；适配前禁止无音频的 playback_completed，多次播放不能只凭一个事件猜测已完成。
4. **组装与 ports**：请 A0 冻结任务读取、计划/设置/取消/列表/汇总等 HTTP 所需入口及 Notification 事件/系统扫描入口。ServiceBundle 尚只有窄写 port，routers/flows 不可导入实现。构造器需注入同一 Clock、AccessPort、MemoryPort/MediaPort/ChangePort；扫描入口用系统方法，不伪造 Actor。ChangeService 应在授权提案应用时调用 B 的受控变更入口，不能放松普通 child apply_change。

截至首次 fetch，远端没有 `f1-shared-v1`。B 不修改共享定义，先提交服务与替身测试；适配发布后正常 merge 并按实际签名接线。
