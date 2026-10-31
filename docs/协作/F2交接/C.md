# F2 C：受限饮食理解与 Agent

2026-10-31（Asia/Hong_Kong）。从指定 `363f6376a63d696ba36b1bc7fc426e8b159dc196` 开始，分支 `backend/f2-understanding`。独立 worktree：`C:/Users/horac/Documents/ChatGPT/hackthon Su2026/VitaSenior-f2-understanding`；F1 的 D 盘工作区/数据未改。开工13:56，主链目标16:56，功能截止17:56。

状态：**C_REAL_DIET_VERIFIED_ISOLATED / A_CHAT_WIRING_REQUIRED**。用户已在本机env配置MiMo key，文字/餐食图片各一次真实请求及确认落库链路均已通过。该证据是明确注入真实适配器的隔离探测，**不代替A默认real chat工厂验收**；F2整体尚不发布完成标签。本机 `backend/.env` 被Git忽略、绝不上传；公共 `.env.mimo.example` 的CHAT_API_KEY保持为空，同事自行复制填写。

## 已交付与入口

- `providers/real_understanding.py::RealUnderstanding`，沿用 `UnderstandingProvider.plan(request, snapshot) -> Plan`。单个显式配置的Chat Completions接口，无SDK/新依赖/重试/自动mock回退；连接5秒、供应商总期限20秒（含持续接收响应），响应128KiB上限。默认单元测试全为HTTP替身，不请求付费API。
- 只接收严格的饮食候选JSON。模型不能填写老人/日期/ID/版本/权限/动作或记忆；服务器用当前上下文构建现有DietAction，全部待确认，source沿原确认入口agent_confirmed。明确餐次缺失/歧义追问；非饮食或历史日期引导已有页面/API，不准备服药任务。真实模式拒绝mock_fixture_id。
- `planning.ImageInput` 是已授权字节，不含路径/票据。flow短鉴权获取MediaPort句柄，事务外读取并发送Base64；每图5MiB、合计10MiB、最多沿原schema的3图。最终写入重新验真实会话、资源、档案和记忆版本。只向供应商发本轮用户文字/图片，不发档案、记忆或家庭身份。
- `Plan.chat_provider`、Agent/AI02/ASR来源不再写死mock；TTS失败保留真实文字/tts_unavailable。45秒Agent预算不足时不启动新的20秒真实TTS；截止后不提交成功结果。最终查询/绑定/确认回复若变化仍走既有AI02补播，不重复执行工具。

供A直接构造（配置/工厂/默认启动/Runtime仍由A维护）：

```python
from app.providers.real_understanding import RealUnderstanding
chat = RealUnderstanding(
    api_key=settings.chat_api_key,
    base_url=settings.chat_base_url,  # HTTPS API root, e.g. .../v1
    model=settings.chat_model,
)
# .name == "real", .is_mock == False
```

建议A统一新增 `CHAT_API_KEY / CHAT_BASE_URL / CHAT_MODEL`，CHAT_PROVIDER=mock|real；真实缺字段启动明确失败。保留默认无key全mock，ASR/TTS独立选择；不改OpenAPI。C已负责flow/Plan/AgentService的来源改动，A不要再实现另一套。

## A共享提交的准确缺口

已正常merge `f2/platform@9c41389`，合并提交 `20cddd3`；C应用实现提交 `fa245e292c66babcab92c51b48f86c8521337d99`，真实探测脚本提交 `37632b57e2f9d329ddcaea448aaa3455ce25efdc`。当前Settings仍拒绝CHAT_PROVIDER=real，build_agent_providers只允许TTS切真实，Runtime按settings返回chat=mock。请A放行并构造上述真实chat实例、按实际实例生成Runtime；同步公共测试中“chat=real必须拒绝”的旧断言。C不会修改公共文件来绕过此门槛。

用户本版FAST-02是**真实文字+真实餐食照片确认落库**，真实TTS是优先争取。A当前交接把TTS列为必交、把mock主链列成真实理解通过，与用户最新版不同，请按用户本版验收，不用mock/替身结果替代供应商通过。

## 验证与真实探测

2026-10-31（Asia/Hong_Kong），MiMo官方API `https://api.xiaomimimo.com/v1`，请求模型 `mimo-v2.6-flash`：

- 文字“今天早餐吃了鸡蛋和全麦面包，请准备记录”：**C_LIVE_DIET_TEXT_OK**，3834ms。
- 餐食JPEG（800×533、127927字节）经真实授权媒体上传、Base64输入：**C_LIVE_DIET_IMAGE_OK**，11796ms。公开[演示图片来源](https://images.unsplash.com/photo-1512621776951-a57141f2eefd?w=800&q=85)；SHA-256 `c048bf36cfa7810c2eb25b93267fef6588d80d5f66dc305d70afe42c6a48aa7f`。只保留在被忽略的data目录，不上传Git。
- 两次各自使用临时SQLite，pending阶段记录数不变；明确确认后各一条source=agent_confirmed记录；轮次重放不调用模型、重复确认不新增；子女看板/日报核对同一checkin。上述耗时包含Agent、确认/重放和看板/日报校验，并非纯供应商延迟。实际仅2次模型请求，没有重试或mock回退。
- Wikimedia原图片源在本机下载超时，改用上述公开图片；这个下载失败没有计为模型通过。实际模型网络正常，不放宽20秒总期限。

已运行（Python3.13.9，D盘既有venv，临时SQLite/FakeClock）：C全量157 passed（24.91s）；全量361 passed / 42 deselected（77.42s），无失败/xfail；严格三轮39 OK / 0 PENDING / 0 FAIL；真实默认Uvicorn网络烟测C_NETWORK_SMOKE_OK。契约/架构/依赖检查通过，OpenAPI SHA-256仍为 `4b7ade26f590902a4eb131920589184b95e0b54a293e9df80ac9f8aa4859532c`。测试替身之外，A/B/C业务端口和登录/绑定/媒体/记录/看板是真实实现，测试没有偷偷装到生产工厂。唯一warning为既有Starlette/httpx弃用提示。

```text
python -m pytest tests/agent -q --tb=short --maxfail=1 --basetemp=.pytest_cache/c-f2-agent-final
python -m pytest tests -q --tb=short -rx --maxfail=1 --basetemp=.pytest_cache/c-f2-all-final
python -m app.tools.integration_smoke --strict
python tests/agent/smoke_network.py
python -m app.tools.export_contract --check
python -m app.tools.check_architecture
python -m pip check
python tests/agent/probe_real_diet.py --env-file .env --live --mode text
python tests/agent/probe_real_diet.py --env-file .env --live --mode image --image data/c-f2-probe-assets/unsplash-meal.jpg
```

本机沙箱默认临时目录不可写且异步事件循环曾停滞；已停止自己的停滞pytest，改为正常Windows执行环境与上述工作区内basetemp。该环境失败不计业务失败或通过，不放宽测试。

同事自行填写本机key后可显式复验；默认both模式仅文字/图片各一次，单独复验可用--mode text/image：

```powershell
# 将 .env.mimo.example 复制为被Git忽略的 .env，并在本机填写 CHAT_API_KEY
# 仅这个探测命令显式读取文件；正常应用仍不会自动加载.env
python tests/agent/probe_real_diet.py --env-file .env --live --image <演示餐食照片路径>
```

该命令使用临时数据库、真实A/B/C端口和**明确注入的真实适配器**；不代替A默认工厂/网络启动验收。无 --live/LIVE_UNDERSTANDING=1 不请求供应商，不打印密钥/token/票据；已验证--help、不带--live时拒绝（退出2）以及上述两次实际调用。仅读取CHAT_*与LIVE_UNDERSTANDING，忽略.env中的数据库地址，防止误用运行数据库。

协议参考官方[图片输入](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/multimodal-understanding/image-understanding)和[JSON输出](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/text-generation/structured-output)。本机账号的文字/图片已实测通过；同事账号仍需自行验证权限，不把文档或替身测试视为其账号已可用。

仍未验收：A默认real chat装配/Runtime、真实音频、手机实听/HTTPS。图片需明确“今天午餐”等餐次文字；模型不凭菜品推测餐别。运动/药物等原业务API保持可用，真实自然语言覆盖延期，不扩展新意图/记忆机制。A接线后只需用同一适配器和flow重跑默认配置/网络门槛，不再重复实现C解析/执行器。
