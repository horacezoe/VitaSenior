# F2 C：受限饮食理解与 Agent

2026-10-31（Asia/Hong_Kong）。从指定 `363f6376a63d696ba36b1bc7fc426e8b159dc196` 开始，分支 `backend/f2-understanding`。独立 worktree：`C:/Users/horac/Documents/ChatGPT/hackthon Su2026/VitaSenior-f2-understanding`；F1 的 D 盘工作区/数据未改。开工13:56，主链目标16:56，功能截止17:56。

状态：**C_ADAPTER_IMPLEMENTED / LIVE_NOT_RUN / A_CHAT_WIRING_REQUIRED**。用户确认目前还没有模型账号配置，正在向同事获取；实际供应商文字/图片请求均未运行，FAST-02未通过，不发布F2完成标签。

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

已读取 `f2/platform@9c41389`：当前Settings仍拒绝CHAT_PROVIDER=real，build_agent_providers只允许TTS切真实，Runtime按settings返回chat=mock。请A放行并构造上述真实chat实例、按实际实例生成Runtime；同步公共测试中“chat=real必须拒绝”的旧断言。C不会修改公共文件来绕过此门槛。

用户本版FAST-02是**真实文字+真实餐食照片确认落库**，真实TTS是优先争取。A当前交接把TTS列为必交、把mock主链列成真实理解通过，与用户最新版不同，请按用户本版验收，不用mock/替身结果替代供应商通过。

## 验证与真实探测

已运行（Python3.13.9，D盘既有venv，临时SQLite/FakeClock）：C全量154 passed；随后新增截止保护，F2专项60 passed。最终合入A后的完整输出待本文件收尾更新。测试替身之外，A/B/C业务端口和登录/绑定/媒体/记录/看板是真实实现，测试没有偷偷装到生产工厂。

```text
python -m pytest tests/agent -q --tb=short --basetemp=.pytest_cache/c-f2-agent
python -m pytest tests -q --tb=short -rx --basetemp=.pytest_cache/c-f2-all
python -m app.tools.integration_smoke --strict
python tests/agent/smoke_network.py
python -m app.tools.export_contract --check
python -m app.tools.check_architecture
python -m pip check
```

本机沙箱默认临时目录不可写且异步事件循环曾停滞；已停止自己的停滞pytest，改为正常Windows执行环境与上述工作区内basetemp。该环境失败不计业务失败或通过，不放宽测试。

拿到账号后显式启用，仅用非隐私演示照片，最多文字/图片各一次实际模型请求：

```powershell
# 使用本机环境配置 LIVE_UNDERSTANDING=1、CHAT_API_KEY、CHAT_BASE_URL、CHAT_MODEL
python tests/agent/probe_real_diet.py --image <演示餐食照片路径>
```

该命令使用临时数据库、真实A/B/C端口和**明确注入的真实适配器**，验证pending阶段不落记录、确认一次、重试不重写、source与子女看板/日报同一记录。它不代替A默认工厂/网络启动验收。无显式开启不会请求供应商，不打印密钥/token/票据；当前仅验证了--help，真实调用未运行。

协议准备参考官方[图片输入](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/multimodal-understanding/image-understanding)和[JSON输出](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/text-generation/structured-output)；不据文档推定本机账号/模型已开通。供应商/model/baseURL由现有账号决定，目前未获提供。

仍未验收：真实文字/照片、A默认real chat装配、真实音频/手机实听/HTTPS。图片需明确“今天午餐”等餐次文字；模型不凭菜品推测餐别。运动/药物等原业务API保持可用，真实自然语言覆盖延期，不扩展新意图/记忆机制。
