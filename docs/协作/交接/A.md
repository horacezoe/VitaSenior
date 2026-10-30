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

**远端推送未执行**：本机没有 GitHub 凭据，SSH 22 端口被阻断，`git push` 会在凭据提示处失败。
提交与标签都在本地 `backend/platform` 上就绪（见第 9 节），需要凭据的人执行
`git push origin backend/platform` 与 `git push origin f1-shared-v1` 即可，内容无需改动。

### OpenAPI

| 阶段 | SHA-256 |
| --- | --- |
| F0 基线（A0 结束时未变） | `73f9920606bdd8c6338c67327e72adef1ea1a474352aa4c22c949e071ad75657` |
| A1 结束（当前） | `6a2de0894ef6de2094799d9e3c1d4cef884d317cc62c336c98f535dd1527720d` |

A1 的唯一契约差异是 MEDIA03 的 security 从 `[{HTTPBearer}]` 变为 `[{HTTPBearer}, {}]`：
任务单要求“有效 ticket 单独授权，仍保留 Bearer”，`<audio src>` 无法带 Authorization 头，
因此 OpenAPI 必须声明鉴权可选，否则前端按契约会认为音频必须带 Bearer。其余 44 个
operation 的路径、字段、状态码、错误响应逐字节未变。

## 2. 提交清单

| 阶段 | 提交 | 标签 |
| --- | --- | --- |
| A0 共享适配 | `10d51af` | `f1-shared-v1`（一次性，不移动） |
| A1 家庭档案与媒体 | 见 `backend/platform` HEAD（本文件所在提交） | — |

B/C 合入方式：`git fetch origin --tags && git merge f1-shared-v1`（或 rebase 到该标签），
保留自己的提交，不 reset、不覆盖别人的工作。

## 3. A0 共享适配（回顾）

1. **F0 断言与长期测试分开。** `tests/framework/test_stage_f0.py` 保留 F0 严格断言
   （40 个业务路由全 501、只有五项能力、业务 port 桩 501），标记 `f0_stage`，默认不运行；
   `pytest -m f0_stage` 显式运行，业务能力登记后自动 `skip`（当前 42 skipped）。
   长期契约改为双向：登记为 true 的路由不得返回 501；未登记的路由必须恰好
   `501 MODULE_NOT_IMPLEMENTED`。
2. **能力按领域声明。** 见第 6 节；`/runtime` 只渲染，不再内联清单。
3. **AI 流程鉴权上下文。** `Auth` 依赖短读鉴权后释放事务，供应商调用期间不持有
   `BEGIN IMMEDIATE`；写操作另开 `write_unit()` 并在事务内重新验权。
4. **统一时钟/配置注入。** `compose(clock, settings, limiter)` 是唯一组装入口。
5. **内部 port 补齐并冻结签名。** 见第 5 节。
6. **历史导入统一入口。** `app/seed.py::import_demo_history` + `app/fixtures/history.py`。

## 4. A1 交付：家庭档案、绑定与媒体

### 4.1 已实现接口（能力已登记为 true）

| 编号 | 实际行为 |
| --- | --- |
| DEMO01 | 每次生成独立老人/子女账号（11 位、全局唯一、`demo_*` 分组）与未确认老人草稿；**不建亲属关系**；同幂等 key 重放原家庭；公开入口按 IP 限流 10 次/60 秒（进程内，演示规模）。新手机号可直接走 AUTH01/AUTH02。 |
| ONB01 | 命中 `community_sample_001` → `matched` + 可选草稿计划；否则 `not_found` + 空草稿。结果只写 `elder_profiles.onboarding_draft`，正式档案 version/字段不变。 |
| ONB02 | 校验 `draft_id` 属于本老人、`expected_version` 一致后升为 `confirmed`、version+1、`source=user_confirmed`、清空草稿；同一事务调用 B 的 `MedicationPort.import_draft` 落库计划，匹配的演示档案再调 `import_demo_history`。任一步失败整笔回滚。 |
| PROF01 | 本人与有效绑定子女可读；未绑定/他人 → 403。 |
| PROF02 | 仅本人；`expected_version` 不符 → 409 `VERSION_CONFLICT` 且回 `current_version`；子女 → 403 `PROPOSAL_REQUIRED`；仅 `birth_date` 可置空。 |
| BIND01 | 四位码（保留前导零），5 分钟有效；重发同事务撤销旧码；全局活动码唯一。 |
| BIND02 | 只预览不消费；未知/失效 → 409 `BIND_CODE_INVALID`，过期 → `BIND_CODE_EXPIRED`，已用 → `BIND_CODE_CONSUMED`；返回脱敏手机号与 `already_bound`；按子女限流。 |
| BIND03 | 同一事务消费 + 建绑定；并发由 `BEGIN IMMEDIATE` 与部分唯一索引兜底；已绑定再消费 → 409 `BIND_CODE_CONSUMED`（同幂等 key 才重放）。 |
| BIND04 | 子女的活动绑定列表（含年龄、关系、binding_id）。 |
| MEDIA01 | 真实落盘 `DATA_DIR/media/`；图片 ≤10 MiB（JPEG/PNG/WebP），音频 ≤15 MiB（WAV/MP3/WebM/MP4）；超限 413、类型不符 415；关联 elder 时校验关系；返回 5 分钟票据地址；同 key 同内容重放同一 asset。 |
| MEDIA02 | 校验归属/绑定后重新签发票据地址。 |
| MEDIA03 | **Bearer 或 ticket 二者其一**即可取字节，`Content-Type` 按素材设置，不包 JSON；票据过期/篡改 → 404，无凭据 → 401，未绑定子女 → 404。 |

### 4.2 仍为 501

CHANGE01–04（A2 下一批）、以及 B/C 的全部业务接口。`MedicationPort.import_draft`、
`HistoryPort.import_demo_history` 目前仍是 501 桩：ONB02 的“匹配样本 + 有用药计划”路径
依赖它们，真实运行时**不会吞 501 假成功**，会返回 501 并回滚档案（有专门测试覆盖）。

### 4.3 A1 实际执行的测试

| 命令（backend 目录） | 结果 |
| --- | --- |
| `python -m pytest tests -q` | `94 passed, 1 failed, 42 deselected` → 唯一失败是 fg10 要求交接文档记录当前契约 hash，本文件补上后通过 |
| `python -m pytest tests/identity -q` | `25 passed` |
| `python -m pytest tests/framework -q` | `69 passed, 42 deselected` |
| `python -m pytest tests -m f0_stage -q` | `42 skipped, 95 deselected`（阶段已关闭，符合设计） |
| `python -m app.tools.export_contract --check` | `OpenAPI matches 6a2de0894ef6de2094799d9e3c1d4cef884d317cc62c336c98f535dd1527720d` |
| `python -m app.tools.check_architecture` | `Architecture OK` |
| `python -m pip check` | `No broken requirements found.` |

`tests/identity/` 覆盖：独立账号与幂等重放、限流、匹配/不匹配草稿、草稿不改正式档案、
确认后版本与计划导入一次、依赖 501 时回滚、权限矩阵（本人/绑定子女/未绑定/他人/匿名）、
版本冲突、绑定码前导零/重发/过期/一次性消费/已绑定、媒体落盘与限额/MIME、票据播放与过期/篡改、
以及已绑定子女才可见媒体。

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

class TaskPort(Protocol):
    def today(self, tx, actor, elder_id: str, day: date) -> TaskList: ...

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
  displayed、playback_completed 需完整播放次数；`playback_completed` 与提案
  `notified_at/auto_apply_at` **同一事务**）。B 通过注入的 `ChangePort.mark_played` 启动窗口，
  不要重写提案状态机。
- `ChangePort.decide` 是变更提案唯一接受/拒绝入口（C 的 `decide_change` 动作调用它）。
- `MediaPort.open_content(actor=None, ticket=...)` 支持仅票据播放；`register_generated` 供 TTS
  生成音频登记（C 不得直接写媒体表或猜路径）。
- `HistoryPort` 由 B 实现，行模板在 `app/fixtures/history.py`，按 `demo_id` 去重。

## 6. 能力声明写在哪

| 文件 | 归属 | 当前值 |
| --- | --- | --- |
| `app/services/identity_capabilities.py` | A | 5 个基础 + DEMO01、ONB01/02、PROF01/02、BIND01–04、MEDIA01–03（17 项） |
| `app/services/health_capabilities.py` | B | 空 |
| `app/services/agent_capabilities.py` | C（含 `PROVIDERS`） | 空 / `not_implemented`×3 |

规则：接口用真实数据库测试通过后才把自己域的编号加进去；`composition.declared_capabilities()`
只做并集，`routers/system.py` 只渲染。登记后 `test_all_routes.py` 会强制该路由不再返回 501。

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
- 服务里的时钟就是 `app.state.clock`（测试注入的 `FakeClock`），不要新建 `SystemClock()`。
- 生成音频用 `services.media.register_generated(...)`；引用他人音频用 `MediaPort.get_asset`。

## 8. 构造器与组装约定

- 唯一组装函数 `app.composition.compose(clock=None, settings=None, limiter=None)`；
  `create_app` 传入 `app.state.clock`/`app.state.settings`/`app.state.ratelimit`。
- 需要时间的服务按 `__init__(self, clock)` 或 `__init__(self, clock, settings)` 接收注入对象；
  `BindingService` 额外接收可选的 limiter。B/C 实现自身服务时沿用同样形状并在 composition 连线。
- 业务代码不得 `import app.composition`（`check_architecture` 会拒绝）。
- `ServiceBundle` 是 frozen dataclass，测试可用 `dataclasses.replace` 注入替身。

## 9. DEMO01 历史导入统一入口

```python
from app.seed import import_demo_history
import_demo_history(tx, services, actor, elder_id, demo_id=demo_id, scenario="diabetes_daily")
```

- 仅 B 的 `HistoryPort` 写 `daily_tasks`/`checkins`（`source="demo_seed"`）并联动 C 记忆素材；
  A 只调度。无匹配手工建档不调用，不凭空生成历史。
- 行模板 `app/fixtures/history.py`：14 天、确定性、无真实用药建议；非法场景直接 `ValueError`。

## 10. 缺口与下一步

1. **A2（下一批）**：CHANGE01–04 + `mark_played`/`apply_due` 60 秒窗口状态机；
   应用时调 B `MedicationPort.apply_change`、C `MemoryPort.on_source_changed`，同一事务提交。
2. **B 依赖**：`MedicationPort.import_draft`（ONB02 落库用药计划）、`HistoryPort.import_demo_history`
   （演示历史）。未实现时 ONB02 相关路径返回 501 并回滚，已有测试证明不会假成功。
3. **C 依赖**：`ChangePort.decide` 供 `decide_change` 动作；`MediaPort.register_generated` 供 TTS；
   `MediaPort.open_content` 可只凭票据。
4. 未运行：真实模型/ASR/TTS、手机 HTTPS、Web Push、企业级分布式限流（当前限流是单进程内存实现）、
   业务 AC01–AC14 的跨三人端到端验收。
