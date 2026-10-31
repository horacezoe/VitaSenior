# F2 B：TTS 适配器与集成待办

日期：2026-10-31（Asia/Hong_Kong）。**按用户最新选择改为小米 MiMo；离线适配器已通过，真实 TTS 未验收，ASR 延期。** 等 C 完成 env 示例，再拉取到本地、配置不被追踪的真实 `.env`；本轮未创建/读取密钥文件、未调用真实供应商。A 的共享提交尚未合入，AI02/Agent 生产入口未接线。旧 `6651786` 的 SiliconFlow 候选已被本次实现替换，不保留第二家 provider 或兼容别名。

## 基线与文件

- 共同起点：`363f6376a63d696ba36b1bc7fc426e8b159dc196`。
- 分支：`backend/f2-audio`；worktree：`E:/CUHKSZ/project/vitasenior/.audio-work`，Git 主库位于 `.framework-review`。没有改主库工作区，也没有 reset、清库、移动标签或推送。
- 仅新增 `backend/app/providers/real_audio.py`、`backend/tests/providers/test_real_audio.py` 和本文件。配置/公共协议/路由/依赖/提案状态机未修改。
- B 独立运行约定：在本 worktree 的 `backend` 使用 `DATA_DIR=<backend绝对路径>/data/f2-audio-b`、清空继承的 `DATABASE_URL` 以使用该目录的 `vitasenior.sqlite3`，端口预留 `8022`；本轮未启动持久服务。测试实际使用 `.pytest_cache` 下的独立临时目录，未使用运行库。

## 可调用入口与限制

```python
from app.providers.real_audio import MiMoTTS

tts = MiMoTTS(
    api_key=local_secret,                        # 仅在本机配置，不提交
    model="mimo-v2.5-tts",
    voice="冰糖",                              # 或 mimo_default，需实际确认
    timeout_seconds=20,
    connect_timeout_seconds=5,
)
speech = tts.synthesize(final_text)              # 退出全部 UoW 后调用
# 新的短写 UoW 中重新鉴权，再调用现有 MediaPort.register_generated：
# content=speech.content, mime_type=speech.mime_type,
# duration_ms=speech.duration_ms, purpose="agent_audio"
# 最后由调用方 commit；不得向 provider 传 Session。
```

供应商固定 `https://api.xiaomimimo.com/v1/chat/completions`，用 `api-key` 鉴权；单次非流式请求、不跟随重定向、不重试、不隐式切 mock。待播报原文放在 `messages=[{"role":"assistant","content":text}]`，设置 `audio={"format":"wav","voice":已配置音色}`；从返回 JSON 的 `choices[0].message.audio.data` 严格 Base64 解码。只支持 `mimo-v2.5-tts` 预置音色，不做克隆/设计。官方已下线旧 `mimo-v2-tts`，构造器明确拒绝，不静默替换模型。

构造器要求显式 key/model/voice，不读取环境、不自动加载 `.env`、构造时不联网。9 个已公布音色 ID 可配置其中一个，请求 `voice_id` 只能为空或等于该配置。`冰糖` 是中文音色；`mimo_default` 随集群映射，示例尚未实听。变量名最终等 C/A 示例统一，不另建配置入口。本次 `git check-ignore --no-index .env .env.local` 在 backend 运行，输出仅 `.env`：已有忽略规则覆盖 `backend/.env`；最终若使用其他文件名，应同步检查实际忽略规则。

复用 `TTSProvider` / `Speech`：`tts.name="mimo"`、`tts.is_mock=False`；返回 `Speech.is_mock=False`、`mime_type="audio/wav"`、24 kHz / 16-bit PCM / mono 或 stereo，时长由完整帧计算。原文逐字传入并保存在 `speech.text`，不截取、分段、添加控制标签或使用固定录音。Demo 上限 **200 个 Python 字符**（含空白）；超限整段 `422 VALIDATION_ERROR`，保留全文显示，公开请求 DTO 的 5000 字限制不改。

HTTP 只接受 JSON，响应体限 20 MiB + 64 KiB（涵盖 Base64 和包络）；解码后最多 15 MiB / 120 秒。拒绝 JSON 错误包、缺音频/多 choice、非 `stop` 的 finish_reason（含 length/过滤/复读截断/缺失）、非法 Base64、错误模型，以及可选 transcript 与全文不符。校验完整 RIFF、全部 chunk 边界、唯一 fmt/data、PCM 编码/采样率/块对齐/帧长、HTTP 声明长度；拒绝空、全零静音、类型不符或截断音频。不转码；容器完整及 stop **不能证明模型逐字读全或音质可接受**，仍需真实请求与人工实听。

`synthesize` 保留同步协议，内部用 HTTPX AsyncClient + Python 3.11 `asyncio.timeout` 保证请求头及整个响应体总计 20 秒可取消，连接最多 5 秒。该内部选择与计划“同步 HTTP”字面有差异，用于避免每次 read 都重新获得 20 秒；不改变业务入口。现有 FastAPI 同步路由在线程池调用；已有事件循环的调用方也须在线程池调用同步协议。

错误复用 `AppError`：超时/408/504 → `504 PROVIDER_TIMEOUT`；401/403/429/其他供应商失败或无效音频 → `502 PROVIDER_ERROR`。上游鉴权失败不误报为用户登录失效；`details` 仅含 provider/reason/上游状态码。429/5xx/网络故障标记 retryable，但不自动重试。错误不公开供应商响应体、密钥或输入文字。输入无效/超长/音色不符为 422，属于 TTS 文字降级而非成功音频。

官方参考：[TTS 用法/请求与音频路径](https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/audio/speech-synthesis)、[鉴权/响应结束原因](https://mimo.mi.com/docs/zh-CN/api/chat/openai-api)、[模型下线公告](https://mimo.mi.com/docs/zh-CN/updates/deprecate)。仅核对文档，尚无真实请求；如实际响应与契约假设不一致，应凭真实证据调整，不能放宽截断/无音频失败规则冒充通过。

## A / C 必须完成的接线

接实际入口前先正常合入 A 发布的共享提交，再由 A/C 在自己的白名单接线；本分支没有替代公共工厂或测试覆盖生产配置。

1. **A/C**：在统一 env 示例和工厂中选择 `MiMoTTS`，默认仍 mock，真实配置缺 key/model/voice 明确失败；runtime 从实例 name 生成。建议示例采用 `MIMO_API_KEY`、`MIMO_TTS_MODEL=mimo-v2.5-tts`、`MIMO_TTS_VOICE=冰糖`，最终名以发布示例为准，勿沿用已下线 TTS/理解模型。`httpx==0.28.1` 已在完整 lock，但 pyproject 只列为 test extra，运行依赖由 A 处理。本分支不改配置/依赖。
2. **A/C**：`application/agent_flows.py::tts` 当前返回硬编码 `provider='mock', is_mock=True`，须取实际 `state.agent_tts.name` 和 `speech.is_mock`；仅换 provider 实例会错误标记。保留原来的短读鉴权→事务外 TTS→短写重新鉴权与媒体登记流程。
3. **C / A 共享定义**：`services/agent_service.py::record_turn` 的 TTS 来源仍硬编码 `mock`。现有 `Speech` 没有 provider 字段，A/C 应决定最小传递方式并集中修改；不要由 B 复制/替换 Speech。Agent 最终文字和 `speech.text` 不同就不登记错误音频；需要补播时前端以最终文字调用 AI02，不重复执行确认动作。
4. **C**：`agent_flows.turn` 的 TTS catch 目前只接 501/502/504；本适配器的超长输入会 422。仅在合成阶段处理该可预期校验失败，保留最终全文、`audio_asset_id=null`、`degraded=['tts_unavailable']`，不吞其他业务错误。AI02 无音频时返回明确错误，前端保留自己已有文字。
5. **A/C**：接线后补 AI02→MEDIA03、Agent 成功来源/失败降级回归，并验证供应商等待时另一个真实请求可写库。本分支只证明独立适配器和现有 MediaPort/MEDIA03 可以配合，不能替代这些入口验收。

提案继续 F1 精确全文 fixture；不使用本适配器改提案状态/语音或启动 60 秒窗口。不把播放当服药。ASR 未新增，既有 mock 仍仅接受精确已知录音，未知录音不能得到固定 transcript。

## 实际验证

环境：Windows / Python 3.11.5 / 既有 `.review-venv` / HTTPX 0.28.1 / Pytest 8.4.2。无新依赖。以下命令工作目录为本 worktree 的 `backend`，`python` 指 `../../.review-venv/Scripts/python.exe`。

| 已运行命令 | 实际结果 |
| --- | --- |
| `python -m pytest tests/providers/test_real_audio.py -q --tb=short -rs --basetemp=.pytest_cache/f2-mimo-audio-first` | **105 passed, 1 skipped, 1 warning in 2.87s** |
| `python -m pytest tests -q --tb=short -rs --basetemp=.pytest_cache/f2-mimo-audio-full` | **404 passed, 1 skipped, 42 deselected, 1 warning in 100.73s** |
| `python -m app.tools.export_contract --check` | OpenAPI matches `4b7ade26f590902a4eb131920589184b95e0b54a293e9df80ac9f8aa4859532c` |
| `python -m app.tools.check_architecture` | Architecture OK |
| `python -m pip check` | No broken requirements found |

覆盖 MiMo 鉴权/assistant 全文/audio 参数、JSON/Base64/结束原因/返回模型/可选 transcript、新中文来源、200 字边界、音色限制、超时/连接失败/401/403/429/5xx、无重试/重定向、无效/截断 WAV、字节限额与流关闭、总期限实际取消、真实 MediaPort/MEDIA03 完整字节及权限。测试 PCM 仅为诊断数据，不能算真实合成或实听。唯一 warning 为既有 Starlette/httpx 弃用提示。

默认验证显式设 `VITASENIOR_LIVE_TTS=0`，没有供应商网络请求。42 deselected 为既有 F0 阶段用例；1 skipped 为未启用的真实请求。严格联调脚本和独立网络烟测本轮未重跑。

## 显式真实验证命令与未验收范围

等 C/A 示例发布并正常合入后，在本机安全配置未追踪 `backend/.env`，按团队约定显式导入到进程。测试当前读取 `MIMO_API_KEY`、`MIMO_TTS_MODEL=mimo-v2.5-tts`、`MIMO_TTS_VOICE=冰糖`，可另设 `VITASENIOR_LIVE_TTS_TEXT`（新中文短文本 ≤200 字）；如最终示例命名不同，同步本测试，不添加第二套自动 env 加载。运行前用 `git check-ignore backend/.env` 确认实际文件仍被忽略，不输出/提交其内容。

```powershell
$env:VITASENIOR_LIVE_TTS = '1'
python -m pytest tests/providers/test_real_audio.py -k live_tts -q -s -rs --basetemp=.pytest_cache/f2-mimo-live-unique
Remove-Item Env:VITASENIOR_LIVE_TTS
```

**以上真实命令未运行**：按用户安排等待 C 的示例及本地凭据。开启后仅一个请求（以可能计费处理），缺 key/model/voice 则明确 skip。成功后在测试临时目录保留 `live-tts.wav` / `live-tts.json`：文本、时间、模型/音色、MIME、时长、字节数、SHA-256、耗时、`listened=false`；同时走 MediaPort/MEDIA03。每次用新的 basetemp 保留实听材料，勿指定运行数据目录（pytest 会清理同名旧 basetemp）。

未验收：真实供应商合成与完整读文、模型/音色账号权限、AI02/Agent 真实接线及来源标记、目标手机/浏览器实听和自动播放权限、HTTPS、真实 ASR 原生录音。TTS 尚未真实稳定且没有目标设备录音，本轮不扩展 ASR、不做转码。前端初版继续文字/照片；语音失败时全文可见并明确降级。
