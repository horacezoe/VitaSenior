# F2 交接（集成人 A）

基线：`integration/f1` 的 `363f637`，分支 **`f2/platform`**（保留既有数据目录与数据库，不重建）。
本轮：3 小时交主链、4 小时结束后端功能；**2:15 冻结范围**。

## 1. 已完成（第一批，30 分钟内）

| 交付 | 位置 | 状态 |
| --- | --- | --- |
| 前端接入包 | `docs/协作/F2交接/前端接入.md` | ✅ 启动方式、固定契约、错误码、登录→看板 13 步、图片/播放/回执口径、当前边界 |
| 可运行样例 | `backend/app/tools/demo_walkthrough.py` | ✅ `python -m app.tools.demo_walkthrough [--base-url ...]`，逐条打印请求/响应，`WALKTHROUGH_OK` |
| 最小配置/工厂共享提交 | `app/core/config.py`、`app/composition.py`、`app/main.py` | ✅ 已推 `f2/platform`，B/C 直接 merge 即可 |

### 1.1 统一复验（合入 B `3195fc0`：TTS + ASR，C `bb37744`）

- 合并提交 `3195fc0`（B 的 MiMo TTS/ASR + C 的 Flash 轻量理解，零冲突）。
- `pytest tests -q` → **527 passed, 42 deselected**；`integration_smoke --strict` → **39/0/0**；
  `export_contract --check` 未变；`Architecture OK`。
- 三模态真实装配均已实测（`run-demo.ps1` + `backend/.env`，真实 uvicorn）：

| 能力 | 实测 |
| --- | --- |
| chat | `AGENT01` 真实文字 201 / 9.6s，正确得出午餐+三种食物 |
| tts | `AI02` 200 / 1.7s，`provider=real`、`is_mock=False`、`audio/wav` 84 KB / 1760 ms |
| asr | `AI01` 200 / 1.0s，`provider=real`、`is_mock=False`，13.6s PCM WAV → 正确转写 |
| runtime | `providers = {chat: real, asr: real, tts: real}`，45 项能力 true |
- A 修正了自己两条过期断言（"`real_tts.py` 不存在就报错"、"ASR 必须拒绝 real"）；现在三个模态
  都可显式切 real，缺 `*_API_KEY/*_BASE_URL/*_MODEL` 一律拒启，不会半 mock 半 real。
- `run-demo.ps1` 会把 `PUBLIC_BASE_URL` 的端口对齐到 `-Port`，否则媒体 `content_url` 指向错误端口。
- **未验收**：Edge 实际麦克风/摄像头采集、句末截图、真机播放（前端后续）；C 的
  `smoke_mimo_network.py` 需要真实餐食照片，A 无素材，照片证据仍以 C 的探测为准。

**Provider 工厂（本轮唯一的共享依赖）**：只切换 TTS，不做通用 provider 平台。

```python
build_agent_providers(settings) -> (chat, asr, tts)   # ASR 固定 mock
providers(settings) -> {"chat": settings.chat_provider, "asr": "mock", "tts": settings.tts_provider}
```

- `TTS_PROVIDER=mock|real`；`real` 时 A 调用 B 的 `app/providers/real_tts.py::build(settings)`。
- `CHAT_PROVIDER=mock|real`（C 的 `RealUnderstanding`）；`ASR_PROVIDER` 仍固定 mock（本轮延期）。
- 两种真实 provider 都要求对应 `*_API_KEY / *_BASE_URL / *_MODEL`，缺一项启动直接失败。
- `providers` 状态由实际构建的对象推导，`agent_capabilities.py` 不保存第二份状态；mock 永远不会
  被标成 real。

## 2. FAST-01–04（发布新标签的门槛）

| 编号 | 含义 | 判定方式 | 当前 |
| --- | --- | --- | --- |
| FAST-01 | 前端可用：地址/启动/固定契约/登录→看板样例 | 前端按 `前端接入.md` 跑通 `demo_walkthrough` | ✅ 文档+脚本+实测 |
| FAST-02 | **真实文字/餐食照片 → 饮食确认落库**（用户本版口径） | `CHAT_PROVIDER=real` 启动、`/runtime.providers.chat=="real"`、真实文字与照片各跑一轮：待确认→确认落库→重试不新增→子女看板/日报同一记录 | ✅ 适配器与供应商实测由 C 完成（`backend/f2-understanding@11445bb`：文字约 3.8s、图片约 11.8s，C 侧 157 passed）；A 已放开并接线，见 §2.1 |
| FAST-03 | 提案播报保留 F1 全文 fixture；无完整音频不计时 | 有匹配语音 → 播报后 60 秒窗口生效；无匹配 → 只有文字、`auto_apply_at` 恒 null | ✅ 回归已覆盖，B 侧 NOTI03 已验 |
| FAST-04 | 完整主链（建档→绑定→饮食确认→看板/日报） | `integration_smoke --strict` 39/0/0 | ✅ |
| FAST-05 | 真实 TTS 接入且标识准确 | `TTS_PROVIDER=real`、`providers.tts=="real"`、`AI02` 返回真实音频（`is_mock=false`、可播放字节） | ✅ 已由 A 实测：`AI02` 200 / 1.7s，`provider=real`、`is_mock=False`、`audio/wav` 84,524 B / 1760 ms，取回字节以 `RIFF` 开头；B 侧另有用户实听确认 |
| FAST-06 | 真实 ASR 生产装配（用户追加） | `ASR_PROVIDER=real`、`providers.asr=="real"`、`AI01` 返回真实转写 | ✅ A 已装配并实测：`AI01` 200 / 1.0s，`provider=real`、`is_mock=False`，13.6s PCM WAV → 正确转写；Edge 实际采集未验收 |
| FAST-07 | 提案播报用真实 TTS（不再限于 5 段预录） | 任意 patch 的提案都带真实音频、文本与语音一致 | ✅ A 已实测：`CHANGE01` 201 / 4.2s，含"术后复查已预约下周二上午九点"的完整叙述，通知带 622,124 B / 12,960 ms 的 `audio/wav`；mock 模式仍走 5 段精确样例（不伪造） |

标签策略：FAST-01–05 全绿后发布新标签（`f2-demo-v1` → `f2-demo-v2` → 本轮 `f2-demo-v3`），
**不移动 `f1-integrated-v1`**。未通过项按编号写在下表，不用"部分通过"含混表述。

### 2.1 真实理解（chat）接线 — 已完成

`CHAT_PROVIDER=real` 已放开，装配由 A 统一维护：

```powershell
$env:CHAT_PROVIDER = 'real'
$env:CHAT_API_KEY  = '<你自己的 MiMo key>'
$env:CHAT_BASE_URL = 'https://api.xiaomimimo.com/v1'
$env:CHAT_MODEL    = 'mimo-v2.6-flash'
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

- 新增 `Settings.chat_api_key/chat_base_url/chat_model/chat_timeout_seconds`；`CHAT_PROVIDER=real`
  缺任一项**启动即失败**（`CHAT_PROVIDER=real requires CHAT_API_KEY, CHAT_BASE_URL and CHAT_MODEL`），
  不会半真半假地跑。
- `build_agent_providers` 用 C 的 `app.providers.real_understanding.RealUnderstanding`；
  `providers(settings)` 按实际实例报告，实测 `{'chat': 'real', 'asr': 'mock', 'tts': 'mock'}`。
- 默认仍全 mock、无需任何密钥；`ASR_PROVIDER` 仍强制 mock（本轮延期）。
- **应用不会自动读取 `.env`**：这是刻意的（本地密钥不能污染 pytest 的确定性）。`backend/.env`
  是 gitignore 的本机密钥文件，`backend/run-demo.ps1` 会把它导出成进程环境变量再启动 uvicorn；
  也可以直接在 shell 里设变量。C 另给了空密钥示例 `backend/.env.mimo.example`。
- **真实 uvicorn 实测**（`run-demo.ps1` + `.env`，端口 8011）：`/health` ok、scheduler running、
  `/runtime.providers = {chat: real, asr: mock, tts: mock}`、45 项能力全 true；真实 HTTP
  `AGENT01` **201 / 9.6s**，正确得出午餐+青菜/豆腐/米饭的待确认 `record_diet`。
- A 用占位凭据验证过"启动 + Runtime 报告 + 默认 mock 回归"，并用真实 key 复跑了文字与图片链路；
  **密钥只存在于本机 `backend/.env`（gitignore），未进入任何提交或标签**。

## 3. 合并与协作约定

- B/C 随时合 `f2/platform`；A 随到随合他们的分支，冲突只改共享文件。
- 新能力登记仍只看实测：`identity/health/agent_capabilities.py` 由各域自己加，A 不代开。
- 只用现有协议与错误码；不新增 DTO、不建第二套 provider 抽象、不做独立验收页面。
- 现有回归基线（合入 C `11445bb` 之后）：`pytest tests -q` → **361 passed, 42 deselected**；`export_contract --check` →
  `4b7ade26…`；`integration_smoke --strict` → 39/0/0。

## 4. 未验证/未完成（明确记录，不算通过）

| 项 | 说明 |
| --- | --- |
| 看板 `provider_mode` | A 已把公共 schema 从 `const:"mock"` 放开为 `enum:["mock","real"]`（契约 `6c1e8d96…`），并在 composition 里给 `reports.provider_mode` 注入真实值；**B 只需把硬编码的 `"mock"` 换成 `self.provider_mode`**，否则响应仍报 mock |
| 家庭关怀文字的动态 TTS | 接缝已就绪：任意文字可用 `app.state.agent_tts.synthesize(...)`（真实 TTS 时），B 在 NOTI04 接线即可；A 不在语音事务里做 provider 调用 |
| 短信 / 社区数据 | 仍是演示实现，需要真实外部服务，本轮不在范围 |
| 手机 HTTPS / 真实设备播放 / Edge 采集 | 按用户安排延期；只验证了字节、票据与文件级 WAV，未验证真机麦克风/摄像头/实听 |
| P1 接口 | 登出/解绑/删计划/撤销提案/记忆导出/推送均未挂载 |
| 完整 AC01–AC14 | 未按总计划逐条演练 |

## 5. 待办与风险

### 5.1 给 B 的真实 TTS 握手契约（A 侧已就绪）

1. 新增 `app/providers/real_tts.py`，提供模块级 `build(settings) -> TTSProvider`。
2. 返回对象必须：
   - 有 `name = "real"`（`AI02` 用它报告来源；名字与 `is_mock` 不一致会 502
     `Speech provenance differs from the configured provider`）；
   - `synthesize(text: str, voice_id: str | None = None) -> Speech`，其中
     `Speech(content: bytes, mime_type: str, duration_ms: int, text: str, is_mock: bool = True)`
     必须 `is_mock=False`、`text` 与入参**完全一致**（flow 校验，不一致即 502）。
3. 配置已冻结：`TTS_PROVIDER=real` + `TTS_API_KEY` / `TTS_BASE_URL` / `TTS_MODEL`
   （可选 `TTS_VOICE`、`TTS_TIMEOUT_SECONDS`）。缺前三项启动直接失败，不会半 mock 半 real。
4. 可用供应商：MiMo `mimo-v2.5-tts`（同 key，`https://api.xiaomimimo.com/v1`）。
5. 测试要求：pytest 里用假 transport 固定响应，不打真实计费请求；真实调用走显式 env 门控的探针。
6. B 交付后 A 验证：`/runtime.providers.tts == "real"`、`AI02` 字节非空且 `is_mock=false`、
   音频长度合理、`TTS_PROVIDER=mock` 时行为不变；通过后补 FAST-05。

| 项 | 负责 | 说明 |
| --- | --- | --- |
| 真实 TTS | B | 提供 `app/providers/real_tts.py::build(settings)`，返回对象需有 `synthesize(text, voice_id=None) -> Speech`；随后把 `TTS_PROVIDER=real` 跑一遍 FAST-02 |
| 真实文字/照片理解 | C | 只用现有 `AgentTurnWrite`（`text` + `image_asset_ids`），确认动作仍走 `CheckinPort(source="agent_confirmed")` |
| 提案播报文案 | A/B | 可在文案里补"60 秒内未拒绝将生效"，属文案优化，不另建协议 |
| HTTPS/真机播放 | 延期 | 排障限时；先交前端可用 API，不做独立验收页 |
| P1 接口 | 未排期 | 登出/解绑/删计划/撤销提案/记忆导出/推送仍未挂载 |

## 6. 已知边界（不要当缺陷）

- AI 全部 mock；`providers` 如实标 mock（接入真实 TTS 后只有 tts 变 real）。
- 提案语音只有 5 段精确匹配样例；不匹配时保存完整文字、`audio_asset_id=null`、不启动 60 秒窗口。
- 单一 FastAPI 进程 + SQLite + 现有扫描器；不引入 Redis/Celery/向量库/通用工作流。

## 7. 社区多人物与自动匹配（2026-11-01）

本轮基线 `4a0c8bc2f19b755eaa2a9a0a7b593119cd5b9465`。工作区已有对话、视频用药、日报相关未提交改动，本轮只在其上追加社区建档功能，不覆盖其他人的修改。

- 同一SQLite新增 community_records、demo_identities，启动和 framework seed 只补种缺失记录。13份完全虚构社区档案（12份慢病及组合、1份无慢病）和1个未建档身份；用户正式档案保留在 elder_profiles。已有表无新增列，旧数据目录可直接启动补建新表，旧账号自动匹配无身份映射时返回 not_found。
- 新增 `DEMO02 GET /api/v1/demo/personas`，仅提供人物摘要。DEMO01 可传 persona_id，返回 persona_id/persona_name，为独立家庭分配账号并持久关联社区身份。scenario 保留旧值作为兼容字段，实际历史模板跟随人物。
- ONB01 `{}` 或 `{mode:"auto"}` 按当前账号匹配；manual 创建空草稿。刷新恢复草稿及手工选择。已确认档案拒绝新的匹配/确认请求，原幂等确认可重放。旧 sample_identity_key 脚本受账号映射约束；无映射旧账号仅兼容最初样本。
- ONB02 仍在同一事务导入档案、计划、历史。HistoryPort 新增可选 `seed: DemoHistorySeed | None`，包含模板键与稳定计划键到已导入实际plan_id的映射；编辑、删除、重复计划跳过其历史。多计划和餐后时段均支持，餐后必须有同日餐食，历史早于确认日，不产生历史通知。
- 前端登录入口可选人物，首次登录自动查询并进入核对表单，支持信息不符转手工。已确认档案直接回首页。身份照片移出必经流程；原隐藏的演示设置路由不重新开放。

社区功能首次导出 OpenAPI SHA-256：`ee052bddc0403edc6d4db08191cb2aeeac81518bd83a4145b4f339524c83d209`。并行 PLAN05 用药风险接口加入后的当前契约 SHA-256：`57f05061929f81ab9a2b6c4a23dd2d0e590aaed955850031b9a0dbc885dad523`。已同步前端生成契约；当前P0接口总数47（本轮新增DEMO02，并行新增PLAN05），表总数23。

验证结果（包含工作区并行功能的最新回归）：

- 后端 `python -m pytest -q --tb=short --maxfail=3 --basetemp <新建临时目录>`：677 passed，42 deselected，146.90s。社区新增25项验收包含13份源档案、未匹配身份、权限、重复确认、草稿恢复/重启、多计划删除/修改/重排/重复、餐后记录、失败回滚、原有SQLite补表及旧草稿兼容。
- `python -m app.tools.integration_smoke --strict`：39 OK，0 pending，0 failed；主链ONB01已改用 `{mode:"auto"}`。`export_contract --check`、`check_architecture` 均通过。
- 前端 `npm.cmd test`：69 passed；`npm.cmd run build` 和 `npm.cmd run contracts:check` 均通过。
- 浏览器：许伯伯首次登录自动匹配三种慢病/三项计划，刷新恢复后确认，正式档案显示正确；未建档身份手工填写后进入本人首页；张伯伯自动匹配后转手工，刷新仍保持手工草稿。登录页支持同一人物另建独立演示家庭；旧浏览器保存的无persona_id家庭只按默认人物处理，不妨碍选择其他人物创建新家庭。
- 测试与浏览器服务均使用独立临时SQLite，未修改已有运行数据库。Windows沙箱内TestClient的asyncio socketpair会挂起，后端验证在沙箱外运行。临时18141/15174验收服务已关闭。

使用：重启后端自动补表/补种，在登录页选择人物，创建演示家庭，点击“安心登录”，核对后确认保存。这里演示的是账号身份映射查询虚构社区库，不提供真实短信注册或人脸身份识别。

### 最终展示入口与提交状态（2026-11-01）

产品登录页现采用正常手机号与角色登录，固定验证码和人物选择由讲解者在后台准备。上节中的人物选择按钮属于实现阶段验收路径；最新入口、账号与准备流程统一见 `docs/演示操作手册.md`。老人登录后的自动匹配、核对保存和手工回退能力保留。

社区功能已作为独立提交 `49137f6` 保存；对话打卡、模型输出重试、用药预检和产品展示整理分别提交。完整批次与验证见 `docs/协作/分批提交记录.md`。本轮提交按开始整理时的已验收快照拆分，之后并行进行的临床样本升级保留在工作区，不与已验收版本混合。
