# F2 C：受限饮食理解与 Agent

2026-10-31（Asia/Hong_Kong）。从指定 `363f6376a63d696ba36b1bc7fc426e8b159dc196` 开始，分支 `backend/f2-understanding`。独立 worktree：`C:/Users/horac/Documents/ChatGPT/hackthon Su2026/VitaSenior-f2-understanding`；F1 的 D 盘工作区/数据未改。开工13:56，主链目标16:56，功能截止17:56。

状态：**C_F2_LIGHT_CHAT_VERIFIED / PENDING_A_INTEGRATION**。已发布统一基线仍为 **`f2-demo-v2` → `24debddce9f5f2a88ee68f56f6245f7bba5b4c95`**，其中A已合入C的 `a7eadaf`、`96177dc`；C分支已正常快进同步。本次用户追加的MiMo低开销调用补丁见下节，尚待A合入，不移动既有标签。本机env始终忽略、不上传；公共示例key为空。其余工作继续围绕前端联调阻断修复。

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
