# Agent A 交接记录

角色：业务 Agent A（平台、家庭档案与媒体）+ 本轮集成人。

## 1. 基线与分支

| 项目 | 值 |
| --- | --- |
| 共同标签 | `f1-reviewed-v1` |
| 标签解引用 commit | `1034c76`（Publish reviewed F1 task sheets and agent handoff prompts） |
| 本轮已验证代码 commit | `497fc4ce6ede5ee951c57cd06913197391633f56`（标签的父提交；标签只多出文档） |
| 分支 | `backend/platform`（从 `f1-reviewed-v1` 创建，未 reset 任何远端分支） |
| OpenAPI SHA-256 | `73f9920606bdd8c6338c67327e72adef1ea1a474352aa4c22c949e071ad75657`（A0 未改变公共契约，逐字节一致） |
| 复验环境 | Windows / Python 3.12.4 / `backend/.venv` / `requirements.lock` |

A0 独立共享提交与一次性标签：见第 9 节（提交后回填 hash）。**不要重打标签，不要强推。**

## 2. A0 交付范围（本批）

A0 只做共享适配，不含业务实现；业务路由仍按能力声明返回 501。

1. **F0 专属断言与长期测试分开。** `tests/framework/test_stage_f0.py` 保留 F0 原始严格断言（40 个业务路由全 501、只有五项能力为 true、业务 port 桩 501），标记 `f0_stage`，默认不运行；`pytest -m f0_stage` 显式运行。业务能力一旦登记，该文件自动 `skip`，不再作为长期契约。长期契约改为双向能力一致：登记为 true 的路由不得返回 501；未登记的路由必须恰好返回 `501 MODULE_NOT_IMPLEMENTED`。
2. **能力声明按领域拆分。** 见第 5 节。`routers/system.py` 只读 `app.state.capabilities_declared`，不再内联清单。
3. **AI 流程鉴权上下文。** 新增 `Auth` 依赖：短读事务内鉴权后立即释放，供应商调用期间不持有 `BEGIN IMMEDIATE`；写操作另开 `write_unit()` 并在事务内重新验权。见第 6 节。
4. **统一时钟与配置注入。** `compose(clock, settings)` 是唯一组装入口，服务不再自建 `SystemClock()`/`Settings()`。
5. **内部 port 补齐并冻结签名。** 见第 4 节。
6. **DEMO01 历史导入统一入口。** `app/seed.py::import_demo_history` + `app/fixtures/history.py`，见第 7 节。

## 3. 改动文件

新增：
- `app/contracts/media.py`
- `app/services/{identity,health,agent}_capabilities.py`
- `app/services/task_service.py`、`app/services/history_service.py`（B 域占位，A0 只为冻结签名/组装）
- `app/fixtures/{__init__,history,identity}.py`
- `tests/framework/{routes_cases,test_stage_f0,test_shared_adaptation}.py`

修改：
- `app/contracts/{ports,bundle}.py`（新签名；`ServiceBundle` 新增 `tasks`、`history`）
- `app/composition.py`（时钟/配置注入、能力汇总、新 port 组装）
- `app/main.py`（`compose(clock, settings)`；`capabilities_declared`/`providers` 挂到 app.state）
- `app/routers/{dependencies,system,agent}.py`
- `app/seed.py`
- `app/services/{binding,profile,change,media}_service.py`（仅补构造器，业务仍 501）
- `app/tools/check_architecture.py`（`task_service`/`history_service` 归 health 域）
- `pyproject.toml`（`f0_stage` marker + 默认 `-m 'not f0_stage'`）
- `tests/framework/{conftest,test_acceptance,test_all_routes}.py`

## 4. 冻结的内部 port 签名

一律 `from app.contracts.ports import ...`；`tx` 是调用方持有的 `Session`，`actor` 来自 `app.contracts.context.Actor`。任何方法都不得 commit/rollback/新建 Session/调用外部供应商。

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
    def query(self, tx, actor, elder_id: str, status: ProposalStatus | None, limit: int, cursor: str | None) -> Page[ChangeProposal]: ...
    def read(self, tx, actor, proposal_id: str) -> ChangeProposal: ...
    def decide(self, tx, actor, proposal_id: str, decision: ChangeDecision, now: datetime) -> ChangeProposal: ...
    def mark_played(self, tx, actor, proposal_id: str, now: datetime) -> ChangeProposal: ...
    def apply_due(self, tx, now: datetime) -> list[ChangeProposal]: ...

class TaskPort(Protocol):
    def today(self, tx, actor, elder_id: str, day: date) -> TaskList: ...

class NotificationPort(Protocol):
    def enqueue(self, tx, actor, source_key: str, payload: NotificationEnqueue) -> Notification: ...
    def handle_event(self, tx, actor, notice_id: str, event: NotificationEvent, now: datetime) -> EventResult: ...

class MediaPort(Protocol):
    def get_asset(self, tx, actor, asset_id: str) -> MediaAsset: ...
    def store_upload(self, tx, actor, *, elder_id: str | None, purpose: str, filename: str,
                     content_type: str, content: bytes) -> MediaAsset: ...
    def open_content(self, tx, actor: Actor | None, asset_id: str, *, ticket: str | None = None) -> MediaContent: ...
    def register_generated(self, tx, actor, elder_id: str, *, content: bytes, mime_type: str,
                           purpose: str, duration_ms: int | None) -> MediaAsset: ...

class HistoryPort(Protocol):
    def import_demo_history(self, tx, actor, elder_id: str, *, demo_id: str, days: int) -> None: ...
```

约定补充：

- `NotificationPort.handle_event` 承担完整回执语义（displayed 需有效可见心跳、answered 需已 displayed、playback_completed 需完整播放次数；`playback_completed` 与提案 `notified_at/auto_apply_at` **同一事务**）。B 通过注入的 `ChangePort.mark_played` 启动窗口，不要在 B 里重写提案状态机。
- `ChangePort.decide` 是变更提案的唯一接受/拒绝入口（C 的 `decide_change` 动作调用它）。`apply_due(tx, now)` 是扫描器入口，不伪造 `actor`。
- `MediaPort.open_content(actor=None, ticket=...)` 支持仅票据播放；`register_generated` 供 TTS 生成音频登记，返回 `MediaAsset`。
- `HistoryPort` 由 B 实现（`app/fixtures/history.py` 提供行模板），按 `demo_id` 去重。

### 仍是 501 的 port（B/C 待实现）

`BindingPort.preview/consume/list_elders`、`ProfilePort.read/update`、`ChangePort.*`、`TaskPort.today`、`NotificationPort.enqueue/handle_event`、`HistoryPort.import_demo_history` 在 `f1-shared-v1` 时仍抛 501（A1/A2 由 A 实现前三组，B/C 各自实现自身）。`MediaPort.*` 在 A1 实现。`MedicationPort`、`CheckinPort`、`ReportPort`、`MemoryPort` 保持 B/C 原有占位；A 调用它们时**不得吞掉 501 伪造成功**。

## 5. 能力声明写在哪

| 文件 | 归属 | 初始值 |
| --- | --- | --- |
| `app/services/identity_capabilities.py` | A | `SYS01,SYS02,AUTH01,AUTH02,AUTH04` |
| `app/services/health_capabilities.py` | B | 空 |
| `app/services/agent_capabilities.py` | C（含 `PROVIDERS`） | 空 / `not_implemented`×3 |

规则：接口用真实数据库测试通过后才把自己域的编号加进去；`composition.declared_capabilities()` 只做并集，`routers/system.py` 只渲染，任何人不改别人的文件。登记后 `test_all_routes.py` 会强制该路由不再返回 501。

## 6. AI 事务入口（C 必读）

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

- `Auth` 只保证“已登录”，不提供 `tx`，避免有人把供应商调用夹进 `BEGIN IMMEDIATE`。
- 写事务里必须重新 `check_access`/`check_resource`（通过 `app.state.services.access`），不能复用读阶段的结论。
- 服务对象上的时钟就是 `app.state.clock`（测试注入的 `FakeClock`），不要新建 `SystemClock()`。
- `routers/agent.py` 的 AI01/AI02/AGENT01/AGENT02 已切到该模式（仍返回 501），C 直接替换 `unavailable(...)`。

## 7. 构造器与组装约定

- 唯一组装函数 `app.composition.compose(clock=None, settings=None)`；`create_app` 传入 `app.state.clock` / `app.state.settings`。
- 需要时间的服务按 `__init__(self, clock)`（如 `BindingService`）或 `__init__(self, clock, settings)`（`ProfileService`/`ChangeService`/`MediaService`）接收注入对象。B/C 实现自身服务时沿用同样形状，并在 `composition.compose` 里连线。
- 业务代码不得 `import app.composition`；`check_architecture` 会拒绝。
- `ServiceBundle` 是 frozen dataclass，测试可用 `dataclasses.replace` 注入替身；新增字段必须给 `composition` 补上。

## 8. DEMO01 历史导入统一入口

```python
from app.seed import import_demo_history
import_demo_history(tx, services, actor, elder_id, demo_id=demo_id, scenario="diabetes_daily")
```

- 仅 B 的 `HistoryPort` 负责写 `daily_tasks`/`checkins`（`source="demo_seed"`）与引用 C 记忆素材；A 只调度，不重复建观众账号。
- 无匹配手工建档不调用该入口，不凭空生成历史。
- 行模板在 `app/fixtures/history.py`（14 天、确定性、无真实用药建议）；场景非法直接 `ValueError`，失败不吞。

## 9. 共享提交与标签

| 项 | 值 |
| --- | --- |
| A0 共享提交 | `见本文件提交 hash（f1-shared-v1 指向该提交）` |
| 一次性标签 | `f1-shared-v1`（只建立一次，不移动） |

B/C 合入方式：`git fetch origin --tags && git merge f1-shared-v1`（或 rebase 到该标签），保留自己的提交，不 reset、不覆盖。

## 10. 实际执行的验证

在 `backend/`、`backend/.venv`、Python 3.12.4 下：

| 命令 | 结果 |
| --- | --- |
| `python -m pytest tests/framework -q` | `70 passed, 42 deselected, 1 warning` |
| `python -m pytest tests/framework -q -m f0_stage` | `42 passed, 70 deselected, 1 warning` |
| `python -m app.tools.export_contract --check` | `OpenAPI matches 73f9920606bdd8c6338c67327e72adef1ea1a474352aa4c22c949e071ad75657` |
| `python -m app.tools.check_architecture` | `Architecture OK: no cross-domain implementation imports` |
| `python -m pip check` | `No broken requirements found.` |

唯一警告是上游 Starlette `TestClient` 的 httpx 弃用提示，未屏蔽。未运行：真实模型/ASR/TTS、手机 HTTPS、Web Push、业务 AC01–AC14（A1/A2 进行中）。

## 11. 缺口与下一步（A 自己）

1. A1：DEMO01、ONB01/02、PROF01/02、BIND01–04、MEDIA01–03（含 MEDIA03 短票据，届时需同步 OpenAPI 快照并在本文件说明差异）。
2. A2：CHANGE01–04 与 `mark_played`/`apply_due` 状态机。
3. 依赖：`MedicationPort.import_draft`（B）是 ONB02 落库用药计划的必要依赖；`HistoryPort`（B）是匹配演示导入 14 天历史的必要依赖。测试可注入替身，真实运行不得吞 501。
