# C 当前接手清单：0894154 后的完整播报与可信来源

2026-10-31。A最新 `integration/f1@0894154494f3363435fed9d31b146b22dadbd8c8` 已合入。C本批只改白名单；公共与A/B文件仍交各自负责人。本节覆盖下方历史已解决项。

## 1. A：请把“按类型的句子”接成“实际字段内容”

准确复现：CHANGE01提交 `patch={"medical_notes":"补充社区复查记录"}`，通知录音/文字仍是“孩子帮您更新了档案。请听取本次修改的内容，如果不同意，请明确拒绝。”。`app/fixtures/proposal_notice.py::notice_for(target_type, operation)` 从未接收body.patch，无法播报实际值。它虽不再是音调，也不能证明老人听到这次改动。C的 `test_default_change_http_notification_reads_actual_patch_values` 保留完整内容断言并strict xfail；NOTI03继续关闭。

C新增可直接接入的准确API（位于 `app.providers.proposal_notice`）：

```python
def proposal_text(body: ChangeProposalWrite, *, plan: MedicationPlan | None = None) -> str: ...
def prepare_proposal_notice(
    body: ChangeProposalWrite, *, tts: TTSProvider,
    plan: MedicationPlan | None = None,
) -> tuple[str, SpokenNotice | None]: ...
class ProposalFixtureTTS:  # implements existing C TTSProvider
    def synthesize(self, text: str, voice_id: str | None = None) -> Speech: ...
```

建议最小接线，仍由 A 实施：

1. identity_flows.create_change 的短读UoW验child访问；计划update/deactivate时通过MedicationPort.get_plan读取实际plan，其plan_id/base_version必须相符。关闭读UoW后准备语音。
2. 在全部UoW之外调用 `full_text, notice = prepare_proposal_notice(body, plan=plan, tts=ProposalFixtureTTS())`，或用集中composition注入符合TTSProvider的实例。不要在服务内调用TTS/读WAV。
3. 写UoW按现有流程重新验权/目标/版本/绑定，调用已冻结 `changes.create(..., notice=notice)`。A的ChangeService已有before_snapshot，可用纯 `proposal_text(body, plan=MedicationPlan.model_validate(snapshot) if needed else None)` 生成当前完整文字，无provider/文件IO；notice存在时必须与它完全相同，否则拒绝登记。
4. NotificationEnqueue.text始终保存上述完整文字。notice=None时audio_asset_id=null、proposal.status=pending_notice，不因为文字存在/一般提醒/模拟提示句启动窗口；本人明确accept/reject继续可用。无需为这个接线另加同名DTO或扩展客户端schema。
5. 五个完整例子/语音在 `fixtures/agent/proposal_cases.json` 和 `proposal_manifest.json`，测试验证真实字节、hash、逐字完整文本。只是精确固定mock；任意新备注或不同计划ID没有语音时如实保留文字，不把类别录音当后备音频。A现有 `notice_for` 不应再供提案路径使用。

## 2. B：冻结的 source 已由 C 传递，真实实现必须接收并保存

A的CheckinPort已冻结：

```python
def create_or_update(
    self, tx: Session, actor: Actor, elder_id: str,
    payload: CheckinWrite | CheckinUpdate, checkin_id: str | None = None,
    *, source: Literal["user", "agent_confirmed"] = "user",
) -> Checkin: ...
```

但 `app/services/health_service.py::CheckinService.create_or_update` 仍无该关键字，也没有row.source赋值。C已在所有record_*执行处固定传agent_confirmed，只接受返回同一来源；未接入的旧适配器明确501、动作仍pending，无健康写入/幂等成功缓存；接参却忽略来源则502并原子回滚，不重试user，不改B表。

请B实现上述参数、运行时限定枚举值、在创建与同餐替换/纠正的明确来源策略下真实写 `row.source = source`（修订先保存旧值）。普通HTTP保持默认user，严禁把JSON.source透传；demo_seed沿既有内部历史导入入口，不开放给客户端。C回归已验证客户端自报agent_confirmed被422拒绝、直接HTTP仍source=user；两个真实C确认验收因该缺口strict xfail，不算通过。

## 3. 系统授权已接，继续保持单一入口

A已发布SYSTEM_ACTOR/中央require_elder_access，C沿用同一AccessPort；没有构造老人Actor。context/on_source_changed允许中央授权的系统来源失效；记忆本人编辑/明确偏好和Agent执行拒绝系统主体。真实默认A/B ports测试已观察到超时档案/设置的C失效调用收到共享SYSTEM_ACTOR、applied_by=timeout，无服药副作用。旧“缺系统入口”申请不再作为当前阻塞。

## 4. 闸门与当前影响

C代码/测试/素材已准备。全量、C、契约与架构输出见交接/C.md。本批默认网络烟测在Agent确认真实501处失败，严格三轮32 OK / 4 PENDING / 0 FAIL、退出1；不得用预期失败/port隔离通过替代完整默认部署通过。保持NOTI03=false；A/B修复后去掉三个strict xfail，重新跑C/全量/契约/架构/严格三轮/真实网络验收，再由B开启NOTI03。

---

# C 历史共享适配申请

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


## C2 更新：已合入 A0/A1/A2，用户指定公共文件仍由 A 修改

已正常合入 f1-shared-v1（10d51af）和 backend/platform 72d7610，均无冲突。用户本轮明确选择“公共文件交 A 修改，C 继续自身范围”。因此 C 没有写 composition/main/schema/OpenAPI；新增C路由默认使用 _ready 检查，未接线时返回501且capability=false，不会因缺少 app.state.agent 而500。

C2 已完成7个HTTP入口和明确DI集成测试，使用真实 A 的登录、档案、绑定码、媒体读写及提案读/决策；B未完成的端口依旧501并回滚。具体公共接线候选如下。

### A 请在同一集成提交中完成装配、schema与能力启用

composition.py（唯一具体实现构造点）：

```python
from app.services.agent_service import AgentService
from app.providers.mock_chat import MockUnderstanding
from app.providers.mock_audio import MockASR, MockTTS

# compose() 里替换原 memory = MemoryService() 和 access=AccessService()：
access = AccessService()
memory = MemoryService(clock, access)
# ServiceBundle(access=access, memory=memory, ...)

def compose_agent(clock, services):
    return AgentService(clock, services, services.memory)

def compose_agent_providers():
    return MockUnderstanding(), MockASR(), MockTTS()
```

main.py：从composition导入以上两个工厂，在app.state.services创建后接线：

```python
app.state.agent = compose_agent(clock, app.state.services)
app.state.agent_chat, app.state.agent_asr, app.state.agent_tts = compose_agent_providers()
```

schemas/system.py：`Runtime.providers` 当前是 `dict[str, Literal["not_implemented"]]`；改为 `dict[str, Literal["not_implemented", "mock"]]`，然后实际运行 export_contract 导出并审核仅此枚举差异。

C-owned agent_capabilities.py 已提供 `C2_OPERATIONS`，但当前 `CAPABILITIES` 保持空、`PROVIDERS` 保持not_implemented，与默认未接线状态一致。完成上述修正时，C授权集成人在同一提交启用 `CAPABILITIES=C2_OPERATIONS` 与 `PROVIDERS={"chat":"mock","asr":"mock","tts":"mock"}`，并跑完整回归。不要只改能力不接线，也不要只接线不修Runtime枚举；否则分别造成假能力、500或能力声明与响应不一致。

### 额外发现的真实跨域契约差异

A ChangeService.create 当前使用 `notification.id`，但冻结 NotificationPort.enqueue 声明返回公开 Notification，其主键字段为 `notification_id`。A的既有测试替身返回SimpleNamespace(id=...)会掩盖这一差异；真实B返回DTO后可能500。请A/B统一，不让C补兼容DTO或改A实现。本轮C的提案测试从明确的已存在提案fixture开始，调用真实A query/read/decide；只替换B的关闭通知hook，不把这视作CHANGE01跨三域创建已通过。

B还需落地TaskPort.today/MedicationPort.get_plan、通知handle_event与Checkin来源标记。C的用药快照从真实计划slots匹配原始slot_id，不直接拆slot_key；当前计划版本与任务版本不同返回409，无法核对时不选择药品。自动规律证据读取仍等B既有申请完成，不从模型猜证据。

### C2 事务与JSON约定

C2使用A0 Auth、read_unit/write_unit。ASR/chat/TTS及媒体字节读取均在Session外；写前重新验证实际会话、老人访问、关联通知、档案/记忆版本。所有成功结果与业务/动作/记忆在同一写UoW保存幂等结果，失败不缓存。Agent响应和动作JSON保留exclude_unset=True，避免patch默认null破坏回放。

固定语音只覆盖真实对应文本，含新增“您好”；其他新文本TTS明确501，Agent可保留文字并标tts_unavailable。没有无内容音频、假播放回执或伪造服药。尚不能把固定mock的可用性宣称为任意文本真实TTS。


## 最新集成更新：integration/f1 = 21f9bff（本段覆盖前述已解决项）

C 已正常合入 A 的 integration/f1，合并提交38bc09c。A已修复Notification主键DTO差异；B的CheckinService.today/import_demo_history、MedicationService.get_plan、真实打卡/日报/通知原语已存在。本轮测试实际通过C确认→B真实落一条记录→重复确认仍一条→真实B日报读取同一checkin_id，不再把已实现B当占位；缺失port测试改为显式测试替身。

当前公共composition仍将tasks/history接A0占位类，MemoryService仍无参，main仍无C装配，Runtime.providers仍只有not_implemented。按用户要求C没有修改这些文件。请A只改现有memory那一行为MemoryService(clock,access)，复用integration/f1已建立的access/media/B实例，再按前述步骤接C。

新的真实全量失败只有 `tests/framework/test_all_routes.py::test_every_p0_route_matches_its_capability[CHANGE04]`：真实C来源失效接入后accept已经200，但identity_capabilities仍未声明CHANGE04，期望501。最新命令结果 `1 failed, 220 passed, 42 deselected`。C保留该测试及cap清单原样，请A确认完整接受路径后登记，或按实际未完成依赖门禁；不能让C伪造501/吞成功来过测试。

C自己的63项全部通过。真实B目前对C确认写入仍标source=user；C未直接改B表冒充agent_confirmed，来源参数的冻结请求仍有效。C HTTP测试中明确断言当前观察到的值，并将来源差异列为未完成的集成事项，不宣称来源验收已通过。

最新正常部署smoke为 `20 ok / 9 pending / 0 failed`；C的AGENT/MEM仍如实PENDING，CHANGE01已因A/B修复变OK。OpenAPI与架构检查通过，hash仍6a2de0894ef6de2094799d9e3c1d4cef884d317cc62c336c98f535dd1527720d。


## 最新复验：已合入 A 的 51dc555，接线和 CHANGE04 闸门已解决

用户指定公共文件由 A 修改。本轮 C 只正常合入 `integration/f1=51dc55517452c094bb169862d1e696f3c683c1fa`，没有自行改 composition/main/core/models/schemas/contracts/OpenAPI/公共测试。默认create_app已共享Clock/Memory并接Agent与三个mock provider；七项C能力为true，runtime正常返回mock；CHANGE04已登记，原200/501闸门失败消失。

C把测试环境改成默认create_app，不再手动装配Agent或替换Memory。跨日用药联调暴露了C自己的真实失败：TaskPort.today会物化目标，C原只读UoW结束会回滚，返回的task_id没有落库。已复现并在C修复：仅需要任务时使用一个独立短写UoW提交目标ID，随后完全释放Session才调用ASR/chat/TTS；音频先识别成功再准备其对应任务，确认前没有Checkin。模型返回后及确认时通过真实ports复核计划/任务版本，版本变化409且不写打卡。来源事实、动作最终状态和幂等成功结果仍由最后一个写UoW原子提交。

新增实际C验收：默认装配Clock/对象身份、跨日任务ID持久性、模型期间/确认前计划变化、真实B取消后C规律失效、新会话上下文变化；使用完整修改内容的真实中文语音，经真实A/B ports测未播报不启动、完整播报后60秒、窗口内C拒绝、到期应用；真实默认Uvicorn网络HTTP一轮也通过。全量237 passed / 42 deselected；C 71 passed；契约和架构通过。正常三轮smoke为24 OK / 7 PENDING / 0 FAIL，尚未零PENDING。

### 仍交给 A/B 的具体业务缺口

1. **A当前提案HTTP仍是提示音，不是完整内容播报。** `app/fixtures/announcement.py::render_announcement(text)` 忽略text，用660/880Hz两个音调生成0.8秒WAV；`identity_flows.create_change`固定调用它。该字节能通过B的MIME/非空检查并启动倒计时，但未逐字播报body.patch，不能据此宣称完整通知内容已被听取。C没有修改A文件。C已提供五号真实语音fixture（proposal_change_example.wav）并通过真实A/B端口验证窗口规则；该测试不等于现有CHANGE01 HTTP已经换成内容语音。请A在事务外按实际修改构建内容，用C TTS的完整匹配语音或真实内容录音；无匹配语音时不要用音调/不匹配录音启动窗口，保留pending_notice和显式接受/拒绝路径。C的有限固定mock不承诺任意新文本TTS。
2. **Agent确认来源标记仍待冻结。** CheckinPort.create_or_update没有source参数，真实B默认source=user。C保留实际值并由action.result追溯，不直接改B表伪装agent_confirmed。请A/B统一来源参数或经审核的调用上下文约定。
3. B仍有7个三轮smoke步骤PENDING：DASH01、PLAN02、TASK01、REC02、NOTI02、REC01、REPORT01。C不修改B的能力文件或路由。其他未发布的自动归纳、手机/真实模型/真实播放器验收按各自任务继续。

以上不阻止C的mock API/事务与工具链验收通过，但整体P0与现有HTTP提案完整播报不能标已全部完成。
