# Agent A 交接记录

角色：业务 Agent A（平台、家庭档案与媒体）+ 本轮集成人。

## 1. 基线与分支

| 项目 | 值 |
| --- | --- |
| 共同标签 | `f1-reviewed-v1` |
| 标签解引用 commit | `1034c76`（Publish reviewed F1 task sheets and agent handoff prompts） |
| 本轮已验证代码 commit | `497fc4ce6ede5ee951c57cd06913197391633f56`（标签的父提交；标签只多出文档） |
| 分支 | `backend/platform`（从 `f1-reviewed-v1` 创建；未 reset、未覆盖任何远端分支） |
| 远端 | `origin` = `https://github.com/horacezoe/VitaSenior.git` |
| 复验环境 | Windows / Python 3.12.4 / `backend/.venv` / `requirements.lock` |

**远端推送未执行**：本机没有 GitHub 凭据，SSH 22 端口被阻断，`git push` 会停在凭据提示。
提交与标签都已在本地 `backend/platform` 就绪（见第 2 节）；有凭据的人执行
`git push origin backend/platform` 与 `git push origin f1-shared-v1` 即可，内容无需改动。

### OpenAPI

| 阶段 | SHA-256 |
| --- | --- |
| F0 基线（A0 结束时未变） | `73f9920606bdd8c6338c67327e72adef1ea1a474352aa4c22c949e071ad75657` |
| A1/A2 结束（当前） | `4b7ade26f590902a4eb131920589184b95e0b54a293e9df80ac9f8aa4859532c` |

唯一的契约差异是 MEDIA03 的 security 从 `[{HTTPBearer}]` 变为 `[{HTTPBearer}, {}]`：
任务单要求“有效 ticket 单独授权，仍保留 Bearer”，而 `<audio src>` 无法附加 Authorization 头，
契约若仍写“必须 Bearer”前端会误判。其余 44 个 operation 的路径、字段、状态码、错误响应逐字节未变。
A2 的状态机、新增 port、`change_proposals.created_at` 均为内部或存储层变化，未改公开契约。

## 2. 提交清单

| 阶段 | 提交 | 标签 |
| --- | --- | --- |
| A0 共享适配 | `10d51af` | `f1-shared-v1`（一次性，不移动） |
| A1 家庭档案与媒体 | `ec80d4c` | — |
| A2 代维护提案 | `f7e750a` | — |
| 联调脚本与合并验证 | 见 `backend/platform` HEAD（本文件所在提交） | — |

B/C 合入方式：`git fetch origin --tags && git merge f1-shared-v1`（或 rebase 到该标签），
保留自己的提交，不 reset、不覆盖别人的工作。

## 3. A0 共享适配（回顾）

1. **F0 断言与长期测试分开。** `tests/framework/test_stage_f0.py` 保留 F0 严格断言，标记
   `f0_stage`，默认不运行；`pytest -m f0_stage` 显式运行，业务能力登记后自动 `skip`
   （当前 42 skipped）。长期契约改为双向：登记为 true 的路由不得返回 501；未登记的路由必须
   恰好 `501 MODULE_NOT_IMPLEMENTED`。
2. **能力按领域声明。** 见第 6 节；`/runtime` 只渲染，不再内联清单。
3. **AI 流程鉴权上下文。** `Auth` 依赖短读鉴权后释放事务，供应商调用期间不持有
   `BEGIN IMMEDIATE`；写操作另开 `write_unit()` 并在事务内重新验权。
4. **统一时钟/配置注入。** `compose(clock, settings, limiter)` 是唯一组装入口。
5. **内部 port 补齐并冻结签名。** 见第 5 节。
6. **历史导入统一入口。** `app/seed.py::import_demo_history` + `app/fixtures/history.py`。

## 4. 已实现的业务接口

### 4.1 A1：家庭档案、绑定与媒体

| 编号 | 实际行为 |
| --- | --- |
| DEMO01 | 每次生成独立老人/子女账号（11 位、全局唯一、`demo_*` 分组）与未确认老人草稿；**不建亲属关系**；同幂等 key 重放原家庭；公开入口按 IP 限流 10 次/60 秒（进程内，演示规模）。新手机号可直接走 AUTH01/AUTH02。 |
| ONB01 | 命中 `community_sample_001` → `matched` + 可选草稿计划；否则 `not_found` + 空草稿。只写 `elder_profiles.onboarding_draft`，正式档案 version/字段不变。 |
| ONB02 | 校验 `draft_id` 属于本老人、`expected_version` 一致后升为 `confirmed`、version+1、`source=user_confirmed`、清空草稿；同一事务调用 B 的 `MedicationPort.import_draft` 落库计划，匹配的演示档案再调 `import_demo_history`。任一步失败整笔回滚。 |
| PROF01 | 本人与有效绑定子女可读；未绑定/他人 → 403。 |
| PROF02 | 仅本人；`expected_version` 不符 → 409 `VERSION_CONFLICT` 且回 `current_version`；子女 → 403 `PROPOSAL_REQUIRED`；仅 `birth_date` 可置空。 |
| BIND01 | 四位码（保留前导零），5 分钟有效；重发同事务撤销旧码；全局活动码唯一。 |
| BIND02 | 只预览不消费；未知/失效 → `BIND_CODE_INVALID`，过期 → `BIND_CODE_EXPIRED`，已用 → `BIND_CODE_CONSUMED`；返回脱敏手机号与 `already_bound`；按子女限流。 |
| BIND03 | 同一事务消费 + 建绑定；并发由 `BEGIN IMMEDIATE` 与部分唯一索引兜底；已绑定再消费 → 409（同幂等 key 才重放）。 |
| BIND04 | 子女的活动绑定列表（含年龄、关系、binding_id）。 |
| MEDIA01 | 真实落盘 `DATA_DIR/media/`；图片 ≤10 MiB（JPEG/PNG/WebP），音频 ≤15 MiB（WAV/MP3/WebM/MP4）；超限 413、类型不符 415；关联 elder 时校验关系；返回 5 分钟票据地址；同 key 同内容重放同一 asset。 |
| MEDIA02 | 校验归属/绑定后重新签发票据地址。 |
| MEDIA03 | **Bearer 或 ticket 二者其一**即可取字节，`Content-Type` 按素材设置、不包 JSON；票据过期/篡改 → 404，无凭据 → 401，未绑定子女 → 404。 |

### 4.2 A2：子女代维护提案（状态机已完成）

| 编号 | 状态 | 说明 |
| --- | --- | --- |
| CHANGE01 | 代码完成，能力仍 false | 仅写提案 + 通知，目标不变；`before_snapshot` 取当前 Profile/ReminderSettings/MedicationPlan；通知 `source_key=f"proposal:{id}"` 去重。提交需 B 的 `NotificationPort.enqueue`，未实现时返回 501 并整笔回滚。 |
| CHANGE02 / CHANGE03 | 已登记 true | 本人与绑定子女可分页查询（`status` 过滤、base64url cursor）与读取详情。 |
| CHANGE04 | 代码完成，能力仍 false | 明确接受/拒绝唯一终态；到期先按服务端时间结算，客户端无法用过去时间撤回；应用时复核目标版本与绑定是否仍有效；冲突记 `conflicted` + `conflict_reason`。终态要关闭关联通知，需 B 的 `mark_proposal_handled`。 |

关键规则实现：

- **窗口只在完整播报后开启**：`ChangeService.mark_played` 是唯一入口，只接受 `pending_notice`，
  写入 `notified_at` 与 `auto_apply_at=now+60s`；重复回执直接返回当前状态、**不重设截止时间**。
  未播报时 `auto_apply_at` 恒为 null（有测试推进 1 小时验证零应用）。
- **到期结算**：`apply_due` 由 `main.py` 注入 `Scanner.tick_hook`（每 5 秒），从 SQLite 读取
  `awaiting_decision` 且 `auto_apply_at <= now` 的提案，按 `applied_by="timeout"` 应用；
  截止时间持久化，重启不依赖任何进程内计时器（有"重启后续跑"测试）。结算失败只记日志、
  不标 applied，下一 tick 重试。
- **竞争唯一终态**：单写事务 + `BEGIN IMMEDIATE`；`decide` 先结算到期再判状态，已 applied 的
  一律 409 `CHANGE_ALREADY_APPLIED`。拒绝/接受到期同刻只有一个终态提交。
- **跨域同事务**：Profile/Settings 应用调 C `MemoryPort.on_source_changed`（`SourceRef(profile)`）；
  用药计划应用先用 B `MedicationPort.get_plan` 复核版本，再调 `apply_change`。任一 port 501 会
  整笔回滚，绝不把提案标成 applied。
- **绑定撤销后不静默写入**：应用前复核 `FamilyBinding.status='active'`，否则记 `conflicted`
  且 `conflict_reason="binding_revoked"`。

## 5. 冻结的内部 port 签名

一律 `from app.contracts.ports import ...`；`tx` 是调用方持有的 `Session`，`actor` 来自
`app.contracts.context.Actor`。任何方法都不得 commit/rollback/新建 Session/调用外部供应商。

```python
class BindingPort(Protocol):
    def issue_code(self, tx, actor, elder_id: str) -> BindingCode: ...
    def preview(self, tx, actor, code: str) -> BindingPreview: ...
    def consume(self, tx, actor, code: str, relationship: str) -> BindingResult: ...
    def list_elders(self, tx, actor) -> ElderList: ...

class ProfilePort(Protocol):
    def read(self, tx, actor, elder_id: str) -> Profile: ...
    def update(self, tx, actor, elder_id: str, expected_version: int, patch: ProfilePatch) -> Profile: ...

class ChangePort(Protocol):
    def create(self, tx, actor, elder_id: str, body: ChangeProposalWrite, now: datetime) -> ChangeProposal: ...
    def query(self, tx, actor, elder_id: str, status, limit: int, cursor: str | None) -> Page[ChangeProposal]: ...
    def read(self, tx, actor, proposal_id: str) -> ChangeProposal: ...
    def decide(self, tx, actor, proposal_id: str, decision: ChangeDecision, now: datetime) -> ChangeProposal: ...
    def mark_played(self, tx, actor, proposal_id: str, now: datetime) -> ChangeProposal: ...
    def apply_due(self, tx, now: datetime) -> list[ChangeProposal]: ...

class NotificationPort(Protocol):
    def enqueue(self, tx, actor, source_key: str, payload: NotificationEnqueue) -> Notification: ...
    def handle_event(self, tx, actor, notice_id: str, event: NotificationEvent, now: datetime) -> EventResult: ...
    def mark_proposal_handled(self, tx, notification_id: str) -> None: ...

class TaskPort(Protocol):
    def today(self, tx, actor, elder_id: str, day: date) -> TaskList: ...

class MedicationPort(Protocol):
    def get_plan(self, tx, actor, plan_id: str) -> MedicationPlan: ...
    def import_draft(self, tx, actor, elder_id: str, plans: list[MedicationPlanWrite]) -> list[MedicationPlan]: ...
    def apply_change(self, tx, actor, elder_id, operation, target_id, patch, expected_version) -> MedicationPlan: ...

class MediaPort(Protocol):
    def get_asset(self, tx, actor, asset_id: str) -> MediaAsset: ...
    def store_upload(self, tx, actor, *, elder_id, purpose, filename, content_type, content: bytes) -> MediaAsset: ...
    def open_content(self, tx, actor: Actor | None, asset_id: str, *, ticket: str | None = None) -> MediaContent: ...
    def register_generated(self, tx, actor, elder_id: str, *, content: bytes, mime_type, purpose, duration_ms) -> MediaAsset: ...

class HistoryPort(Protocol):
    def import_demo_history(self, tx, actor, elder_id: str, *, demo_id: str, days: int) -> None: ...
```

约定补充：

- `NotificationPort.handle_event` 承担完整回执语义（displayed 需有效可见心跳、answered 需已
  displayed、playback_completed 需完整播放次数），并在**同一事务**里调用
  `ChangePort.mark_played` 启动窗口；B 不要重写提案状态机。
- `NotificationPort.mark_proposal_handled` 是 A2 用来关闭关联通知的小钩子（A 不直接写 B 的表）。
- `ChangePort.decide` 是提案唯一接受/拒绝入口（C 的 `decide_change` 动作调用它）。
- `MedicationPort.get_plan` 供 A 取 `before_snapshot` 与复核版本，A 不读 B 的表。
- `MediaPort.open_content(actor=None, ticket=...)` 支持仅票据播放；`register_generated` 供 TTS
  生成音频登记（C 不得直接写媒体表或猜路径）。
- `HistoryPort` 由 B 实现，行模板在 `app/fixtures/history.py`，按 `demo_id` 去重。

## 6. 能力声明写在哪

| 文件 | 归属 | 当前值 |
| --- | --- | --- |
| `app/services/identity_capabilities.py` | A | 5 个基础 + DEMO01、ONB01/02、PROF01/02、BIND01–04、MEDIA01–03、CHANGE02/03（19 项） |
| `app/services/health_capabilities.py` | B | 空 |
| `app/services/agent_capabilities.py` | C（含 `PROVIDERS`） | 空 / `not_implemented`×3 |

CHANGE01/CHANGE04 **故意未登记**：它们的真实路径依赖 B 的 `enqueue` / `mark_proposal_handled`
与 C 的 `on_source_changed`，现在登记会让 `/runtime` 声称可用而实际返回 501。等 B/C 端口落地、
端到端跑通后再由 A 追加这两位，并用 `tests/identity/test_changes.py` 的同样断言复验。

## 7. AI 事务入口（C 必读）

```python
from app.routers.dependencies import Auth, check_access, read_unit, write_unit

@router.post("/agent/turns", ...)
def agent01(auth: Auth, body: AgentTurnWrite, idempotency_key: str = Header(...)):
    with read_unit(auth.request) as uow:                     # 短读：鉴权+取上下文
        check_access(auth.request, uow.session, auth.actor, body.elder_id, "self")
        facts = ...                                          # 只读所需数据
    result = provider_call(...)                              # 无事务，慢调用
    with write_unit(auth.request) as uow:                    # 短写：重验权+幂等
        check_access(auth.request, uow.session, auth.actor, body.elder_id, "self")
        ...                                                  # 业务写入
        uow.commit()
```

- `Auth` 只保证“已登录”，不提供 `tx`，避免把供应商调用夹进 `BEGIN IMMEDIATE`。
- 写事务里必须重新 `check_access`/`check_resource`，不能复用读阶段结论。
- 服务里的时钟就是 `app.state.clock`（测试注入的 `FakeClock`）。
- 生成音频用 `services.media.register_generated(...)`；引用他人音频用 `MediaPort.get_asset`；
  提案接受/拒绝用 `services.changes.decide(...)`。

## 8. 构造器、组装与存储变更

- 唯一组装函数 `app.composition.compose(clock=None, settings=None, limiter=None)`；
  `create_app` 传入 `app.state.clock`/`app.state.settings`/`app.state.ratelimit`。
- 需要时间的服务按 `__init__(self, clock)` 或 `__init__(self, clock, settings)` 接收注入对象；
  `BindingService` 额外接收可选 limiter。
- A↔B 通知/提案互相引用，用 `ChangeService.bind(medication, notifications, memory)` 与
  `NotificationService(clock, changes=...)` 在 composition 里晚绑定断环；业务代码不得
  `import app.composition`（`check_architecture` 会拒绝）。
- `ServiceBundle` 是 frozen dataclass，测试可用 `dataclasses.replace` 注入替身。
- **存储层**：`change_proposals` 新增 `created_at`（分页需要稳定排序）。`create_all` 不会给已有
  数据库补列，**旧的运行库需要重建或手工 ALTER**；测试与演示库都是新建，不受影响。

## 9. DEMO01 历史导入统一入口

```python
from app.seed import import_demo_history
import_demo_history(tx, services, actor, elder_id, demo_id=demo_id, scenario="diabetes_daily")
```

- 仅 B 的 `HistoryPort` 写 `daily_tasks`/`checkins`（`source="demo_seed"`）并联动 C 记忆素材；
  A 只调度。无匹配手工建档不调用，不凭空生成历史。
- 行模板 `app/fixtures/history.py`：14 天、确定性、无真实用药建议；非法场景直接 `ValueError`。

## 10. 实际执行的验证

在 `backend/`、`backend/.venv`、Python 3.12.4 下：

| 命令 | 结果 |
| --- | --- |
| `python -m pytest tests -q` | `109 passed, 42 deselected, 1 warning` |
| `python -m pytest tests/identity -q` | `39 passed` |
| `python -m pytest tests/framework -q` | `70 passed, 42 deselected` |
| `python -m pytest tests -m f0_stage -q` | `42 skipped`（阶段已关闭，符合设计） |
| `python -m app.tools.export_contract --check` | `OpenAPI matches 4b7ade26f590902a4eb131920589184b95e0b54a293e9df80ac9f8aa4859532c` |
| `python -m app.tools.check_architecture` | `Architecture OK` |
| `python -m pip check` | `No broken requirements found.` |
| 真实 uvicorn 冒烟（临时 DATA_DIR、`SCANNER_ENABLED=true`、127.0.0.1:8123） | health/DEMO01（含重放）/AUTH01-02/me/runtime/PROF01/ONB01/BIND01-04/MEDIA01-03（含 ticket 播放真实字节）全部通过；CHANGE01 在 B 未就绪时如实 501；`SMOKE_OK` |

`tests/identity/` 共 39 项，覆盖：独立账号与幂等重放、限流、匹配/不匹配草稿、草稿不改正式档案、
确认后版本与计划导入一次、依赖 501 时回滚、权限矩阵（本人/绑定子女/未绑定/他人/匿名）、
版本冲突、绑定码前导零/重发/过期/一次性消费/已绑定、媒体落盘与限额/MIME、票据播放与过期/篡改、
提案窗口（不播报不启动、重复回执不重设、59/61 秒边界）、拒绝与到期竞争、版本冲突与绑定撤销
记 conflicted、幂等决定、用药/设置提案经端口应用、分页与过滤、重启后续跑。

未运行：真实模型/ASR/TTS、手机 HTTPS、Web Push、业务 AC01–AC14 的跨三人端到端验收、
真实多进程限流（当前是单进程内存限流）、旧数据库的手工迁移。

## 11. 联调脚本与 C 分支的合并验证

### 11.1 一键三轮验收

`python -m app.tools.integration_smoke`（临时库、进程内；`--base-url` 可打真实服务，
`--strict` 把 PENDING 也算失败，用来做合并闸门）。三态如实报告：`OK` / `PENDING`（真实 501）/
`FAIL`（契约或数据不一致）。PENDING 绝不计为成功，脚本只用自己的临时 DATA_DIR。

当前在 `backend/platform` 上的结果：**19 ok / 9 pending / 0 failed**。pending 的 9 步正是
B/C 的端口缺口：ONB02（B 计划导入 + 历史）、AGENT01（C 的 HTTP 层）、PLAN02/TASK01/REC02/
CHANGE01（B 的计划、任务、打卡、通知入队）、REC01/REPORT01/MEM01（B 的查询与 C 的记忆路由）。
两条隔离断言已经 OK：另一个 DEMO01 家庭的子女读他人档案/看板均 403。

### 11.2 B 已合并：生产 composition 接线（`integration/f1`）

B 的 `backend/health` = `b1535f8` 已经把我的 A0/A1/A2 全部合入（`72d7610` 是它的祖先），
并在其上完成 B1/B2 服务与 PLAN02/PLAN03/TASK01/REC02/REC03/REPORT01/NOTI03 的 HTTP flow。
因此我把 `integration/f1` 从 `backend/platform` 快进到该提交，只补集成人这半边：

- **生产 composition 接线**：`compose()` 现在构造 `access`/`media`/`memory` 一次，并把同一个
  clock（以及 access/media/memory/changes）注入 `MedicationService`/`CheckinService`/
  `NotificationService`/`ReportService`。这是 B 的 `health_flows.perform` 两道闸门之一：
  `getattr(service,'clock') is not app.state.clock` 就必须 501。
- **修一个集成才暴露的真 bug**：`ChangeService.create` 之前写 `notification.id`，而
  `NotificationPort.enqueue` 的契约返回 `Notification` DTO（`notification_id`）。现在已改，
  测试替身也改成返回同样的形状。
- **CHANGE01 已登记为 true**（B 的 `enqueue` 就绪后实测 201）；CHANGE04 仍为 false，
  因为 accept 走完整应用路径还要 C 的 `MemoryPort.on_source_changed`。
- 框架用例 `CHANGE04` 的代表请求从 `reject` 改为 `accept`：reject 只关通知，accept 才覆盖
  "写目标 + 失效来源"的完整契约，用它做能力闸门更严格。

临时打开 B 已接线的开关（仅实测用，未提交）后的联调结果：
**22 ok / 7 pending / 0 failed**，`PLAN02`、`CHANGE01`、`REPORT01` 由 PENDING 转 OK。
其余 pending 的真实原因：

| 仍 501 | 原因 |
| --- | --- |
| ONB02 | `HistoryService.import_demo_history` 仍是 A0 桩（B 只要实现它即可） |
| TASK01 | `TaskService.today` 仍是 A0 桩 |
| REC02 | 依赖 TASK01 产出 task_id |
| REC01 / DASH01 / CAL01 / SET01–02 / PLAN01 / NOTI01–02 / NOTI04 | B 尚未接 flow |
| AGENT01 / MEM01 | C 未合并（`backend/agent` 仍停在 `7d8bfea`） |

`backend/health` 上此时有 **158 passed, 42 deselected**（含上面的修复）、契约 hash 未变、
`Architecture OK`。


### 11.4 B 的七项请求落地情况（`integration/f1`，另含 C 合并）

已合入 B 的 `8fc6289`（在 `b1535f8` 之上）与 C 的 `backend/agent`（`7d8bfea`），两者均无冲突。

| B 的请求 | 落地 |
| --- | --- |
| 1. 合入 `8fc6289` | 已合入，`integration/f1` 现含 A0/A1/A2 + B1/B2 + C1 |
| 2. `tasks=checkins`, `history=checkins` | 已按 B 的写法接线，`TaskService`/`HistoryService` 两个 A0 桩不再被组装使用 |
| 3. 冻结已有服务方法 | `contracts/ports.py` 已加：`MedicationPort.list/settings/update_settings`、`CheckinPort.list/cancel`、`ReportPort.calendar/dashboard`、`NotificationPort.presence/query`，签名与 B 变更申请逐字一致 |
| 4. 合入 C 并注入 clock/access | 已合入；`MemoryService(clock, access)`，六项测试验证 `service.clock is app.state.clock` |
| 5. 模型约定 | `daily_tasks.cancelled_at`（软停用，不删行）、新表 `daily_goal_batches(elder_id, local_date, category, generated_at)`（区分"已生成且不适用"与"从未生成"）、`DailyTask.cancelled: bool=False` |
| 6. 通知协作 | 播报计数约定按 B 的逐次 `playback_completed.event_id` 采纳；提案通知现在带**真实音频**（见下）；扫描器一个 tick 内同 tx 先跑 `notifications.scan` 再跑 `changes.apply_due`；亲情录音所有权由 `MediaPort.assert_owned_voice` 提供 |
| 7. A2 修正 | 用药提案 `create` 不再 `get_plan(None)`、`deactivate` 传 `patch=None`、`mark_played` 补 `require_elder_access(...,"self")`、`_system_actor` 改名 `_principal_for_timeout` 并说明不是伪造用户决定（`applied_by="timeout"` 审计） |

**提案音频（原第 6/13 项）**：`CHANGE01` 改为两段式——短读鉴权 → 事务外渲染确定性演示提示音
（`app/fixtures/announcement.py`，本地 PCM，不走供应商）→ 短写事务内 `register_announcement`
登记并用 `audio_asset_id` 入队通知。因此"完整音频播报"现在可真正启动 60 秒窗口。真实语音仍由 C 的
TTS 在事务外替换该 fixture，事务形状不变。

**契约变化（本次唯一）**：`DailyTask` 增加 `cancelled` 字段，OpenAPI 重新导出为
`4b7ade26f590902a4eb131920589184b95e0b54a293e9df80ac9f8aa4859532c`；表数从 18 变 19
（`daily_goal_batches`）。`fg04` 的表集合断言已同步。

**当前验证**：`pytest tests -q` → **211 passed, 42 deselected**；`Architecture OK`；
联调脚本 **21 ok / 8 pending / 0 failed**——`ONB02` 已由 PENDING 转 OK（B 的计划导入 + 历史导入
经 `history=checkins` 生效），`CHANGE01` 已 OK。剩余 pending：`PLAN02/TASK01/REC01/REPORT01/
NOTI02`（B 未开启 `health_capabilities`，按他要求由他自己逐项开）、`AGENT01/MEM01`（C 的 HTTP 层）。

### 11.5 C2 激活（A-owned），`integration/f1`

C 的新提交（`7aba5a8`，含 C2 HTTP 与"capabilities 留空待 A 激活"）已合入，唯一冲突在
`tests/agent/test_agent_service.py`（两边都改成注入失败端口，取 C 的写法并保留本地 `replace`
导入）。激活由 A 分三步完成：

1. **运行时接线**：`create_app` 现在构造 `app.state.agent`（`AgentService(clock, bundle, memory)`，
   与 `services.memory` 同一实例）以及 `agent_chat`/`agent_asr`/`agent_tts` 三个 mock provider。
   C 的 `_ready()` 正是检查这四个属性，缺一个就如实 501。
2. **放开 `Runtime.providers` 枚举**：`Literal["not_implemented"]` →
   `Literal["mock","real","not_implemented"]`。mock 是真实可运行的实现、必须能上报；契约 hash 变为
   `4b7ade26f590902a4eb131920589184b95e0b54a293e9df80ac9f8aa4859532c`。
3. **登记能力**：`agent_capabilities.CAPABILITIES = C2_OPERATIONS`（7 项），`PROVIDERS` 三项为 `mock`。

C 原测试 `test_default_unwired_deployment_stays_501_and_capability_false` 的前提（默认部署未接线）
已不成立，改写为 `test_agent_wiring_guard_and_activation`：`_ready(Bare())` 必须 501，默认部署必须
四属性齐全、providers 报 mock、7 项能力为 true。

**实测**：`pytest tests -q` → **237 passed, 42 deselected**（含合入 C 的 `a2d16f1`/`1e31bb6`：
默认部署验收 + 可持久化用药任务准备 + 通知→提案关联走 `ChangePort.query`）；联调
**24 ok / 7 pending / 0 failed**。C 已用冻结的 `ChangePort.decide` 接好 `decide_change` 动作。
第一轮链路已打通：DEMO01 → 建档确认 → 绑定 → 午餐图片 → `AGENT01` 生成待确认动作 →
`AGENT02` 确认后经 B 的 `CheckinPort` 落成真实打卡；`MEM01` 可读。剩余 7 个 pending 全部是 B 的
health 接口尚未开启 `health_capabilities`（`PLAN02/TASK01/REC01/REC02/REPORT01/NOTI02/DASH01`）。
若把这 7 个已验证接口的开关临时打开，联调结果为 **27 ok / 4 pending / 0 failed**。

### 11.6 回应 B 的收尾清单（`integration/f1`，最新）

| B 的要求 | 落地 |
| --- | --- |
| 1. 设置提案调用 B 的 `update_settings`，同步未来目标 | `ChangeService._apply` 的 settings 分支改为调用冻结端口 `MedicationPort.update_settings(tx, actor, elder_id, base_version, patch)`；A 不再直接写 `reminder_settings_json`、也不再自己 `version += 1`（避免重复递增）。B 的 strict xfail 因此 XPASS，已按 B 授权移除标记，`tests/health/test_shared_settings_gap.py` 现为普通回归测试。 |
| 2. 播报实际提案内容、替换提示音 | 删除合成提示音。新素材 `backend/fixtures/identity/*.wav`（5 段，Windows SAPI `Microsoft Huihui Desktop` 离线生成，16 kHz 单声道）+ `proposal_notices.json` 清单；`app/fixtures/proposal_notice.py` 按 (target_type, operation) 取段落，**通知 text 与音频逐字一致**。契约新增 `SpokenNotice(text, audio)`，`ChangePort.create(..., notice=...)`，仍遵守"事务外准备、事务内登记"。 |
| 3. 统一系统授权入口 | 新增保留主体 `contracts/context.py: SYSTEM_ACTOR`（`user_id="system"`，AUTH 从不签发、users 表不含该 id）；`require_elder_access` 在角色判断前对系统主体短路并返回 `scope="system"`。`apply_due`/`_settle_if_due` 一律用它，**不再构造老人 Actor**；审计仍写 `applied_by="timeout"`。B/C 的 `authorize()` 都委托 A 的 access port，因此自动认可该系统主体，无需他们改代码。 |
| 4. 联调脚本修正 | 药品计划改成未来 23:30 时段（B 不为当天已过时刻生成目标）；任务按 `plan_id` 精确匹配；回执前先发 `NOTI01` 可见心跳；提案 `base_version` 改为读取档案当前版本（原来写死 1，建档后必然冲突）。 |
| 5. Agent 确认的可信来源 | `CheckinPort.create_or_update(..., *, source: Literal["user","agent_confirmed"] = "user")` 已冻结。来源由服务端参数决定、永不取自客户端 body；C 在确认动作执行时传 `agent_confirmed`，B 落库。 |

**给 B 的关键证据**：把 `NOTI03` 临时打开后，联调脚本 **39 ok / 0 pending / 0 failed**——
`displayed → answered → playback_completed → window armed → timeout applies the change` 全部通过，
即"完整语音播报 → auto_apply_at → 60 秒后自动生效"已在真实 HTTP + 真实 B/C 端口上跑通。
按提交状态（`NOTI03` 仍由 B 关闭）为 **34 ok / 3 pending / 0 failed**；
`pytest tests -q` → **267 passed, 42 deselected**（无 xfail）。

### 11.7 接入 C 的完整提案播报（`974d719` 之后）

C 提供了 `app/providers/proposal_notice.py`：`proposal_text()` 逐字段叙述补丁（含显式清空），
`ProposalFixtureTTS` 按文本精确匹配 5 段完整语音。A 侧接线：

- `identity_flows.create_change` 在写事务**之外**调用
  `prepare_proposal_notice(body, tts=ProposalFixtureTTS(), plan=...)`；用药 update/deactivate 先用
  一个短读 UoW 调 `MedicationPort.get_plan` 取当前计划供叙述使用。
- 返回的完整文本作为通知 `text`，有匹配语音时用返回的 `SpokenNotice` 登记为 `audio_asset_id`；
  没有匹配语音时只保存完整文字、保持 `pending_notice`、**不会**开启窗口（C 的约定）。
- `ChangePort.create(..., text, notice)` 已冻结两个可选参数：`text` 为权威叙述文本，`notice` 为
  语音（可为 None）。
- 删除了 A 上一批的通用提示语音素材（`backend/fixtures/identity/*.wav` 与
  `app/fixtures/proposal_notice.py`），避免"只播类别不播内容"的两套实现并存。
- 因此 C 的 A 侧 strict xfail
  `test_default_change_http_notification_reads_actual_patch_values` 已 XPASS，标记按约定移除。

**剩余唯一阻塞（B）**：C 现在强制"可信来源"，`CheckinService.create_or_update` 必须接受并保存
冻结的 `source` 参数，否则 `AGENT02` 确认动作如实返回 501（`Checkin adapter must implement the
trusted source parameter`）。B 的实现到位后：

| 场景 | 当前 | B 落地后预期 |
| --- | --- | --- |
| `pytest tests -q` | 290 passed / 2 xfailed（均为 B 的 source） | 292 passed / 0 xfailed |
| 联调（NOTI03 关闭，B 自己的开关） | 32 ok / 4 pending | 33 ok / 3 pending |
| 联调（NOTI03 临时打开） | 37 ok / 1 pending（AGENT02） | 38 ok / 0 pending |

### 11.8 全绿里程碑：45/45 P0 已实现（`f1-integrated-v1`）

B 在 `c1fe1d6` 里实现了可信来源（`CheckinService.create_or_update(..., source=...)` 落库）、
在 `e78e604` 里以"完整内容语音"为前提打开了 `NOTI03`；C 在 `e24604b` 对齐验收。合并后：

| 项 | 实际结果 |
| --- | --- |
| `python -m pytest tests -q` | **298 passed, 42 deselected, 0 failed, 0 xfailed** |
| `python -m app.tools.integration_smoke` | **39 ok / 0 pending / 0 failed** |
| 同上 `--strict` | **退出码 0** |
| `GET /runtime` capabilities | **45/45 个 P0 为 true**，仅 `web_push`（P1）为 false |
| providers | `chat/asr/tts` 均为 `mock` |
| OpenAPI / 架构 | `4b7ade26…` / `Architecture OK` |

发布动作（由 A 执行，均为快进或新增，不改写历史）：

- `backend/platform` 快进到本提交（此前停在 A2 的 `72d7610`）。
- 打一次性集成标签 `f1-integrated-v1`，指向本提交；**不移动、不重打**。
- `integration/f1` 与两名开发者的分支都包含同一提交，后续如需修 P1 从该标签拉分支。

仍未做（不属于 P0 闭环）：P1 的 `AUTH03/BIND05/PLAN04/CHANGE05/MEM04/PUSH01–03`、
真实模型/ASR/TTS、手机 HTTPS 与真实 `<audio>` 播放、前端界面、AC01–AC14 的三人端到端演练。

### 11.9 演示机就绪（P0 之外的收尾）

前端与真机演示推后进行，因此先把"演示当场不会崩"这件事做掉：

- **旧库守卫**：`app/core/db.py::assert_schema_current` 在启动时对比实际列与模型列。F1 没有迁移
  工具、`create_all` 不会给旧表加列，旧 `DATA_DIR` 现在会以
  `DATABASE_SCHEMA_OUTDATED: ... daily_tasks(cancelled_at)` 明确失败，而不是在后面冒出离奇 SQL 错误。
  有对应测试 `test_outdated_data_dir_fails_fast`。
- **README「演示机准备」**：要求从空 `DATA_DIR` 开始、设置 `MEDIA_TICKET_SECRET`、按需开
  `SCANNER_ENABLED`，并说明"删 DATA_DIR 即完全重置"与"演示账号由 DEMO01 生成"。
- **`.env.example`** 补上 `MEDIA_TICKET_SECRET` / `MEDIA_TICKET_SECONDS`（此前缺失，照抄示例会
  用默认开发密钥）。
- **接口说明抬头**改为真实状态：45 个 P0 全部实现，P1 未挂载。

验证：`pytest tests -q` → **299 passed, 42 deselected**（新增 1 项旧库守卫测试）。

### 11.3 C 分支（`backend/agent`，7d8bfea）的合并结论

- C 只改了自己白名单内的文件，**没有碰任何共享文件**（contracts/schemas/models/core/main/
  composition/seed/OpenAPI/框架测试），合并面干净。
- 在临时 worktree 实测把 `f1-shared-v1` 合入 `origin/backend/agent`：**零冲突**，
  合并后全量 `pytest tests -q` → **115 passed, 42 deselected**（A 的 109 + C 的 6）。
- C 已实现 `MemoryService.on_source_changed(...)`，与 A2 提案应用路径的签名一致。
- 唯一需要 A 侧接线的点：C 的 `MemoryService(clock=None, access=None)` 要求注入同一个 Clock 与
  AccessPort。合入后把 `composition.compose` 的两行改成

  ```python
  access = AccessService()
  memory = MemoryService(clock, access)
  ```

  否则记忆服务会在测试里退回 `SystemClock`。A0 现在写的是无参 `MemoryService()`，因为 A 分支上的
  桩还不接受参数；这条等 C 合入时一并改，属于一次性集成编辑。
- C 的 `agent_capabilities.py` 在其分支上不存在（该文件由 A0 新增）。C 合入 A0 后需在
  `app/services/agent_capabilities.py` 登记自己已验收的 operation 与真实 `PROVIDERS`，
  `/runtime` 才会如实显示。

## 12. 缺口与下一步

1. **B**：`MedicationPort.import_draft/get_plan/apply_change`、`HistoryPort.import_demo_history`、
   `NotificationPort.enqueue/handle_event/mark_proposal_handled` 仍需落地；它们就绪后 A 把
   CHANGE01/CHANGE04 登记为 true 并复跑 `tests/identity`。
2. **C**：合入 `f1-shared-v1`（已验证零冲突），补齐 `AgentService` 的 composition 接线与 HTTP 层；
   `ChangePort.decide` 供 `decide_change` 动作，`MediaPort.register_generated` 供 TTS。
3. ONB02 的“匹配样本 + 有用药计划”路径依赖 B 的计划导入；当前真实运行返回 501 并回滚，
   有专门测试证明不会假成功。
