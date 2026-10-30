# C 交接：小安、mock 与长期记忆

日期：2026-10-31（Asia/Shanghai）。状态：**C1_READY；C2_WAITING_A0**。用户已确认 A0 尚未完成，A/C 正在同时开发。本记录不宣称 C2 HTTP、音频登记或跨领域真实业务闭环已经完成。

共同起点：`f1-reviewed-v1` = `1034c7698de4394b3e7695a3a820df2dcfeaf28b`。

分支：`backend/agent`。已验证代码提交：`be35f0706f652ba9301205d14cbbbad3d7d5d7d5`。本记录单独提交，不为回填自身 commit 反复修改。

## 实际完成

- MemoryService：真实访问校验、按来源的条目保存、跨会话读取、版本冲突、用户修正/删除、修订与抑制信息、来源失效、稳定 Markdown；DB 是唯一事实来源，无 memory.md 双写。
- 规律只接受同一事务中由 B 验证的 Checkin DTO 快照，检查至少三个不同 HK 日期、老人/来源/版本一致、非取消/非未来；一次饮食或运动不会自动形成规律。自动读取证据与自动归纳 HTTP 尚未接入，不能传入模型猜测或缓存证据。
- 纯 MockUnderstanding：11 个任务要求场景，未知照片/文本 clarify，明确标“模拟”；完整发生时刻/目标/版本/服药 task_id、plan_id、原始 slot_id 等保存在 payload_json，preview 只展示。
- AgentService C1 原语：轮次去重/异体冲突、待确认持久化、明确确认/取消、10 分钟过期、单次执行及结果重放、类型一致的 amendments、实际权限与资源拒绝、模型阶段后重新检查内存版本。
- 使用当前既有 port 的工具原语已通过明确替身测试：CheckinPort、ProfilePort、BindingPort、ReportPort。尚未实现的真实 port 错误会原样传播并整笔回滚，不转成假成功。不直接写 A/B 生产表。
- 模型不在写事务内执行；测试验证独立写连接可在 provider 阶段提交。失败回滚轮次、动作、记忆/业务写入，失败动作不会标 confirmed。
- 真实固定中文语音：三个 PCM WAV，Windows SAPI Microsoft Huihui Desktop 离线生成并附脚本/哈希。MockASR 只识别摘要匹配的已知录音，校验真实 WAV 编码；MockTTS 只提供完整文字一致的语音，其他文本明确501。
- 新会话能回答已保存偏好；修正/删除后新会话使用更新后上下文，不从旧对话恢复条目。记忆不写档案或用药表。

## 文件和写入边界

实际代码只写任务单白名单：

- `backend/app/services/memory_service.py`
- `backend/app/services/agent_service.py`（新增）
- `backend/app/providers/planning.py`、`mock_chat.py`、`mock_audio.py`
- `backend/fixtures/agent/README.md`、`scenarios.json`、`audio_manifest.json`、`generate_audio.ps1` 和三个 WAV
- `backend/tests/agent/conftest.py`、`test_memory.py`、`test_planning.py`、`test_agent_service.py`、`test_audio.py`
- `docs/协作/变更申请/C.md`、本记录

公共 core/models/schemas/contracts/composition/main/依赖锁/OpenAPI/框架测试均未改；没有启用 C HTTP 能力、修改 runtime 或新建临时跨域协议。private planning 值放在 providers，只复用共享公开 DTO/ActionType/SourceRef。

## 给 A 的准确接线点

`app.services.memory_service.MemoryService(clock: Clock | None = None, access: AccessPort | None = None)`：保持原无参 F1 composition 可启动。A0 应明确传入应用同一个 Clock 和 AccessPort；测试必须传 FakeClock，不能依赖默认 SystemClock。

既有 MemoryPort：

```python
context(tx: Session, actor: Actor, elder_id: str) -> MemoryDocument
on_source_changed(tx: Session, actor: Actor, elder_id: str, source_ref: SourceRef) -> None
```

同领域应用方法，不是擅自新增的共享 port：

```python
remember(tx: Session, actor: Actor, elder_id: str, entry: MemoryEntry) -> MemoryDocument
remember_pattern(tx: Session, actor: Actor, elder_id: str, entry: MemoryEntry,
                 records: Sequence[Checkin]) -> MemoryDocument
update_entry(tx: Session, actor: Actor, elder_id: str, entry_id: str,
             expected_version: int, text: str) -> MemoryDocument
delete_entry(tx: Session, actor: Actor, elder_id: str, entry_id: str,
             expected_version: int) -> MemoryDocument
```

所有方法仅使用传入 tx，调用方一次 commit；不会自行新开连接、commit/rollback、调用模型或导出文件。context 对不存在的文档返回空逻辑版本1，不在 GET 事务里创建数据；首次真实记忆写入升为版本2。remember 验证 agent_turn 归属，失效匹配 type/id，不会因旧引用 version1 与新变更 version2 不同而漏掉失效。

`app.services.agent_service.AgentService(clock: Clock, services: ServiceBundle, memory: MemoryService)`：memory 必须与 services.memory 是同一实例，在统一 composition 构造。入口：

```python
replay(tx, actor, request: AgentTurnWrite) -> AgentTurn | None
read_snapshot(tx, actor, request: AgentTurnWrite, *, profile: Profile | None = None,
              tasks: Sequence[DailyTask] = (), medication_slots: Mapping[str, str] | None = None) -> Snapshot
record_turn(tx, actor, request: AgentTurnWrite, snapshot: Snapshot, plan: Plan) -> AgentTurn
decide(tx, actor, action_id: str, decision: ActionDecision) -> ActionResult
```

profile/tasks/medication_slots 必须由真实 A/B port 在同一读 UoW 内读取，不能从客户端或模型直接传。medication_slots 为 task_id 到原始 slot_id 的准确映射。后续正常执行需要复核真实任务/版本，缺失时不猜药品与用量。

调用顺序：短读 UoW 验权并先检查 replay → read_snapshot → 完全释放 Session → provider.plan(request, snapshot) → 新短写 UoW → record_turn 再验权/去重/版本 → 一次 commit。确认已有动作只在短写 UoW 调 decide，不等待模型。应用入口与 HTTP Idempotency-Key 仍由 C2/A0 基础设施协调；当前测试已覆盖 client_turn_id 和 action_id 的自身重放，不冒充已经接好 HTTP 幂等头。

`app.providers.mock_audio.MockASR.transcribe(audio: bytes, mime_type: str, fixture_id: str | None = None) -> ASRResult`；`MockTTS.synthesize(text: str, voice_id: str | None = None) -> Speech`。Speech 为同领域字节结果，必须交给 A0 MediaPort 登记后才能构建公开 TTSResult，不能猜 URL。语音文件不作为任意新提案已播报的证据。

## mock 示例与实际限制

`fixtures/agent/scenarios.json` 保存以下场景及输入/预期 scene/action：

- meal_lunch / “这是我的演示午餐”：pending record_diet，不创建健康记录。
- ingredient_advice：模拟食材建议，不直接打卡。
- exercise_walk / “我散步了20分钟”：pending record_exercise；确认后才通过 B port。
- medication_ambiguous：追问；medication_confirm：仅有唯一到期、明确计划及原始时段时生成 pending，否则追问。
- binding_code：通过 A BindingPort；daily_query：通过 B ReportPort，回复使用实际返回 summary_text；port未实现时整笔501。
- profile_update：需要真实档案版本后生成 pending update_profile。
- explicit_preference：保存带 agent_turn 来源的明确偏好。
- reject_change：当前只引导使用真实提案拒绝入口；缺少关联/决策 port，不伪造已拒绝。
- provider_timeout：确定性504，不留下轮次、动作或健康写入。

不指定 fixture 时只识别有限、明确文本（散步分钟数、明确偏好、指定/唯一待确认动作、读取已有偏好等）；其他内容引导澄清，不宣称实现了真实语义模型。模糊服药对应多个任务永远追问。context.notification_id 目前因缺读取关联 port 返回501，不把其当 proposal_id。

## 实际验收

环境沿用 backend/.venv，Python 3.13.9 / Windows / requirements.lock，无新依赖、无供应商密钥；测试全部用 tmp_path SQLite 和同一个 FakeClock。

工作目录 backend，已实际运行：

```text
python -m pytest tests/framework tests/agent -q
108 passed, 1 warning in 19.21s

python -m app.tools.export_contract --check
OpenAPI matches 73f9920606bdd8c6338c67327e72adef1ea1a474352aa4c22c949e071ad75657

python -m app.tools.check_architecture
Architecture OK: no cross-domain implementation imports
```

108 = 原框架63 + C业务45。警告为原有 Starlette TestClient/httpx 弃用提示，未屏蔽。已验证白名单无越界和 git diff --check。测试替身只在 tests/agent，不会在正常运行中伪装 A/B 已成功。

明确未运行：C2 HTTP/AI01–02/AGENT01–02/MEM01–03业务集成、A/B真实工具闭环、手机播放/HTTPS、真实模型/ASR/TTS、提案60秒联调。框架 snapshot 中这些接口仍501/capability=false，原框架63项能继续通过，不代表 C HTTP 已上线。

## 依赖与下一步

提交前重新 fetch，远端只有 codex/f1-handoff 等原分支，没有 f1-shared-v1；用户也确认 A0 并行开发中。C2 依照任务单暂不越权自行补公共依赖。具体缺口与 patch 序列化实测问题见 `docs/协作/变更申请/C.md`。

A0 发布后：正常 merge f1-shared-v1 → 读取真实扩展 ports/Clock/无写锁鉴权及 capability 约定 → 统一 composition 接线 → C 实现 MEM/AGENT/AI HTTP → 用 A/B 真服务做完整集成测试 → 仅将实际通过的能力标 true。尤其需要明确 Agent 打卡来源、原始用药 slot_id、Checkin 当前证据读取、媒体字节/生成音频登记和通知到提案的关联。

本批可以交给 A 合入 MemoryPort 与 C1 独立代码；尚不能把 C2 标为完成，也不能将模块替身测试视作真实用药/绑定/日报业务验收。
