# F2 B：MiMo TTS 握手与验收

2026-10-31（Asia/Hong_Kong）。**B 已正常快进合入 C `dfb41df`，复验多意图对话与音频装配通过；此前“真实理解仅支持饮食”的缺口已由 C 补齐。仍待 A 的提案真实 TTS、看板来源字段和新关怀文字动态 TTS 接线，以及正式前端设备验收。** TTS 已有用户对单个证据文件的实听确认，ASR 已有 B 独立 WAV 与 A/C 正常网络探测；Edge 真麦克风实际采集尚未验收。三个模态统一 MiMo，无新增转码或依赖。下节为最新状态，优先于后文历史交付口径。

## 最新：同步 C 多意图工作流与 B 音频复验

- 正常 fetch A/C 后，A 仍为 `origin/f2/platform@582e304`，C 为用户发布的 `origin/backend/f2-understanding@dfb41df`。C 已包含 B `ad4325a`，因此 B 用 `merge --ff-only` 快进成功，无冲突、无重写历史。本轮未修改 C 的业务实现或 A 共享文件。
- 已阅读 C 最新交接及 `变更申请/C.md`，核对确认/取消/更正、ASR 标点及附带截图、澄清草稿恢复/过期/切换/并发、真实聊天/饮食/运动/日报/绑定/偏好和核对既有到时任务的用药确认；旧的受限饮食描述仅属历史。A 的公共接线仍未发布新提交。
- B 独立实际运行 `python -X utf8 -m pytest tests/agent/test_dialogue_workflow.py tests/providers/test_real_audio.py tests/agent/test_f2_configured_startup.py tests/agent/test_proposal_notice.py tests/agent/test_f2_http.py -q --tb=short --basetemp=.pytest_cache/b-c-dialogue-audio-review` → **231 passed / 1 既有 warning / 43.09s**。使用原依赖、临时 SQLite 和 HTTP 替身，未付费调用。
- 在 B 白名单 `tests/providers/test_real_audio.py` 新增一条集成回归：正常 Settings/工厂构建三项 real，仅设置各自 HTTP transport；48 kHz/16-bit PCM WAV 上传后经实际 MiMoASR 解析“确认。”，携带已授权截图进入 C 对话，确认只写一条 agent_confirmed，原请求重放既不重复供应商调用也不重复健康事实，子女日报读到同一记录，AI02 为执行后的最终 reply.text 生成音频并由 MEDIA03 返回完整 WAV。所有三类 HTTP 等待期间独立写 UoW 均可提交。此 WAV 为诊断测试数据，不是真麦克风、真实合成或人工实听证据。
- 新测试首次因测试代码误用 ORM 字段 `record.checkin_id` 失败，改为现有 `record.id` 后实际运行 `python -X utf8 -m pytest tests/providers/test_real_audio.py -q --tb=short --basetemp=.pytest_cache/b-audio-dialogue-final` → **160 passed / 1 既有 warning / 10.27s**。未据该测试错误改业务实现。
- `python -X utf8 -m app.tools.export_contract --check` → 匹配 `4b7ade26f590902a4eb131920589184b95e0b54a293e9df80ac9f8aa4859532c`；`python -X utf8 -m app.tools.check_architecture` → Architecture OK。未重复全量 560 项、strict 或供应商真实请求；C 报告的 560 passed/42 deselected、39/0/0 与真实三模态 TCP 结果以 C 交接为来源，不冒充 B 本轮结果。
- 用户明确回复“前端未就绪”。因此正式 Edge 页面、真麦克风/摄像头预览、句末截图、浏览器实际播放/回执和手机 HTTPS 均待正式前端完成后验收；不要求用户另建录音页、手动录制或保存文件。本轮没有启动服务器、修改运行数据库或宣称设备已通过。此前对 `speech.wav` 的用户实听继续有效，但不外推为新链路全场景实听。

下一步：A 正常合入 C `dfb41df` 及 B 本轮回归/交接，收口提案真实 TTS、Dashboard 来源 schema/service 和新关怀文字动态 TTS；短信/社区外部服务仍是独立接入事项，MiMo key 不代替这些服务。B 对现有音频适配器无新增依赖要求，待正式页面就绪后继续设备验收。

## 用户最新要求与业务闭环核查

用户明确：正常演示使用 MiMo 真实 ASR、理解模型和 TTS；预设关怀和历史种子可以是演示素材，但业务写入、发送、播放回执、历史保存和回看必须真实执行。模型可用不等于所有意图、上下文续接和业务接线已经完成。原任务中“本轮提案不要求真实 TTS”的阶段边界不能继续用来解释用户此次提出的完整产品要求；此项应纳入 A/C 下一批接线，B 不越过共享文件白名单自行修改状态机。

### 本次实际完成

- 重新同步远端跟踪引用后，A 仍为 `582e304`，C 仍为 `bb37744`，未发现更新的多意图实现。
- B 本机被忽略的 `backend/.env` 已由旧的三项 mock 改为 `CHAT_PROVIDER=real / ASR_PROVIDER=real / TTS_PROVIDER=real`，补齐 ASR 官方地址与 `mimo-v2.5-asr`，按用户同一 MiMo 账号约定复用本机 key；未输出或提交密钥。原独立 DATA_DIR、数据库和端口保留。
- 显式将该文件导入本次子进程，正常 `Settings` / `build_agent_providers` 构建通过：三个实际对象均 `name=real / is_mock=False`，输出 `B_LOCAL_REAL_FACTORY_OK`。`git check-ignore .env` 通过。构建未发供应商请求、未启动应用或改动运行库，也没有重启已有服务；应用仍不会自动读取 .env，运行实例必须在加载该配置后重启，并以 `/runtime.providers` 为准。
- 免费回归实际运行：`python -X utf8 -m pytest tests/health/test_activation.py::test_records_correction_cancel_and_three_views_persist tests/health/test_activation.py::test_family_voice_priority_shared_copy_repeats_and_no_taken tests/health/test_activation.py::test_family_fixed_speech_exact_fixture_integrity tests/health/test_activation.py::test_family_ownership_permissions_and_text_fallback tests/health/test_history.py tests/health/test_http.py::test_http_same_meal_replay_conflict_and_child_report tests/agent/test_http.py::test_actual_b_confirmation_writes_once_and_report_uses_same_record -q --tb=short --basetemp=.pytest_cache/b-real-workflow-audit` → **11 passed / 1 既有 warning / 7.04s**。子进程显式使用 mock provider 与临时 SQLite；验证的是实际业务服务/端口/HTTP/数据库，并非真实模型或 Edge 设备。本次未重复付费探测。

### 当前事实与接下来的责任范围

| 项目 | 已有实现 | 仍需完成 / 负责方 |
| --- | --- | --- |
| 真实 ASR/TTS | MiMo 适配器、正常 AI01/AI02 装配、来源校验和失败降级已通。默认测试保留 HTTP 替身，真实失败不会偷偷回退固定答案。 | B 配合正式 Edge PCM WAV 收音、句末截图、播放与回执验收；尚无实际麦克风采样证据。 |
| 意图识别与执行 | C `dfb41df` 已补真实多意图路由、对应执行端口及持久化澄清草稿；B 已合入复验。 | A 正常合入并统一复验；前端保留 conversation_id，按最终回复和实际动作状态呈现。不能扩大成自动新增/改变用药方案。 |
| 语音确认 | C 已补“确认。”等标点、自动截图、取消/更正优先处理及澄清续接；B 新增正常三 real 工厂与实际 ASR 适配器的组合回归通过。 | 正式 Edge 真麦克风与播放器尚待验收，不能拿 HTTP 替身或合成输入代替设备证明。 |
| 家人关怀 | 预设全文音频或子女上传录音能实际保存、通知老人、取回播放、上报回执；重复播放不等于服药/运动打卡。任意新文字目前可发送，但没有动态 TTS。 | 预设素材可按用户要求继续使用；前端走实际通知/播放/回执。若支持任意文字语音，A/B 接既有 TTSProvider，并保留文字降级。 |
| 历史与回看 | 14 天历史标记 demo_seed；后续实际新增、修改、取消、分页查询、日历、日报和家庭看板走真实 SQLite；确认动作幂等，不重复新增。上述 11 项含相关验证。 | 前端接真实查询接口并验证重启后回看，不把展示样例当成新记录；不重新清库或覆盖用户数据。 |
| 修改提案播报 | 指子女申请修改老人档案、提醒设置或用药计划后，向老人读出具体完整改动；真实提案/决定状态机已实现。C 已补真实来源/全文标记与校验，但 `identity_flows.create_change` 仍显式构造 `ProposalFixtureTTS()`。 | A 接已有配置的 TTSProvider。外部调用放写事务外，保持原文一致和媒体登记；失败保留全文、无完整音频不启动 60 秒窗口。B 提供适配器验证，不重写状态机。 |
| 看板来源标识 | 看板实际统计来自数据库。 | A 处理 `Dashboard.provider_mode` schema/service 写死 mock 的历史字段，避免把真实统计误标；不能只改标签掩盖上述路由缺口。 |

后续验收顺序：A 合入已补齐的 C 真实意图和语音确认/澄清续接，接提案及新关怀文字 TTS，然后从正式 Edge 界面执行“说话→ASR→句末截图+文字→意图→业务子流程→明确确认→实际保存→最终文字 TTS→历史回看”。仅对已经验证的意图与设备范围报告通过。

提案全文可能超过 B 当前单次 200 字保护上限；不能简单截断。接线验收需覆盖全文超限时明确文字降级，或另行实现并验证完整分段合成/拼接；无完整音频时不能启动自动生效窗口。该要求不是新增模型或媒体库的理由。

## 基线与协作进度

- 共同起点：`363f6376a63d696ba36b1bc7fc426e8b159dc196`；B 分支 `backend/f2-audio`，独立 worktree `E:/CUHKSZ/project/vitasenior/.audio-work`。
- 已正常合入 A `origin/f2/platform@24debddce9f5f2a88ee68f56f6245f7bba5b4c95`，合并提交 `41906d226adef26cbbac58ac6931dd5b1e86d1d8`，零冲突，包含 A 的 `9f46203` 握手和 C 的 `96177dc`。
- 真实 TTS/实听之后，又正常合入 C `backend/f2-understanding@bb37744`，合并提交 `fe9b2d7a66efb3535a5c5aa2ad3cfa4d2be18f17`，零冲突；包含 C 的 Flash 非思考模式补丁及其回归，B 未自行编辑 C 文件。同步时 A 的远端仍为 24debdd，旧公共断言尚未更新。
- ASR 独立探测通过后，正常合入 A `origin/f2/platform@0d9d9cc`（`f2-demo-v3`）。A 已集成并实测真实 chat+TTS，修复旧“real_tts 模块不存在”断言；该历史测试阻断已关闭。ASR 配置/工厂仍为 mock，后续由 A 单独接线，不移动既有标签。
- 最新已快进到 `origin/f2/platform@582e304ef62c831ba7d825654d159b5dfa0ce19f`（`f2-demo-v4`），A 新增真实 ASR 配置/装配/Runtime 并更新公共测试。上述“ASR 仍 mock/待 A 接线”仅为历史状态。B 本次没有编辑共享文件、重复调用付费模型或重打标签。
- C 最新交接报告：正常工厂/Uvicorn 的真实文字、餐食照片、确认落库、看板/日报、重启及显式 mock 回退均通过；A 已合入复验。此处是 A/C 的证据，不冒充 B 已重复发起供应商请求。
- B 自己的改动仅 `providers/real_audio.py`、用户后续明确新增的 `providers/real_tts.py`、`tests/providers/test_real_audio.py`、独立 `tests/providers/probe_real_tts.py` / `probe_real_asr.py` 和本文件。公共/其他领域文件只来自正常 merge，没有由 B 编辑。
- 测试用临时 SQLite；B 本机演示数据 `backend/data/f2-audio-b`、默认数据库 `vitasenior.sqlite3`，端口 8022。没有操作他人的运行库、重置历史或移动标签。

## A 可直接使用的冻结入口

```python
from app.providers.real_tts import build
tts = build(settings)  # A 的现有 composition 已调用此处
speech = tts.synthesize(final_text)  # 事务外；随后通过既有 MediaPort 登记
```

`real_tts.MiMoTTS` 复用 `real_audio` 的唯一 MiMo HTTP/音频实现：生产入口 `name='real'`、`is_mock=False`，返回 `Speech.is_mock=False`、原样 `text`、`audio/wav`、真实帧时长。未增加第二个 provider 协议、媒体库或应用入口。AI02/Agent 来源与媒体登记使用 C 已合入的 flow。

配置与 A 一致，不再使用早期建议的 MIMO_* 变量：

```dotenv
TTS_PROVIDER=real
TTS_API_KEY=<仅在本机填写>
TTS_BASE_URL=https://api.xiaomimimo.com/v1
TTS_MODEL=mimo-v2.5-tts
TTS_VOICE=冰糖
```

`TTS_VOICE` 可省略，默认 `mimo_default`。仅支持该模型的预置音色；未知 `voice_id` 明确 422。API root 只接受上述官方 HTTPS 地址（允许末尾 `/`），配置错误在构建时失败，不把 key 发到任意地址。供应商路径 `/chat/completions`，原文置于 assistant message，非流式请求 WAV，解析 JSON 的 `choices[0].message.audio.data`。旧型号、音色设计/克隆不在本轮范围。

文本限 200 个 Python 字符（含空白），超限整段 `502 PROVIDER_ERROR`、reason=text_too_long，不截断；这使 Agent 的现有 catch 保留全文及 `tts_unavailable`。空白/NUL/未知音色 422。连接最多 5 秒、整个供应商请求 20 秒，能取消缓慢响应，无重试/隐式 mock；同步协议内部用 HTTPX AsyncClient 实现可取消的总期限，不改业务入口。

JSON 最多 20 MiB+64 KiB，解码音频最多 15 MiB/120 秒；严格 Base64、单 choice、finish_reason=stop，校验完整 RIFF/chunk/24kHz/16-bit PCM/帧长并拒绝空、全零静音、截断。MiMo 真实响应的 transcript=null 表示没有独立转写，现已兼容；若提供非 null transcript，仍必须与全文一致。Speech.text 始终保留入参。容器完整不能证明逐字读全和音质，仍需人工实听。上游超时 504，其他供应商失败/无效音频 502；错误不公开 key、供应商响应体或输入文字。

此处为已发布版本的状态：提案仍用 F1 精确全文 fixture，未改提案状态机或 60 秒窗口；播放不形成 taken。用户最新提出的提案真实 TTS 接线缺口见本文首节。

## 本机 env 与真实探针

`backend/.env.mimo.example` 已从 C/A 正常合入。B 在自己的 worktree 创建了被忽略的 `backend/.env`，改用 B 的独立数据/端口并补 TTS_*；用户将 MiMo key 填入 CHAT_API_KEY 后，B 按统一账号约定在本机将同一个 key 复用到 TTS_API_KEY、后续再补 ASR_API_KEY。密钥未进入代码、命令参数、输出或 Git。`git check-ignore backend/.env` 实际通过。早期本机文件保留三项 mock 是独立探测阶段的配置，不是当前产品目标；现已按本文首节改为三项 real。独立 TTS 探针仍只启用真实 TTS，不重复调用 C 的真实理解。

独立探针不被 pytest 收集；显式读 TTS_*，忽略文件里的数据库地址、DATA_DIR 和 chat 选择，始终用自己的临时数据库、真实默认工厂/登录/Runtime/AI02/票据 MEDIA03。仅一次供应商请求，无重试，不调用真实 chat：

```powershell
# backend 工作目录，Python 为 ../../.review-venv/Scripts/python.exe
python tests/providers/probe_real_tts.py --env-file .env --live
# 可选：--text '这是一条新的中文完整播报测试。'
```

也可在进程设置 `LIVE_TTS=1`；无显式启用会退出 2。缺 key/base/model 同样退出 2。成功后 `data/f2-audio-b/evidence/<独立时间戳>/speech.wav` 和 `evidence.json` 保留文本、时间、模型/音色、MIME、时长/字节数、SHA-256、耗时、Runtime，生成时标记 `listened=false`，有实听确认后再更新；不保存 token/票据/key。真实探针用 TestClient 驱动正常应用，尚不代替真实 TCP/前端设备播放。

应用不自动加载 .env。A 的 run-demo.ps1 默认依赖 backend/.venv，本机实际复用 ../../.review-venv；长期服务应按本机解释器路径显式导入 env 后用单 worker/8022 启动，不改共享脚本来适配 B 工作区。

## 实际检查

环境：Windows / Python 3.11.5 / 原锁定依赖 / HTTPX 0.28.1。默认 pytest 全为替身，付费测试已迁出。下表命令在 backend，python 指 ../../.review-venv/Scripts/python.exe。

| 命令 | 结果 |
| --- | --- |
| `python -m pytest tests/providers/test_real_audio.py -q --tb=short --basetemp=.pytest_cache/f2-b-shared-handshake` | 118 passed / 1 warning / 8.56s（独立探针的两项回归加入前） |
| `python -X utf8 -m pytest tests/providers/test_real_audio.py -q --tb=short --basetemp=.pytest_cache/f2-mimo-null-transcript` | **121 passed / 1 warning / 9.06s**，含真实响应 null transcript 兼容回归 |
| `python -m pytest tests -q --tb=short --basetemp=.pytest_cache/f2-b-integrated-all` | **485 passed / 1 failed / 42 deselected / 1 warning / 146.30s**；唯一失败为下述 A 旧阶段断言，包含 B 的 120 项通过 |
| `python -X utf8 -m pytest tests -q --tb=short --basetemp=.pytest_cache/f2-b-live-final` | **488 passed / 1 failed / 42 deselected / 1 warning / 126.88s**；含 B 121 项通过，唯一失败仍是 A 的旧“模块不存在”断言 |
| `python -m app.tools.export_contract --check` | OpenAPI matches `4b7ade26f590902a4eb131920589184b95e0b54a293e9df80ac9f8aa4859532c` |
| `python -m app.tools.check_architecture` | Architecture OK |
| `python -m pip check` | No broken requirements found |
| `python -m app.tools.integration_smoke --strict` | **39 OK / 0 PENDING / 0 FAIL** |
| `python tests/agent/smoke_network.py` | C_NETWORK_SMOKE_OK，默认 Uvicorn/mock、独立临时数据库 |
| `python tests/providers/probe_real_tts.py --help` / 无参数 | help 正常；无参数按预期退出 2，不读 env/不发请求 |
| `python -X utf8 tests/providers/probe_real_tts.py --env-file .env --live` | **B_LIVE_TTS_OK**，正常工厂/AI02→票据 MEDIA03，供应商真实网络 |

新增入口回归覆盖：正常工厂与 Runtime、AI02 完整媒体字节、HTTP 等待期间独立写 UoW 可提交、未登录/越权不触发供应商、Agent 正确 real 来源/超时与超长全文降级/确认前无健康记录、显式 mock 重启保留会话。诊断 PCM/HTTP 替身均不是真实合成证据。

### 真实结果（2026-10-31 15:41，Asia/Hong_Kong）

- 模型 `mimo-v2.5-tts`，音色 `冰糖`，返回 `provider=real / supplier=mimo / is_mock=false`；Runtime 为 chat=mock / asr=mock / tts=real。
- 新中文全文含末尾香港本地日期时间；合成和媒体登记约 **7.032 秒**，取回 **652844 字节 / 13600 ms / audio/wav**。严格完整 WAV/PCM 校验通过。
- 本机证据：`backend/data/f2-audio-b/evidence/20261031T074100Z-7238915d/speech.wav` 与 `evidence.json`，均被 data/ 忽略。SHA-256 `ee2ef3983781d18405d4f075356f4fd379d41f372ccfe7f3dd98ccd52c8c5728`。用户已对该文件确认“全文清楚、无截断”，本机 manifest 记 `listened=true` 及用户确认来源/时间。该证据是实际文件实听，不代表手机 HTTPS/网页自动播放已验收。
- 过程如实记录：第一次因 TTS_API_KEY 空未调用；复用本机 key 后一次沙箱网络传输失败；随后两次供应商响应到达，但被本地错误的 null transcript 校验拒绝（其中一次显式诊断）；补兼容回归后一次正式复验通过。实际到达供应商的请求共 3 次，各次均显式运行，没有自动重试。诊断只观察字段，没有绕过校验制造通过。

## 待 A 收口与下一步

1. TTS 和 ASR 的旧阶段断言均已由 A 更新；B 未修改公共测试。真实 ASR 已正常装配，历史 1 failed 和 ASR 配置阻断均已关闭。
2. A 的 `Settings.tts_timeout_seconds` 当前为固定字段 20.0，尚未读取 TTS_TIMEOUT_SECONDS 环境变量；显式构造 Settings 时能传 timeout。若承诺该可选环境变量，由 A 在配置层处理，B 不另读 env。默认 20 秒不受影响。
3. 新中文 AI02→MEDIA03 与该文件人工实听已通过；B 继续做前端/真实端口集成验证，不为重复验同一文件扩大供应商请求数量。此为音频适配器范围，不能推断其他 Agent 子流程已经完成。
4. A 的三模态工厂集成已完成；正式前端的一句一轮音视频采集、图文 Agent 与播报仍待联调，同时 C/A 需补本文首节所列多意图及提案接线。C 现有真实饮食流程继续复用。

### B 对 f2-demo-v4 的独立核验

- 已核对 A 的配置、工厂、Runtime 与最新交接：A 记录正常 Uvicorn 下 chat/asr/tts 全 real，AI01 真实转写约 1.0 秒；A 全量 527 passed / 42 deselected、严格联调 39/0/0。这些供应商网络结果是 A 的证据，B 本次没有重复计费调用。
- B 本机实际运行 `python -X utf8 -m pytest tests/framework/test_shared_adaptation.py tests/agent/test_f2_configured_startup.py tests/providers/test_real_audio.py -q --tb=short --basetemp=.pytest_cache/b-v4-assembly-review` → **172 passed / 1 warning / 11.50s**。
- 另用临时 SQLite、实际 Settings/工厂装配三模态 real，仅替换 ASR HTTP transport：真实登录→Runtime 全 real→MEDIA01→AI01 来源/转写均一致，输出 **B_V4_OFFLINE_FACTORY_AI01_OK**；无 provider/service 注入、无付费请求。
- 契约与架构检查通过，OpenAPI hash 仍为 `4b7ade26f590902a4eb131920589184b95e0b54a293e9df80ac9f8aa4859532c`。本次未重复跑全量 527 项或真实浏览器采集。
- A 交接中仍有少量“ASR 固定 mock/等待 B”的历史段落；应以其最新 §1.1、FAST-06、实际代码及本节为准。该文档清理项不代表接线仍未完成。

## 用户追加 ASR：独立接口已通，待产品接线

用户明确的目标交互是：Edge 中摄像头持续本地预览、麦克风收音，一句话结束时取当前帧，将转写文字与截图交给 Agent，再播放 TTS。**不要求用户另做录音页面或手动准备文件目录**。本轮没有新增独立录音/验收网页；前端采集应接在正式界面。

入口复用原 ASRProvider/ASRResult，无共享 DTO 改动：

```python
from app.providers.real_audio import MiMoASR
asr = MiMoASR(api_key=local_secret, base_url="https://api.xiaomimimo.com/v1",
               model="mimo-v2.5-asr", timeout_seconds=20)
result = asr.transcribe(wav_bytes, "audio/wav")  # 无 Session，退出读 UoW 后调用
# result.provider == "real", result.is_mock is False
```

- 当前适配器限定完整 16-bit PCM WAV（mono/stereo、最多 60 秒/7 MiB），Base64 小于供应商 10 MB 上限。未知 MIME、WebM/MP4、截断、超限在发送前明确失败，不改扩展名、不转码。MiMo 官方还支持 MP3，但本轮没有扩展/验收该格式。
- 输入只发音频，不给模型参考文本/固定答案；拒绝 mock_fixture_id；返回真实非空转写。空转写 422、上游/非法 JSON/不完整 finish_reason 明确 502，超时 504；连接最多 5 秒/单次总期限 20 秒、无重试/静默 mock。
- `language=zh-CN` 表示本轮固定使用中文识别参数，不是独立语言检测结论。转写不会触发饮食或服药事实写入，仍由既有 Agent 待确认/确认流程处理。
- 单独探针 `probe_real_asr.py --env-file .env --audio <演示PCM WAV> --live` 不被 pytest 收集。仅该隔离探针允许复用同一个已配置 TTS MiMo key；这不是新增生产环境变量别名。探针标记 Edge/default-factory 未验收，禁止拿它冒充正常装配。

### 实际结果

- `python -X utf8 -m pytest tests/providers/test_real_audio.py -q --tb=short --basetemp=.pytest_cache/f2-b-asr-with-probe`：**159 passed / 1 warning / 11.36s**，含 TTS 原回归、ASR 成功/新录音不同输出、超时/401/403/429/5xx、无效音频/输出、显式注入 AI01 的媒体鉴权与写锁释放、独立探针门控。pytest 无付费请求。
- 合入 A 0d9d9cc 后的全量：`python -X utf8 -m pytest tests -q --tb=short --basetemp=.pytest_cache/f2-b-asr-final-all` → **527 passed / 42 deselected / 1 warning / 124.81s**。TTS 旧公共断言失败已关闭；契约与架构检查通过，OpenAPI hash 不变。没有重跑真实 chat/TTS 计费请求或全部手机/前端演练。
- 独立探针 `--help` 正常；不带 --live 按预期退出 2。
- **2026-10-31 16:16（Asia/Hong_Kong）**：`python -X utf8 tests/providers/probe_real_asr.py --env-file .env --audio data/f2-audio-b/evidence/20261031T074100Z-7238915d/speech.wav --live` → **B_ASR_WAV_PROBE_OK**，仅一次真实 ASR 请求，耗时 **2.672 秒**，模型 `mimo-v2.5-asr`、provider=real/is_mock=false。
- 输入是已实听的 13.6 秒 TTS WAV，不是 Edge 麦克风采样；SHA-256 `ee2ef3983781d18405d4f075356f4fd379d41f372ccfe7f3dd98ccd52c8c5728`。实际转写主要句子和末尾日期时间完整，但“您好”转为“你好”、“银龄”识成同音“银铃”，不能宣称逐字零错。结果位于被忽略的 `data/f2-audio-b/asr-evidence/20261031T081635Z-a3cb0303/evidence.json`，不提交录音或密钥。

### A / C / 前端接线

1. **A 已完成**：`ASR_PROVIDER=mock|real`，real 时显式要求 ASR_API_KEY / ASR_BASE_URL / ASR_MODEL；工厂构造 MiMoASR，Runtime 报告实际模式，公共测试已同步。B 没有修改 core/main/composition 或另建工厂。
2. **C / 前端联调**：现有 flow 已接 `ASRProvider.transcribe` 并使用真实 provenance。前端接好后验证 audio_asset_id + image_asset_ids 一起送 AGENT01：先 ASR，再与该帧共同理解；保留 45 秒总预算和鉴权复验、确认前不写业务事实。若前端先走 AI01 展示/修正转写，再用 text+图片调用 Agent，则已有 text 时不重复 ASR。
3. **前端**：说完话那一刻固定一帧，WAV 与图片通过既有 MEDIA01 上传，再提交同一轮 Agent；持续预览不等于持续上传视频。录音格式应在实际 Edge 验证：可考虑直接采集 PCM 并封装 WAV，避免服务器端 WebM 转码；不能假定默认 MediaRecorder 就返回 WAV。若最终只产 WebM 且需要转码，按原约定重新评估范围，不静默改后缀。TTS 播放与下一轮收音的回授控制也需随正式界面联调。
4. **用户**：正式界面接好后，在 Edge 正常说一句“今天午餐吃了青菜、豆腐和米饭，请帮我记录。”即可验收。现在无需单独录音、安装软件或管理测试目录。

官方协议参考：[MiMo TTS](https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/audio/speech-synthesis)、[MiMo ASR 协议与格式](https://mimo.mi.com/docs/zh-CN/api/audio/Speech-Recognition)、[浏览器录制格式选择](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder/MediaRecorder)。真实 TTS/媒体字节与本机实听已验；ASR 独立接口及正常应用装配已验；Edge 录音、摄像头预览/句末截图与真实界面串联尚未验收。
