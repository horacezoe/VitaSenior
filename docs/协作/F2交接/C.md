# F2 C：真实多意图对话与澄清工作流

## 2026-11-01：日常对话内部优化（覆盖下文历史确认口径）

用户最新授权：信息足够就完成日常记录，减少餐次追问和重复确认；用小孩形象的数字人陪老人聊健康生活，并在系统提示词头部加入当前对话时间。另明确要求所有后端接口保持不变。

- **接口冻结**：未修改 routers、公共 schemas/enums、models、contracts、core、composition/main、依赖或 OpenAPI。只调整 providers 的私有模型/提示词及 AgentService 内部执行策略，继续沿用 typed ports、原事务与幂等入口。
- **餐次推断**：用户说明优先，其次当前这餐已知信息，再按服务端 UTC+8 时间推断：05:00–10:59 早餐、11:00–16:59 午餐、其他晚餐。多轮补充跨过分界时保留首轮餐次和发生时间，用户更正优先。模型自行给出的冲突餐次不覆盖用户说明。
- **少问、顺手记**：真实饮食/已完成运动在必要事实齐全后直接执行现有 CheckinPort，动作 `confirmed`、来源 `agent_confirmed` 沿用原协议；本人的生活报告承担这次记录的表达。只有用户要求先核对时等待确认，支持“好呀、对、就这样”。模糊图片、没有说出的运动时长、尚未完成的行为不虚构。用药和档案修改仍保留必要核对。
- **上下文续接**：原先只转发最近六轮中的 chat/ingredient，现改为最近八轮内的日常交流、饮食、运动及澄清文字，仍按 actor + elder + conversation 隔离并限制长度。保留未完成任务及已知食物/餐次/时长，短暂闲聊不丢失草稿；取消、换话题、过期按真实状态处理。
- **保存后补充/更正**：现有 `request_json['_workflow']` 内保存最近一次日常记录结果，十分钟内可通过明确补充/更正续接。调用既有 CheckinUpdate + CheckinPort 更新同一记录，保留原 ID/时间并校验版本；重试不重复建记录，外部修改或取消导致的冲突不被覆盖。不新增表、迁移或公共字段。
- **提示词与话术**：逐轮注入真实当地时间；角色为“小银龄，一个小孩形象的数字人”。短句、生活化、尊重老人；不对用户说“候选、草稿、业务”等术语，也不为了流程重复要求明确确认。饮食/运动完成回复由服务端根据真正执行的计划形成，失败事务不会返回保存成功。

新回归文件：`backend/tests/agent/test_daily_dialogue_completion.py`；既有 pending 专项明确使用“先让我核对再保存”，同时保留真实工厂默认直接完成、ASR+截图确认、幂等、跨会话隔离、失败回滚与 TTS 降级验证。手动付费探测脚本同步适配可选核对路径，本轮不运行付费请求。

实际验证（当前 worktree 的 backend 目录，D 盘既有 Python 3.13.9 虚拟环境）：

```text
python -m pytest tests -q --tb=short --maxfail=1 --basetemp=.pytest_cache/daily-dialogue-final-05
606 passed, 42 deselected, 1 warning in 97.45s
python -m app.tools.export_contract --check
python -m app.tools.check_architecture
```

42 项为已有 F0 阶段筛选，1 项为已有 Starlette/httpx 弃用警告。最初全量运行 601 passed / 2 failed，失败是两项仍固定要求 pending 的旧场景；真实工厂场景改为验证默认直接完成，音频确认专项改为用户主动要求先核对，随后定向 38 项通过并完成上述全量复验。OpenAPI 与仓库原契约一致，SHA-256 为 `6c1e8d96bfe881605d5d7ffd99a4da93b52d0682c01dbda4be9f9629d8e7f500`。全部供应商调用为测试替身；未做真实模型、摄像头/麦克风和音色听感验收。修改未提交。

以下为历史交付记录，其“必须先说出餐次”“所有日常写入都先 pending”等口径已被本节和最新用户要求覆盖。

2026-10-31（Asia/Hong_Kong）。从指定 `363f6376a63d696ba36b1bc7fc426e8b159dc196` 开始，分支 `backend/f2-understanding`。独立 worktree：`C:/Users/horac/Documents/ChatGPT/hackthon Su2026/VitaSenior-f2-understanding`；F1 的 D 盘工作区/数据未改。开工13:56，主链目标16:56，功能截止17:56。

当前已正常快进合入 **`f2-demo-v4@582e304ef62c831ba7d825654d159b5dfa0ce19f`** 与 B 的 `ad4325a`。用户要求补真实多意图工作流及剩余mock；公共文件仍由A维护。最新交付见本节，以下v2/Flash/受限饮食口径均是历史，不代表当前能力边界。既有发布标签不移动。

## 最新：真实对话闭环补齐

状态：**C_DIALOGUE_VERIFIED / READY_FOR_A_INTEGRATION**；剩余公共mock接线仍待A/B，不能宣称完整通话产品已验收。

两项缺口先离线复现：带截图的“确认。”返回空动作；照片后答“午餐”丢失原image_asset_ids。新增回归最初为2 failed；修复后新增33项会话回归已通过，最终全量 **560 passed / 42 deselected / 1既有弃用warning（91.00s）**。严格联调 **39 OK / 0 pending / 0 failed**，默认mock TCP为 **C_NETWORK_SMOKE_OK**；OpenAPI、架构检查通过。

最终实际命令（backend目录，Python为D盘既有venv3.13.9；全部测试使用独立临时数据库）：

```text
python -m pytest tests -q --tb=short -rx --maxfail=2 --basetemp=.pytest_cache/c-dialogue-final
python -m app.tools.export_contract --check
python -m app.tools.check_architecture
python -m app.tools.integration_smoke --strict
python tests/agent/smoke_network.py
```

OpenAPI仍为 `backend/contracts/openapi.json`，SHA-256 **`4b7ade26f590902a4eb131920589184b95e0b54a293e9df80ac9f8aa4859532c`**。42 deselected是既定历史F0分类；无失败/xfail/新跳过。初始新测试曾缺api fixture导入，修复后才记录上述2项真实业务失败，不把fixture错误算作业务复现。其后先通过555项，再扩展控制语法及提案来源校验，最终560项通过。本次未独立重跑pip/demo_walkthrough或真机检查。

本轮手改均在C范围：`providers/dialogue.py`、`planning.py`、`real_understanding.py`、`mock_chat.py`、`proposal_notice.py`、`application/agent_flows.py`、`services/agent_service.py`、`tests/agent/test_dialogue_workflow.py`、既有2个C回归、`probe_real_dialogue.py`、`.env.mimo.example`及C交接/变更申请。A的core/models/schemas/contracts/composition/main、依赖与B音频实现未手改。

### 控制与会话状态

- 控制优先于新图/新意图：标点、空白、常见ASR礼貌前缀归一化；“确认。/请帮我确认这条记录。”“取消。”带合法截图仍控制当前动作。问句或否定句不当确认。素材/会话/动作的真实权限检查仍先执行；不跳过陌生截图鉴权。
- 确认/取消复用 `AgentService.decide`，已取消/过期/已确认冲突沿原错误和幂等规则；多个待处理动作须明确指定。更正餐次/食物/运动草稿时旧pending取消与新pending/草稿在同一UoW，必须再次明确确认，不修改既成健康事实。用药目标/剂量不能靠会话更正偷换。
- C私有 `ConversationDraft` 保存在已有 `AgentTurn.request_json['_workflow']`，原请求仍逐字段校验幂等；不新增表/迁移/公共DTO。按actor+elder+conversation隔离，用户补充必须携带返回的conversation_id；服务端在收到pending_action_id时解析其真实会话。没有会话信息不复活其他会话草稿。
- 草稿含服务器确定的原occurred_at/10分钟expires_at、授权媒体引用和已校验候选；“午餐”“二十分钟”等可不再调用模型。原媒体在短读与最终写重新验权。切换任务/取消清空草稿；过期不延寿、不拿新截图替换旧候选。SQLite行插入次序取得最新轮次，FakeClock同一时间戳也能稳定续接；最终写核对conversation_revision，防止慢模型覆盖并发新回合。
- 普通交流仅附带同actor/老人/会话最近6轮内的chat/ingredient文字，截取用户1000字/回复400字；不向供应商发送动作结果、绑定码、媒体票据、档案或长期记忆。草稿续接只发已授权短期候选，无身份/权限/时间字段。

### 已开放的真实意图与事务约定

- 文字/图片饮食候选、运动种类/时长澄清→pending→确认→真实CheckinPort，source=agent_confirmed。原图保留，未确认不写事实。
- 明确的今日/昨日日报命令走ReportPort；绑定码走BindingPort；称呼修改使用当前Profile版本并待确认；明确偏好写MemoryService，查询偏好/有效规律读取真实长期记忆。普通陪伴聊天与食材建议走MiMo，返回真实文本，无附带健康动作。
- 通知稍后/处理及修改提案接受/拒绝复用实际通知/提案port和鉴权上下文，不生成播放回执。
- 用药另加严格回归：只查实际当日、已到时、未取消/未完成、非等待餐后的既有任务，服务器从实际计划解析slot_id；多药/多时段追问，不自行选。保存用药澄清后可按具体药名/早上等时段续接；计划version在准备与确认前复核，变化拒绝且动作/健康写入回滚。新增或改变用药方案仍使用已有专用页面/API。
- `Snapshot`/`Plan`新增均为C私有类型；`read_snapshot(tx, actor, request, *, profile=None, tasks=(), medication_slots=None)`、`record_turn(..., speech=None, tts_provider=None)`与`decide(tx, actor, action_id, ActionDecision)`签名不变。调用方UoW负责提交。ASR/模型/TTS在事务外；会物化目标的日报/用药读取用单独短写UoW提交稳定ID，目标不是打卡事实。
- C提案全文准备器已支持实际tts来源与全文标记，拒绝mock音频伪装real；A仍须替换`create_change`硬编码fixture。具体最小接线、验收条件和看板mock字段见 `docs/协作/变更申请/C.md`。

### 配置与真实网络证据

C本机被忽略的.env已设chat/asr/tts=real，沿用自己的MiMo key、DATA_DIR和端口；没有启动或改动运行数据库。正常Settings/工厂三个实际对象均real/is_mock=False，输出 `C_LOCAL_REAL_FACTORY_OK`。空key示例新增ASR/TTS字段，同事自行填key并加载进程环境。

真实TCP探针采用正常app.main:app/A工厂、隐藏临时Uvicorn与临时SQLite，无provider/service注入。实际已依次得到：

```text
REAL_PHOTO_CLARIFICATION_OK
REAL_DRAFT_RESTART_AND_MEAL_SLOT_OK
REAL_ASR_CAMERA_CONFIRM_TTS_AND_CHILD_HISTORY_OK
REAL_COMPANION_CHAT_AND_TTS_OK
C_REAL_DIALOGUE_OK
```

照片先触发餐次追问；重启后只答“午餐。”并附截图保留原候选；AI02实际生成“确认。”WAV并取回RIFF字节，再经真实ASR+截图确认，只写一条agent_confirmed，重试不重复，子女看板/日报回看同一记录；普通陪伴聊天+TTS正常。此探针最多8次显式供应商调用，无自动重试；未保存key/token/票据。真实探测后只扩展了纯服务端控制语法和提案来源校验，未重复计费。

```text
python tests/agent/probe_real_dialogue.py --env-file .env --live --chat --image data/c-f2-probe-assets/unsplash-meal.jpg
```

尚未宣称完整产品完成：提案真实TTS公共接线、看板来源schema固定mock、新关怀文字动态TTS由A/B收口；生成绑定码等执行后动态全文在缺音频时需前端调用AI02补播最终reply.text。预设关怀/历史demo_seed继续如实标识。短信仍为demo code，MiMo key不提供短信服务。Edge真麦克风PCM WAV、手机HTTPS/实听/真实播放器回执未验；本次ASR用明确合成的确认WAV，不冒充现场采音。

## 以下为历史验证记录

## 用户追加：轻量 Chat 调用（2026-10-31）

用户要求将chat改用更轻量模型。本机实际 `CHAT_MODEL` 已为 `mimo-v2.6-flash`；使用该key实际查询官方 `/v1/models` 返回200，可用chat型号为 `mimo-v2.6-flash / mimo-v2.6-pro / mimo-v2.6-pro-ultraspeed`，没有更小的可用chat型号。因此保留轻量Flash型号，改为显式发送 `thinking={"type":"disabled"}`。官方[模型说明](https://mimo.mi.com/models/en-US/mimo-v2.6-flash)将Flash定位为低成本高频调用档；[深度思考说明](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/other/deep-thinking)确认其默认开启思考、可以关闭。本轮落实为Flash非思考模式，没有声称更换了一个更小型号。

- C的 `providers/real_understanding.py` 仅对官方 `api.xiaomimimo.com` 添加非思考参数，其他兼容endpoint保持原请求格式。构造签名、配置字段、路由与确认规则不变；A公共文件未改。
- `tests/agent/test_real_understanding.py` 增加文字/图片非思考请求与待确认动作回归，并检查其他供应商请求不附带MiMo参数。`.env.mimo.example` 更新说明，key仍为空；用户本机.env及其key未修改、未上传。
- 全量 **368 passed / 42 deselected / 1既有弃用warning（74.83s）**；OpenAPI校验及架构检查通过。OpenAPI SHA-256仍为 `4b7ade26f590902a4eb131920589184b95e0b54a293e9df80ac9f8aa4859532c`。
- 正常工厂、临时Uvicorn与临时SQLite实际网络联调为 **C_MIMO_NETWORK_OK**。文字与图片各一次供应商请求，完整链路分别 **19991ms / 7363ms**；均经pending、确认、幂等重放和子女端同记录校验，real重启持久化、无key显式mock重启均通过。耗时包括多次本地业务请求，并非纯模型延迟；与历史单次采样不能构成稳定提速结论，供应商响应仍有波动。

本轮实际执行（backend目录、D盘既有venv）：

```text
python -m pytest tests -q --tb=short -rx --maxfail=1 --basetemp=.pytest_cache/c-f2-light-chat-all
python -m app.tools.export_contract --check
python -m app.tools.check_architecture
python tests/agent/smoke_mimo_network.py --env-file .env --live --image data/c-f2-probe-assets/unsplash-meal.jpg
```

A接手时正常合入 `backend/f2-understanding` 并重启服务即可；保持 `CHAT_PROVIDER=real / CHAT_MODEL=mimo-v2.6-flash`，沿用各自本机key。无新增公共配置或数据库迁移。本次未重跑独立strict/demo_walkthrough/pip检查，下文统一基线的既有结果是历史证据；没有操作运行数据库。

## 统一基线跟进（f2-demo-v2）

在A统一提交上独立执行：全量 **366 passed / 42 deselected / 无失败或xfail（73.33s）**；严格三轮 **39/0/0**；`demo_walkthrough` 为 **WALKTHROUGH_OK**；默认mock网络 **C_NETWORK_SMOKE_OK**；OpenAPI/架构/依赖检查均通过。唯一warning仍为既有Starlette/httpx弃用提示。

```text
python -m pytest tests -q --tb=short -rx --maxfail=1 --basetemp=.pytest_cache/c-f2-v2-all
python -m app.tools.demo_walkthrough
```

其余命令同下节。本轮未重复供应商计费调用：真实MiMo正常网络证据见下节，相关实现与工厂未变。新增 `run-demo.ps1` 已审阅；A交接有其实际启动/真实请求记录，C本轮未运行该启动器（C工作树无本地backend/.venv，复验使用D盘既有venv）。在此工作树使用启动器前，按README准备本地.venv；不修改脚本或运行数据库来绕过环境条件。

## 已交付与入口

- `providers/real_understanding.py::RealUnderstanding`，沿用 `UnderstandingProvider.plan(request, snapshot) -> Plan`。单个显式配置的Chat Completions接口，无SDK/新依赖/重试/自动mock回退；连接5秒、供应商总期限20秒（含持续接收响应），响应128KiB上限。默认单元测试全为HTTP替身，不请求付费API。
- 只接收严格的饮食候选JSON。模型不能填写老人/日期/ID/版本/权限/动作或记忆；服务器用当前上下文构建现有DietAction，全部待确认，source沿原确认入口agent_confirmed。明确餐次缺失/歧义追问；非饮食或历史日期引导已有页面/API，不准备服药任务。真实模式拒绝mock_fixture_id。
- `planning.ImageInput` 是已授权字节，不含路径/票据。flow短鉴权获取MediaPort句柄，事务外读取并发送Base64；每图5MiB、合计10MiB、最多沿原schema的3图。最终写入重新验真实会话、资源、档案和记忆版本。只向供应商发本轮用户文字/图片，不发档案、记忆或家庭身份。
- `Plan.chat_provider`、Agent/AI02/ASR来源不再写死mock；TTS失败保留真实文字/tts_unavailable。45秒Agent预算不足时不启动新的20秒真实TTS；截止后不提交成功结果。最终查询/绑定/确认回复若变化仍走既有AI02补播，不重复执行工具。

适配器签名（现已由A正常工厂构造；业务入口无需手动注入）：

```python
from app.providers.real_understanding import RealUnderstanding
chat = RealUnderstanding(
    api_key=settings.chat_api_key,
    base_url=settings.chat_base_url,  # HTTPS API root, e.g. .../v1
    model=settings.chat_model,
)
# .name == "real", .is_mock == False
```

A已提供 `CHAT_API_KEY / CHAT_BASE_URL / CHAT_MODEL` 和CHAT_PROVIDER=mock|real；真实缺字段启动明确失败，默认无key全mock，ASR/TTS保持本轮mock。C的flow/Plan/AgentService来源改动继续复用，不改OpenAPI。

## 已合入的 A 接线与本轮改动

正常快进合入 `origin/f2/platform@ad05258dfe84dd1f008841caf976a85710eedb82`。A已放开Settings、构造RealUnderstanding、更新Runtime与公共测试；本轮C未自行编辑core/composition/main/models/schemas/contracts/依赖或公共测试。C原应用实现 `fa245e2` 保留；旧“只允许真实TTS、chat未接线”结论已关闭。

本轮C仅新增 `tests/agent/test_f2_configured_startup.py`（5项）和 `tests/agent/smoke_mimo_network.py`，更新C自己的空密钥示例说明与本交接。前者以真实A工厂验证实际实例/Runtime、缺3项配置拒启、无key mock重启；只有HTTP传输使用显式替身。后者无provider/service注入，以正常应用入口做实际TCP网络验证，测试关闭入口只存在于临时进程、未改应用源码或OpenAPI。

## 验证与真实探测

2026-10-31（Asia/Hong_Kong），MiMo官方API `https://api.xiaomimimo.com/v1`，请求模型 `mimo-v2.6-flash`：

- 正常配置启动：Runtime为 `chat=real / asr=mock / tts=mock`；真实模式缺key时正常应用导入明确拒绝，输出 `MISSING_KEY_STARTUP_REJECTED`。
- 文字“今天早餐吃了鸡蛋和全麦面包，请准备记录”：正常HTTP全链路 **13530ms**。
- 餐食JPEG（800×533、127927字节）经真实授权媒体上传、Base64输入：正常HTTP全链路 **13157ms**。公开[演示图片来源](https://images.unsplash.com/photo-1512621776951-a57141f2eefd?w=800&q=85)；SHA-256 `c048bf36cfa7810c2eb25b93267fef6588d80d5f66dc305d70afe42c6a48aa7f`。图片只在被忽略的data目录，不上传Git。
- 同一个临时SQLite：DEMO→真实登录→手工建档→绑定→文字/图片pending→确认，各一条source=agent_confirmed记录；pending不落记录，重试/重复确认不新增；绑定子女看板/日报核对同一checkin，绑定前访问被403拒绝。耗时包含确认/重放和看板/日报，并非纯供应商延迟。本轮仅2次实际模型请求，没有供应商重试或静默mock回退。
- 停止进程后用同一临时DATA_DIR重启real服务：原会话有效、两条记录保持、原轮次重放一致，`REAL_RESTART_PERSISTENCE_OK`。再移除key/base/model并显式mock重启：Runtime全mock、可生成明确mock待确认动作、原记录保持，`EXPLICIT_NO_KEY_MOCK_FALLBACK_OK`。
- 最终 `C_MIMO_NETWORK_OK`，退出0；临时服务均已退出、数据库清理，没有操作F1或运行数据库。此前隔离探测的3.8s/11.8s保留为历史，本轮证据已由正常工厂网络验证替代。

已运行（Python3.13.9，D盘既有venv；pytest临时SQLite、时间推进测试使用FakeClock，真实网络用系统时钟）：C **162 passed（25.41s）**；全量 **366 passed / 42 deselected（70.43s）**，无失败/xfail；严格三轮 **39 OK / 0 PENDING / 0 FAIL**；默认mock网络 `C_NETWORK_SMOKE_OK`，正常real工厂网络 `C_MIMO_NETWORK_OK`。契约/架构/依赖检查通过，`backend/contracts/openapi.json` SHA-256仍为 `4b7ade26f590902a4eb131920589184b95e0b54a293e9df80ac9f8aa4859532c`。42 deselected为原A0历史F0分类；唯一warning为既有Starlette/httpx弃用提示。

```text
python -m pytest tests/agent -q --tb=short --maxfail=1 --basetemp=.pytest_cache/c-f2-configured-agent
python -m pytest tests -q --tb=short -rx --maxfail=1 --basetemp=.pytest_cache/c-f2-configured-all
python -m app.tools.integration_smoke --strict
python tests/agent/smoke_network.py
python -m app.tools.export_contract --check
python -m app.tools.check_architecture
python -m pip check
python tests/agent/smoke_mimo_network.py --env-file .env --live --image data/c-f2-probe-assets/unsplash-meal.jpg
```

本机沙箱默认临时目录不可写且异步事件循环曾停滞；已停止自己的停滞pytest，改为正常Windows执行环境与上述工作区内basetemp。该环境失败不计业务失败或通过，不放宽测试。

同事自行填写本机key后可显式复验正常配置网络；只做文字/图片各一次供应商请求，重启重放不新增模型请求：

```powershell
# 将 .env.mimo.example 复制为被Git忽略的 .env，并在本机填写 CHAT_API_KEY
# 仅这个探测命令显式读取文件；正常应用仍不会自动加载.env
python tests/agent/smoke_mimo_network.py --env-file .env --live --image <演示餐食照片路径>
```

该命令显式读取CHAT_*与LIVE_UNDERSTANDING，再通过进程环境启动正常应用，**无适配器注入**；忽略.env中的数据库地址，始终使用新临时目录。无 --live/LIVE_UNDERSTANDING=1 不请求供应商，不打印密钥/token/票据。验收脚本自动停止临时服务；长期演示服务按A启动说明显式设置环境，应用仍不自动加载.env。旧 `probe_real_diet.py` 只留作隔离调试，不再作为正常启动门槛证据。

协议参考官方[图片输入](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/multimodal-understanding/image-understanding)和[JSON输出](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/text-generation/structured-output)。本机账号的文字/图片已实测通过；同事账号仍需自行验证权限，不把文档或替身测试视为其账号已可用。

仍未验收：真实音频、手机实听/HTTPS、前端设备演练及完整产品AC01–AC14。当前真实自然语言只保证饮食；其他原业务API保持可用。图片需明确“今天午餐”等餐次，不从菜品猜餐别。A已完成代码整合，无需等待C新增功能。A的前端接入资料仍有“所有AI都是mock”，自身交接保留“TTS-only”和“C照片仅隔离探测”旧段，应由A统一成chat可real且C正常网络照片已验、ASR/TTS仍mock的事实；这些是文档清理项，不是当前代码阻断。本次只补C核验记录，沿用A的f2-demo-v2，不移动/重建任何标签。
