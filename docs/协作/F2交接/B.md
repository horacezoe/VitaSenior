# F2 B：MiMo TTS 握手与验收

2026-10-31（Asia/Hong_Kong）。**真实 MiMo TTS 已通过正常工厂/AI02/媒体取回，用户已确认“全文清楚、无截断”；ASR 延期。** 用户已确认文字、ASR、TTS 统一采用 MiMo；ASR 供应商选择不代表本轮已接通。

## 基线与协作进度

- 共同起点：`363f6376a63d696ba36b1bc7fc426e8b159dc196`；B 分支 `backend/f2-audio`，独立 worktree `E:/CUHKSZ/project/vitasenior/.audio-work`。
- 已正常合入 A `origin/f2/platform@24debddce9f5f2a88ee68f56f6245f7bba5b4c95`，合并提交 `41906d226adef26cbbac58ac6931dd5b1e86d1d8`，零冲突，包含 A 的 `9f46203` 握手和 C 的 `96177dc`。
- C 最新交接报告：正常工厂/Uvicorn 的真实文字、餐食照片、确认落库、看板/日报、重启及显式 mock 回退均通过；A 已合入复验。此处是 A/C 的证据，不冒充 B 已重复发起供应商请求。
- B 自己的改动仅 `providers/real_audio.py`、用户后续明确新增的 `providers/real_tts.py`、`tests/providers/test_real_audio.py`、按 A 要求提供的独立 `tests/providers/probe_real_tts.py` 和本文件。公共/其他领域文件只来自正常 merge，没有由 B 编辑。
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

提案仍用 F1 精确全文 fixture，未改提案状态机或 60 秒窗口；播放不形成 taken。

## 本机 env 与真实探针

`backend/.env.mimo.example` 已从 C/A 正常合入。B 在自己的 worktree 创建了被忽略的 `backend/.env`，改用 B 的独立数据/端口并补 TTS_*；用户将 MiMo key 填入 CHAT_API_KEY 后，B 按统一账号约定仅在本机将同一个 key 复用到 TTS_API_KEY。密钥未进入代码、命令参数、输出或 Git。`git check-ignore backend/.env` 实际通过。chat=mock 是示例/本探针的配置选择，不表示真实 chat 未实现；本探针只启用真实 TTS，不重复调用 C 的真实理解。

独立探针不被 pytest 收集；显式读 TTS_*，忽略文件里的数据库地址、DATA_DIR 和 chat 选择，始终用自己的临时数据库、真实默认工厂/登录/Runtime/AI02/票据 MEDIA03。仅一次供应商请求，无重试，不调用真实 chat：

```powershell
# backend 工作目录，Python 为 ../../.review-venv/Scripts/python.exe
python tests/providers/probe_real_tts.py --env-file .env --live
# 可选：--text '这是一条新的中文完整播报测试。'
```

也可在进程设置 `LIVE_TTS=1`；无显式启用会退出 2。缺 key/base/model 同样退出 2。成功后 `data/f2-audio-b/evidence/<独立时间戳>/speech.wav` 和 `evidence.json` 保留文本、时间、模型/音色、MIME、时长/字节数、SHA-256、耗时、Runtime 与 `listened=false`，不保存 token/票据/key。真实探针用 TestClient 驱动正常应用，尚不代替真实 TCP/前端设备播放。

应用不自动加载 .env。A 的 run-demo.ps1 默认依赖 backend/.venv，本机实际复用 ../../.review-venv；长期服务应按本机解释器路径显式导入 env 后用单 worker/8022 启动，不改共享脚本来适配 B 工作区。

## 实际检查

环境：Windows / Python 3.11.5 / 原锁定依赖 / HTTPX 0.28.1。默认 pytest 全为替身，付费测试已迁出。下表命令在 backend，python 指 ../../.review-venv/Scripts/python.exe。

| 命令 | 结果 |
| --- | --- |
| `python -m pytest tests/providers/test_real_audio.py -q --tb=short --basetemp=.pytest_cache/f2-b-shared-handshake` | 118 passed / 1 warning / 8.56s（独立探针的两项回归加入前） |
| `python -X utf8 -m pytest tests/providers/test_real_audio.py -q --tb=short --basetemp=.pytest_cache/f2-mimo-null-transcript` | **121 passed / 1 warning / 9.06s**，含真实响应 null transcript 兼容回归 |
| `python -m pytest tests -q --tb=short --basetemp=.pytest_cache/f2-b-integrated-all` | **485 passed / 1 failed / 42 deselected / 1 warning / 146.30s**；唯一失败为下述 A 旧阶段断言，包含 B 的 120 项通过 |
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

1. A 的公共测试 `tests/framework/test_shared_adaptation.py::test_provider_factory_separates_mock_and_real` 仍断言 B 模块不存在（RuntimeError 包含 real_tts.py）。模块现已交付，需由 A 改成有效配置可构造真实实例、非法配置拒启；B 不修改公共断言，也不把错误文案改成旧断言来掩盖阶段变化。
2. A 的 `Settings.tts_timeout_seconds` 当前为固定字段 20.0，尚未读取 TTS_TIMEOUT_SECONDS 环境变量；显式构造 Settings 时能传 timeout。若承诺该可选环境变量，由 A 在配置层处理，B 不另读 env。默认 20 秒不受影响。
3. 新中文 AI02→MEDIA03 与该文件人工实听已通过；下一步仅做前端/真实端口集成验证，不为重复验同一文件扩大供应商请求数量。
4. A 合入 B 后更新公共测试、TTS env 示例和 FAST-05；C 的真实饮食主链继续用现成实现，不重复开发。ASR 只有 TTS 稳定且时间允许才考虑；当前延期，不接转码/新依赖。

官方协议参考：[MiMo TTS](https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/audio/speech-synthesis)、[鉴权与结束原因](https://mimo.mi.com/docs/zh-CN/api/chat/openai-api)。真实 TTS/媒体字节与本机文件人工实听已验；手机 HTTPS/自动播放、真实 TCP 音频联调与 ASR 尚未验收。
