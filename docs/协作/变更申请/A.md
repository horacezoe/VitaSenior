# A 的变更申请

本文件记录 A 认为需要集成人修改公共定义（schema/model/contracts/快照）的事项。
A 本人即本轮集成人，因此已批准的条目在合并时直接列出实际改动与提交。

## 已由 A0 统一处理（不需要 B/C 另改）

1. `ServiceBundle` 增加 `tasks: TaskPort`、`history: HistoryPort`。
   影响：`composition.compose` 已同步；测试可用 `dataclasses.replace` 注入替身。
   原因：当日任务读取与演示历史导入需要显式 typed port，避免 B 把历史导入塞进 medication 服务。
2. `ChangePort` 由 2 个方法扩为 6 个（`create/query/read/decide/mark_played/apply_due`）。
   影响：仅 A 域实现；B 只调用 `mark_played`，C 只调用 `decide`。
   原因：C 的 `decide_change` 动作与 B 的回执都需要同一状态机入口，不能各自实现。
3. `NotificationPort` 增加 `handle_event(..., now) -> EventResult`，并要求实现方注入 `ChangePort`。
   影响：B 实现；A 的提案不重复实现通知状态机。
4. `MediaPort` 增加 `store_upload/open_content/register_generated`；`open_content` 允许 `actor=None` 配合短票据。
   影响：A 实现；C 不再接触媒体表或文件路径。
5. `routers/agent.py` 的 AI01/AI02/AGENT01/AGENT02 改用无事务的 `Auth` 依赖。
   影响：C 实现时用 `read_unit`/`write_unit` 两段式；对外契约未变。
6. `pyproject.toml` 增加 `f0_stage` marker 与默认 `-m 'not f0_stage'`。
   影响：F0 阶段断言不再阻挡业务开发，但显式 `pytest -m f0_stage` 仍可复现 F0 基线。

## 待确认（暂未改公共定义）

暂无。若 A1/A2 需要新增公开字段（例如 MEDIA03 的票据授权在 OpenAPI 中的可选 security），会在实现时同步快照并在此记录差异。
