# F2 交接（集成人 A）

基线：`integration/f1` 的 `363f637`，分支 **`f2/platform`**（保留既有数据目录与数据库，不重建）。
本轮：3 小时交主链、4 小时结束后端功能；**2:15 冻结范围**。

## 1. 已完成（第一批，30 分钟内）

| 交付 | 位置 | 状态 |
| --- | --- | --- |
| 前端接入包 | `docs/协作/F2交接/前端接入.md` | ✅ 启动方式、固定契约、错误码、登录→看板 13 步、图片/播放/回执口径、当前边界 |
| 可运行样例 | `backend/app/tools/demo_walkthrough.py` | ✅ `python -m app.tools.demo_walkthrough [--base-url ...]`，逐条打印请求/响应，`WALKTHROUGH_OK` |
| 最小配置/工厂共享提交 | `app/core/config.py`、`app/composition.py`、`app/main.py` | ✅ 已推 `f2/platform`，B/C 直接 merge 即可 |

**Provider 工厂（本轮唯一的共享依赖）**：只切换 TTS，不做通用 provider 平台。

```python
build_agent_providers(settings) -> (chat, asr, tts)   # chat/asr 固定 mock
providers(settings) -> {"chat": "mock", "asr": "mock", "tts": settings.tts_provider}
```

- `TTS_PROVIDER=mock|real`；`real` 时 A 会 `from app.providers import real_tts` 并调用
  `real_tts.build(settings)`——**这个模块由 B 提供**，未提供时启动直接报
  `TTS_PROVIDER=real but app/providers/real_tts.py does not exist yet`，不会假装成功。
- `providers` 状态由实际构建的对象推导，`agent_capabilities.py` 不再保存第二份状态；mock 永远不会
  被标成 real。
- config 只放开 TTS：`CHAT_PROVIDER`/`ASR_PROVIDER` 必须是 mock（ASR 本轮延期）。

## 2. FAST-01–04（发布新标签的门槛）

| 编号 | 含义 | 判定方式 | 当前 |
| --- | --- | --- | --- |
| FAST-01 | 前端可用：地址/启动/固定契约/登录→看板样例 | 前端按 `前端接入.md` 跑通 `demo_walkthrough` | ✅ 文档+脚本+实测 |
| FAST-02 | **真实文字/餐食照片 → 饮食确认落库**（用户本版口径） | `CHAT_PROVIDER=real` 启动、`/runtime.providers.chat=="real"`、真实文字与照片各跑一轮：待确认→确认落库→重试不新增→子女看板/日报同一记录 | ✅ 适配器与供应商实测由 C 完成（`backend/f2-understanding@11445bb`：文字约 3.8s、图片约 11.8s，C 侧 157 passed）；A 已放开并接线，见 §2.1 |
| FAST-03 | 提案播报保留 F1 全文 fixture；无完整音频不计时 | 有匹配语音 → 播报后 60 秒窗口生效；无匹配 → 只有文字、`auto_apply_at` 恒 null | ✅ 回归已覆盖，B 侧 NOTI03 已验 |
| FAST-04 | 完整主链（建档→绑定→饮食确认→看板/日报） | `integration_smoke --strict` 39/0/0 | ✅ |
| FAST-05（加分） | 真实 TTS 接入且标识准确 | `TTS_PROVIDER=real`、`providers.tts=="real"`、`AI02` 返回真实音频 | ⏳ 等 B 的 `real_tts.build`，未完成不影响 FAST-01–04 |

标签策略：FAST-01–04 全绿后再打新标签（例如 `f2-demo-v1`），**不移动 `f1-integrated-v1`**。
未通过项按编号写在下表，不用"部分通过"含混表述。

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
| A 侧真实供应商复跑 | ✅ 已复查（用用户提供的 MiMo key，未入库）：`CHAT_PROVIDER=real` → 生产工厂 → HTTP。纯文字 `AGENT01` **201 / 13.9s**，`providers.chat=real`，正确得出午餐+青菜/豆腐/米饭的待确认 `record_diet`；图片链路 **201 / 4.2s**（空白 1×1 图正确返回"无可记录"，没有伪造动作）；伪造 PNG 字节被供应商拒收时**如实 502 `PROVIDER_ERROR`**，不吞错。真实餐食照片的识别数据仍以 C 的探测为准（A 无照片素材） |
| 真实 TTS（FAST-05） | 等 B 提供 `app/providers/real_tts.py::build(settings)`；工厂已就绪，`TTS_PROVIDER=real` 缺 `TTS_API_KEY/TTS_BASE_URL/TTS_MODEL` 会拒绝启动，模块缺失时也不会假装。**同一 MiMo key 的模型列表含 `mimo-v2.5-tts` / `mimo-v2.5-asr`**，B 可直接对接，ASR 也可顺带解决。完整握手见 §5.1 |
| 手机 HTTPS / 真实设备播放 | 按用户安排延期；当前只验证到字节与票据，未验证真机 `<audio>` 实听 |
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
