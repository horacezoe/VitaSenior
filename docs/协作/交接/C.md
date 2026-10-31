# C 当前交接：完整提案内容、SYSTEM 授权与可信来源适配

日期：2026-10-31（Asia/Shanghai）。状态：**C_IMPLEMENTED / INTEGRATION_NOT_READY**。本节覆盖后面的历史就绪结论；三个 strict xfail 和网络阻塞均未计为通过。

代码提交：`73e8f200bb04c36dc1b59088ebd7c4415fc08259`，分支 `backend/agent`。正常快进合入 A/B 的 `integration/f1@0894154494f3363435fed9d31b146b22dadbd8c8`，含 `backend/health@ce472da`。没有修改 A/B 实现或公共文件。B 提供的路径实际为 `docs/协作/交接/B.md`，不是“交接B.md”。

## 本批 C 已完成

- `providers/proposal_notice.py` 提供完整提案文字与真实匹配语音准备器，覆盖档案、提醒设置、计划新增/修改/停用。逐字段读出提交的实际值、清除值、替换列表、时间、剂量与原因；创建包含默认字段。计划修改/停用必须有 ID/版本匹配的真实 MedicationPlan，不猜目标药物。
- `fixtures/agent/proposal_cases.json`、`proposal_manifest.json`、五个 `proposal_*_full.wav` 和生成脚本。离线 Huihui 中文语音，16kHz/16bit/mono PCM；文本和 SHA-256 一一对应。未知实际值不借用其他音频，返回完整文字与无音频。运行服务器无需 Windows/SAPI/供应商密钥。原 ASR 与五段普通语音清单没有扩张。
- `AgentService` 按冻结 CheckinPort 固定传 `source="agent_confirmed"`。旧 B 签名在执行前明确 501；不回退成 user，不直接改 B 表。若适配器接参却丢弃来源，502 并回滚全部写入/动作/幂等成功结果。业务内部 TypeError 不被吞掉或重试。
- `MemoryService` 复用共享 AccessPort 与 A 已发布的 SYSTEM 主体。系统仅可读取上下文/使来源失效，不能代替老人新建明确偏好、修正/删除记忆或确认 Agent 动作；本人、已绑定子女和陌生老人权限仍按中央检查。
- 新增 `test_proposal_notice.py`、`test_system_and_source.py`，扩展真实默认装配验收。真实 A/B ports 已验证完整语音字节登记、未播放无窗口、完整播放后才有60秒、SYSTEM 超时应用档案/设置、无音频仍 pending_notice、显式本人接受可用，播放不生成 Checkin。客户端自报 source 被422拒绝，直接用户打卡仍为 user。

## 实际验收（backend 目录，.venv / Python3.13.9）

所有 pytest 使用 tmp_path SQLite/FakeClock；网络脚本使用独立临时 DATA_DIR/随机端口并退出，没有触碰运行数据库。

```text
python -m pytest tests/agent -q --tb=short -rx
93 passed, 3 xfailed, 1 warning in 13.58s

python -m pytest tests -q --tb=short -rx
289 passed, 42 deselected, 3 xfailed, 1 warning in 55.04s

python -m app.tools.export_contract --check
OpenAPI matches 4b7ade26f590902a4eb131920589184b95e0b54a293e9df80ac9f8aa4859532c

python -m app.tools.check_architecture
Architecture OK: no cross-domain implementation imports

python -m pip check
No broken requirements found.

python -m app.tools.integration_smoke --strict
32 ok, 4 pending, 0 failed; exit 1（未过严格门槛）

python tests/agent/smoke_network.py
exit 1：确认动作返回501，B未实现冻结source参数，期望200的验收未通过。
```

OpenAPI 路径 `backend/contracts/openapi.json`，上述 SHA-256 没有变化。42 deselected 为既有A0历史分类，唯一warning为既有Starlette/httpx弃用提示。真实设备/手机HTTPS/真实供应商未运行；NOTI03没有开启；没有把隔离ports测试等同默认HTTP完成。

## 当前三项 strict xfail 与接手顺序

这三项均由真实路径复现，使用 strict xfail 保留原成功/完整内容断言；修复后 XPASS 会失败，须删除对应标记并重跑。

1. `test_default_change_http_notification_reads_actual_patch_values`：A `0894154` 虽删除提示音，仍仅按类型选录音，内容是“请听取本次修改”，没有实际 medical_notes 等值。默认HTTP回归要求通知文字包含实际值，当前失败。C提供的完整播报准备器尚待A接入，不能宣布该项已修好。
2. `test_actual_b_confirmation_writes_once_and_report_uses_same_record`：B CheckinService 真实签名尚无 source，C运动确认明确501，不允许错标user。
3. `test_medication_new_day_task_ids_remain_valid_after_planning[none]`：同一B缺口阻止真实服药确认；任务ID持久和版本复核仍通过。

A 接手：按完整 body/真实目标快照在事务外调用 C 准备器；ChangeService 在写事务内重验目标、版本和 notice.text，存完整文字；无匹配语音时 audio=null、保持 pending_notice。具体候选接线与签名见 `变更申请/C.md` 首节。不要继续使用按类型的通用录音启动窗口。

B 接手：实现已冻结的关键字 source，校验仅内部 user/agent_confirmed，创建/同餐替换时真实保存来源并保留旧修订来源；HTTP不新增source入参。C已固定传agent_confirmed并核对返回来源。

A/B 合入本分支并修复这两处以后，移除三个 strict xfail、重跑本节所有命令；由 B 验收后开启其 NOTI03，再跑零PENDING严格三轮和真实网络烟测。当前4 PENDING为1项Agent确认来源+3项NOTI03回执。全部历史标签保持原指向，本批不移动或重建基线。

---

# C 历史交接：51dc555 已合入，mock 联调复验通过

日期：2026-10-31（Asia/Shanghai）。状态：**C2_MOCK_INTEGRATION_VERIFIED；整体 P0 尚未全部完成**。

已验证 C 代码提交：`a2d16f1be086d77787381b7549fe3f793a8c5943`。分支 `backend/agent`。本节覆盖下方历史失败/未接线结论；本文件随后单独提交，不回填自身提交。

## 已合入并复验的 A 修复

正常快进合入 `origin/integration/f1` 的 `51dc55517452c094bb169862d1e696f3c683c1fa`，保留双方历史，未重置或强推。A 已完成：

- 默认 create_app 构造 app.state.agent 与 chat/asr/tts 三个 mock provider。
- MemoryService/AgentService/真实B服务使用同一应用Clock与Memory实例。
- Runtime.providers 可正确返回mock，七个C端点登记true。
- CHANGE04已登记，原“实际200但capability=false”的框架失败已消失。
- 已接B的Task/History、冻结list/cancel/calendar/dashboard/presence/query，以及19表/soft-cancel字段。公共变化全部来自A提交，C没有自行编辑公共文件。

## 本轮 C 修复与验收

C测试现使用**默认 create_app**，不再手工替换bundle、Memory或Agent装配。只在明确测试错误路径时注入失败provider/缺失port。

真实跨日用药回归先复现了C自己的问题：TaskPort.today会物化当天目标，只读UoW退出后任务被回滚，规划中的task_id不存在。已在C修复为：需要任务时先在独立短写UoW持久化目标并释放锁，再调用provider；音频先识别成功后再准备对应目标。准备阶段只生成目标，不生成Checkin。模型阶段和确认时重新读取真实计划/任务，版本已变则409、不标动作成功。

新增/强化验证：

- 跨日目标ID持久、确认实际服药只写一次；模型期间或确认前计划变化均409，健康记录仍为零。
- 过滤已取消任务，沿用真实plan slots匹配slot_id，不拆opaque slot_key。
- 真实B取消记录后，C对应规律在同一事务失效；新conversation不再使用旧规律。
- 使用逐字包含完整演示修改的真实中文语音，通过真实A/B ports验证未播报不启动、完整播放后60秒、C明确拒绝以及到期自动应用；无服药记录副作用。
- 新增可重复运行的 `tests/agent/smoke_network.py`：真实默认Uvicorn、127.0.0.1随机端口、新建临时数据库，无装配替身，结束时正常关闭。

## 实际执行结果（backend 工作目录）

环境：Windows / Python3.13.9 / 原requirements.lock / FakeClock与tmp_path；供应商无真实调用。没有触碰运行数据库。

```text
python -m pytest tests/agent -q --tb=short
71 passed, 1 warning in 12.29s

python -m pytest tests -q --tb=short
237 passed, 42 deselected, 1 warning in 51.11s

python -m app.tools.export_contract --check
OpenAPI matches 4b7ade26f590902a4eb131920589184b95e0b54a293e9df80ac9f8aa4859532c

python -m app.tools.check_architecture
Architecture OK: no cross-domain implementation imports

python tests/agent/smoke_network.py
C_NETWORK_SMOKE_OK

python -m app.tools.integration_smoke
24 ok, 7 pending, 0 failed
```

42 deselected是A0明确分类的历史F0阶段测试；唯一warning为既有Starlette/httpx弃用提示，未屏蔽。没有失败测试被删除或放宽。

真实网络烟测包含：健康检查、DEMO/登录、手工建档确认、真实绑定、图片上传、Agent pending→确认→重复确认、真实日报同一记录、跨会话偏好、已绑定子女读记忆、真实音频上传/mock ASR、固定TTS及ticket取回原始语音字节、未知语音文本明确501、模型超时504、CHANGE04本人明确接受。不是仅TestClient验证。

## 写入边界

实际新增/修改仅C白名单：application/agent_flows.py、services/agent_service.py、providers/mock_chat.py、fixtures/agent、tests/agent及C自己的交接/变更申请。目标版本复核只通过冻结ports，无A/B业务表写入捷径。main/composition/core/models/schemas/contracts/依赖/OpenAPI/公共测试未由C修改；OpenAPI保持A的4b7ade…快照。

## 仍未完成且不计为通过

1. 三轮smoke仍有B的7个PENDING：DASH01、PLAN02、TASK01、REC02、NOTI02、REC01、REPORT01。相关服务可被C工具调用，不代表其HTTP能力均已启用。严格零PENDING验收尚未通过。
2. **A当前CHANGE01 HTTP音频仍为0.8秒双音提示，未播报实际修改内容。** 本轮完整播放窗口测试用C新增的真实 `proposal_change_example.wav`，直接经共享GeneratedAudio/ChangePort提供完整固定文本语音；这不等于A的HTTP生产路径已经替换提示音。请A处理，具体代码位置与建议见变更申请/C.md。不能把该提示音视作用户完整听取修改后的自动应用证据。
3. B的冻结CheckinPort仍没有Agent来源参数，真实记录source仍为user；C没有直接改B表冒充agent_confirmed。Action.result可追溯实际记录，来源字段统一仍交A/B。
4. 真实供应商、手机HTTPS/真实播放器、任意文本TTS、自动规律整理等未在本轮发布或验收。五段固定中文语音只对应各自完整文本，无匹配时明确降级/501，不用音调或不匹配录音代替。

完整当前申请在 `docs/协作/变更申请/C.md` 的“最新复验”段。A可正常合入本分支后重跑上述命令；公共文件与B能力启用继续由A/B负责。下方保留此前阶段历史，不代表当前仍缺接线或CHANGE04仍失败。

---


# C 历史交接：51dc555 合入前的集成状态

2026-10-31（Asia/Shanghai）。状态：**C2_IMPLEMENTED_PENDING_SHARED_FIXES / INTEGRATION_NOT_READY**。

当前已验证提交：`0e9101a84479e5b012d764cebe454e0854f18d0f`；C2主体代码提交 `8fe7174c3ed48ce514c2d21f0bdddec6728cf474`。分支 `backend/agent`。本节覆盖后面的阶段性历史结果。

本轮继续正常合入了 A 发布的 `integration/f1` = `21f9bff`，合并提交 `38bc09cde04567128ee97c48c23fa1b73f9dc9b9`。因此当前已包含真实 B 的服务，不再沿用“B全部是桩”的结论。

## 最新实际结果

- `python -m pytest tests/agent -q`：**63 passed, 1 warning in 9.48s**。含45个C1原语与18个C2 HTTP计数。
- `python -m pytest tests -q --tb=short`：**1 failed, 220 passed, 42 deselected, 1 warning in 41.47s**。不能宣称全量绿。
- 唯一失败：`test_every_p0_route_matches_its_capability[CHANGE04]`；真实C来源失效可用后，A接受提案已返回200，但A能力仍为false，框架严格要求501。C保留公共测试与A能力文件，待A按真实状态修正登记/门禁。
- `python -m app.tools.export_contract --check`：通过；hash为 `6a2de0894ef6de2094799d9e3c1d4cef884d317cc62c336c98f535dd1527720d`。
- `python -m app.tools.check_architecture`：通过。
- `python -m app.tools.integration_smoke`：**20 ok / 9 pending / 0 failed**，PENDING不是业务通过。

测试均为临时SQLite、FakeClock、锁定依赖。唯一warning为原有Starlette/httpx弃用提示。C2 HTTP环境使用明确依赖注入；默认部署没有偷偷组装C服务或启用能力。

## 新增真实跨域验证

已用真实 A/B/C 服务完成：C mock运动规划→健康表仍零条→确认动作→B真实写入一条打卡→重复确认仍一条→B真实日报包含相同checkin_id，运动完成数为1。没有直接改B表代替写port。

当前冻结B port没有Agent来源参数，实际返回的记录source仍为user。C未直接改表冒充agent_confirmed，该来源标记差异仍是A/B共享契约缺口，不能宣称该项业务验收已完成。缺失B的回滚测试已改成明确注入的测试替身；正常实际B服务不再被当占位。

A在integration/f1已修复原notification.id/notification_id差异，此问题不再阻塞；C默认部署的7个HTTP入口仍因缺少A-owned装配而明确501/capability=false，等待接线。

## A 的剩余操作

用户明确要求公共文件由A修改。C的实际功能/测试修改只在白名单；共享变化均来自A已发布的正常merge。准确候选代码和最新失败已写入 `docs/协作/变更申请/C.md`：

1. composition复用已有access/media/B实例，仅将现有MemoryService改为传同一个clock/access，并构造AgentService与三个mock provider。
2. main连接app.state.agent/agent_chat/agent_asr/agent_tts。
3. Runtime.providers允许mock，重导出并审核仅此枚举的OpenAPI变化。
4. 同次集成启用C2_OPERATIONS及真实mock PROVIDERS；C已在申请中明确授权集成人一次性激活该C注册文件。
5. 修正CHANGE04能力与实际接受路径的不一致，重新跑全量；不要放宽框架断言或让C记忆服务故意抛501。

TaskPort/HistoryPort仍接A0占位实例，B对应原语已存在；其接线及其他健康能力仍由A/B处理。自动规律的当前证据读取、来源标记、手机/真实供应商和零PENDING三轮业务验收仍未完成。

以下为此前C2/C1历史记录，保留签名与流程说明；以本节的最新测试和未就绪状态为准。

---


# C2 前一批历史交接：尚未合入 integration/f1

日期：2026-10-31（Asia/Shanghai）。状态：**C2_IMPLEMENTED_PENDING_A_ASSEMBLY**。本批代码提交 `8fe7174c3ed48ce514c2d21f0bdddec6728cf474`；分支 `backend/agent`。本记录之后单独提交，不回填自身 commit。

已正常 merge `f1-shared-v1`（A0）与 `origin/backend/platform` 的 `72d7610ba398588f0201b1bdde9a7344e999804e`（A1/A2及联调脚本），无冲突且保留 C1 历史。**用户明确指定公共文件交 A 修改**，因此本批只改 C 白名单；composition/main/schema/OpenAPI 未由 C 修改。

## 本批完成与真实运行状态

- 已实现 AI01/02、AGENT01/02、MEM01–03 的 C 路由和 application flow。
- HTTP 测试明确注入与目标装配一致的 AgentService、同一个 Clock/MemoryService 和纯 mock providers，使用真实 A 登录、ProfilePort、BindingPort、MediaPort、提案查询/决策。没有把测试注入装到正常运行路径。
- 默认 create_app 仍未提供 `app.state.agent/agent_chat/agent_asr/agent_tts`。C 的 `_ready` 在真实身份/资源检查后明确返回 `501 MODULE_NOT_IMPLEMENTED`，避免缺属性500。C 的 CAPABILITIES 仍为空、PROVIDERS 仍为 not_implemented，与部署状态一致。
- C-owned `agent_capabilities.py` 已列出通过实现测试的 `C2_OPERATIONS`，**不是已启用的能力清单**。A 完成接线及 Runtime schema 修正后，在同一次集成中启用注册并复验；具体代码见 `docs/协作/变更申请/C.md` 的 C2 段落。

## C2 流程与验证事实

1. 使用 A0 Auth 先做短读鉴权，释放 Session；ASR、chat、TTS 和媒体内容字节读取均在事务外。
2. 重新开启短写 UoW，重新验证实际会话、本人权限、关联通知、档案与记忆版本；成功业务、动作/轮次/记忆与幂等结果在一次提交里保存。Provider 期间的独立写连接已实测可提交。
3. client_turn_id 重放跳过 provider；同 key 异体409，失败不缓存。档案动作经真实 A 更新一次，重复 HTTP 确认不再增加版本。用户下一轮“确认”也可执行唯一/指定的同一动作。
4. C 的确认执行器支持现有冻结 ports 的打卡、档案、计划、绑定码、日报、提案决策、普通提醒处理。B 仍501时如实回滚，动作保留 pending；取消不需要 B。未把 B 的缺口转成假成功。
5. 关联通知由 A0 共享资源 guard 在读/写阶段检查；proposal_id 通过真实 A 的分页查询按 notification_id 关联查出，不把两个 ID 当同一个。测试验证已有提案被真实 A 状态机拒绝、目标档案不变、auto_apply_at 仍为空；只用明确 B 关闭通知测试替身。
6. 模型工具只能处理 snoozed/handled/dismissed，不允许制造 displayed/answered/playback_completed；播放不记录 taken。
7. 音频先通过真实 A MediaPort 验权和取受控句柄；生成语音交 A register_generated，再用 ticket 内容地址实际取回完整 WAV 字节。text+audio 时 text 是已校正转写，不重复 ASR。
8. TTS 只有完整文本一致的四个真实固定中文语音；新增“您好”及其可复现生成脚本/哈希。未知文本501，Agent保留文字并标 tts_unavailable；没有静音、音调或不匹配语音冒充内容。
9. Memory HTTP 支持本人修正/删除、版本冲突与幂等；绑定子女只读。修正/删除后新会话读取新上下文，保留来源/修订与旧候选抑制。

## C 白名单文件

- application/agent_flows.py、routers/agent.py
- services/agent_service.py、services/agent_capabilities.py
- providers/planning.py、providers/mock_chat.py
- fixtures/agent（新增 greeting.wav、更新清单/脚本/说明）
- tests/agent/test_http.py（新增17个实际HTTP测试计数，含参数化）
- docs/协作/变更申请/C.md 与本记录

其他共享文件仅来自 A 的正常 merge。本批未改依赖、前端或其他领域实现，也未新建第二套 DTO/鉴权/数据库。

## 实际验证

backend 工作目录，Windows / Python 3.13.9 / 原 requirements.lock / 独立临时 SQLite / 同一 FakeClock：

```text
python -m pytest tests -q
171 passed, 42 deselected, 1 warning in 34.62s

python -m pytest tests/agent -q
62 passed, 1 warning in 9.26s

python -m app.tools.export_contract --check
OpenAPI matches 6a2de0894ef6de2094799d9e3c1d4cef884d317cc62c336c98f535dd1527720d

python -m app.tools.check_architecture
Architecture OK: no cross-domain implementation imports

python -m app.tools.integration_smoke
19 ok, 9 pending, 0 failed
```

全量171含 A/框架109与 C62。62项 C 测试包括 C1 45 + C2 HTTP 17。补充问候语音后 C62再通过。42 deselected 是 A0 分类的历史 F0 snapshot；唯一 warning 是既有 Starlette/httpx 弃用提示，未屏蔽。

正常未接线部署的 smoke 中 C 相关步骤仍为 PENDING，明确报告“C2 awaits A-owned composition wiring”；不把 PENDING 算成功。HTTP业务验证使用 TestClient 和明确装配测试环境，本轮没有启动持久 uvicorn 服务或进行手机播放测试。

## A 需要完成的最小接手

完整代码块在 `docs/协作/变更申请/C.md`。核心是：

- composition 用 `MemoryService(clock, access)`，并构造 `AgentService(clock, services, services.memory)` 与 MockUnderstanding/MockASR/MockTTS。
- main 设置 `app.state.agent` 及 `agent_chat/agent_asr/agent_tts`。
- Runtime.providers 当前只接受 not_implemented；允许 mock 并真实重导出 OpenAPI，否则设置真实 provider 状态会500。
- 在同一个集成提交启用 C2_OPERATIONS 和 mock PROVIDERS，避免代码、能力、schema 分批不一致。C 已在变更申请中明确授权集成人进行这次 C 注册激活。
- 先跑 tests/agent、全量 tests、契约/架构工具，再跑 integration_smoke；B未就绪的 PENDING 应继续如实保留。

额外具体缺口已记录：A ChangeService.create 使用 notification.id，而冻结 Notification DTO 是 notification_id；B Task/计划/通知/打卡来源和规律证据读取仍需各自完成。本批没有借测试替身宣称这些跨三域闭环已完成。

**未运行/未完成**：A-owned 装配与 Runtime schema 修改、默认部署 C 能力激活、B真实写入/通知/历史全链路、自动规律证据读取、真实供应商、手机HTTPS/播放器、严格零PENDING三轮集成。以下保留 C1 历史记录，当前状态以上方 C2 为准。

---


# C1 历史交接：小安、mock 与长期记忆

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
