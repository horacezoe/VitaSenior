# C 共享适配申请

2026-10-31；C1 基于 f1-reviewed-v1 = 1034c7698de4394b3e7695a3a820df2dcfeaf28b。用户确认 A0 与 C 正在并行开发。C 不修改公共文件，以下交 A 按 A0 统一落地；不要求变更既有 HTTP 字段。

## 1. C 已提供的实际接线点

- `MemoryService(clock: Clock | None = None, access: AccessPort | None = None)`，原有 context/on_source_changed port 签名不变。F1 的 composition 仍以无参构造，因此保留向后兼容；A0 请显式传同一 Clock/AccessPort，尤其 FakeClock 测试不能漏注入。
- `AgentService(clock: Clock, services: ServiceBundle, memory: MemoryService)`，memory 必须是 bundle.memory 同一实例。C 内部的明确偏好写入直接调用同领域 memory.remember，不借用未定义的跨域协议。A0 可按集中 composition 构造后注入应用，不要让 router 偷建服务。
- C1 提供 `replay / read_snapshot / record_turn / decide` 四个服务原语；provider.plan 在 snapshot 的读 UoW 完全退出后、record_turn 的写 UoW 之前运行。没有 HTTP 慢调用接线，也未修改能力清单。

## 2. A0 既定缺口（还没有猜测扩展 port）

需要读取真实 Profile；按 elder/date 查询当日任务，并给出 medication task 对应的原始 slot_id（不能把 DailyTask.slot_key 当作 slot_id 猜测）；通知查询及其与 proposal_id 的真实关联；提案明确决策与普通提醒事件；受控媒体字节读取；生成音频登记并返回 MediaAsset；Clock/Settings 注入及无写锁请求鉴权入口。

CheckinPort 当前 create_or_update 没有来源参数，而 HTTP 契约区分 user/agent_confirmed。请 A/B 统一如何传递“Agent已确认”来源，不通过给冻结DTO偷偷增字段解决。C 的模块测试明确使用 source=agent_confirmed 的 B 替身，不代表真实 B 已支持该标记。Medication 待确认 payload 已保存 task_id、plan_id、slot_id、task_date、task_plan_version，实际执行前需要 B 的真实任务读取校验；不可把 slot_key 当原始 slot_id。

在真实签名发布前，reject_change fixture 只返回明确的引导，语音通知 context 引用报501；不能把 notification_id 当 proposal_id，不能伪造 playback_completed。真实 B ReportPort 当前501会原样导致整笔事务回滚，不被转成成功。

自动规律归纳还需要 B 在同一个 UoW 返回当前有效 Checkin DTO/版本的读取入口。C 的 remember_pattern 目前只接收由 B 在当前事务验证的 DTO 快照，并检查三不同 HK 日期、非取消、非未来、老人/来源/版本匹配；自动 HTTP 路径未接入，不接受客户端或模型随意提供的日期。A0 补齐来源读取契约后再调用，禁止传缓存证据。

## 3. 实测发现的 patch 序列化差异

ProfilePatch/PlanPatch/SettingsPatch 等用“未出现”表示不修改字段，并拒绝某些显式 null；默认 model_dump 会把未传字段输出成 null，随后重新 model_validate 失败。例如 ProfileAction.preview.patch 只有 medical_notes，默认序列化后出现 display_name:null，重放报 only birth_date may be null。

C 已用 exclude_unset=True 保存动作及轮次/结果 JSON，且有 profile_action_roundtrips 回归用例，没有修改公共 schema/快照。C2 HTTP 对含 patch 的响应同样需要保留未传字段；A 可选择在公共序列化层处理，或由 C 路由在必要响应上用 response_model_exclude_unset=True。不要放宽 null 校验，也不要另造兼容 DTO。

## 4. A0 完成后的最短集成步骤

发布 f1-shared-v1 后 C 正常 merge；读取真实新增签名和 capability 约定；把 MemoryService/AgentService/纯 mock provider 接入集中 composition；先接 MEM01–03，随后按“短读鉴权→退出Session→ASR/chat/TTS→短写重新验权/版本/幂等→一次commit”接 AGENT/AI。

C1 不改 tests/framework。原63个 F0 snapshot 用例仍通过；C2 启用接口前仍需 A0 分类占位测试。没有 agent_capabilities.py 是因为任务单明确要求 A0 先建立统一机制。C2 不能把已存在的服务测试成功直接当作 HTTP 能力已可用。
