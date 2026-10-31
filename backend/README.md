# VitaSenior F0 后端

本阶段是供下一阶段并行开发的公共基线，不是业务完成版本。Python + FastAPI + SQLAlchemy + SQLite，无前端改动，无真实模型/ASR/TTS/推送调用。只有 SYS01、SYS02、AUTH01、AUTH02、AUTH04 已实现；另 40 个 P0 接口校验请求/权限后返回 `501 MODULE_NOT_IMPLEMENTED`。实际状态见 `../docs/协作/框架交接记录.md`。

## 安装

F0已验证 Windows / Python 3.13.9，F1另在Windows / Python 3.11.5复验通过。项目声明支持3.11–3.13，其他版本/系统尚未实测。`requirements.lock`固定完整运行及测试依赖。原框架标签为`framework-v1`；本轮业务从`f1-reviewed-v1`共同开始，按[本轮验收说明](../docs/协作/F1验收与开工说明.md)和正式任务单执行。A0完成后合入`f1-shared-v1`。

```powershell
cd D:\codes\VitaSenior\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python -m pip check
```

无需激活时，将下文 `python` 换为 `.\.venv\Scripts\python.exe`。可选 `python -m pip install --no-build-isolation --no-deps -e .`；直接从 backend 目录运行不需要 editable 安装。

## 配置

配置直接读进程环境变量，`.env.example` 是说明文件，不会自动加载 `.env`。无任何供应商密钥可启动。默认 DATA_DIR 为 backend/data，数据库为其下 vitasenior.sqlite3。启动不会重置数据库或自动植入 seed。

```powershell
$env:APP_ENV='demo'
$env:DATA_DIR='D:/codes/VitaSenior/backend/data'
$env:SCANNER_ENABLED='false'
$env:CORS_ORIGINS='http://localhost:5173'
```

`DATABASE_URL` 可覆盖数据库文件（仅支持文件 SQLite URL，例如 `sqlite:///D:/vita-a/vitasenior.sqlite3`）。每个 worktree 必须用独立 DATA_DIR、DATABASE_URL 和端口。DATA_DIR 及数据库路径父目录由初始化创建；运行数据与 .env 均不提交。

`APP_ENV` 支持 development/demo/test；`PUBLIC_BASE_URL` 默认 http://localhost:8000，供 F2 演示入口使用；`APP_TIMEZONE` 冻结 Asia/Hong_Kong。`CHAT_PROVIDER`、`ASR_PROVIDER`、`TTS_PROVIDER` 当前只允许 mock，但 F0 尚未实现 mock 业务，因此 runtime.providers 如实为 not_implemented。`WEB_PUSH_ENABLED` 仅允许 false。设置真实 provider 或启用推送会明确拒绝启动。没有“静默回落为假成功”的模式。

## 初始化和登录

```powershell
python -m app.seed --mode framework
```

命令建表并输出真实 user_id / elder_id；只在缺失时建立四个固定测试账号，不覆盖已有档案或恢复已撤销绑定。若手机号被其他 demo 占用会报错回滚。验证码统一为 `123456`，不发短信。

- `19900000001` / elder：测试老人。
- `19900000002` / child：已绑定该老人。
- `19900000003` / child：未绑定子女。
- `19900000004` / elder：陌生老人。

framework seed 不创建假 token、不消费绑定码、不建立 14 天业务历史。DEMO01 的独立观众家庭留给 F2。

```powershell
$body = @{phone='19900000001';role='elder'}
$challenge = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/auth/code -ContentType application/json -Body ($body | ConvertTo-Json)
$loginBody = $body + @{challenge_id=$challenge.data.challenge_id;code='123456'}
$login = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/auth/login -ContentType application/json -Body ($loginBody | ConvertTo-Json)
$headers = @{Authorization="Bearer $($login.data.access_token)"}
Invoke-RestMethod http://localhost:8000/api/v1/me -Headers $headers
Invoke-RestMethod http://localhost:8000/api/v1/runtime -Headers $headers
```

challenge 5 分钟、一次消费；每个演示账号每 5 分钟最多签发 5 次 challenge。会话为随机不透明 token，DB 仅存 SHA-256 摘要，48 小时过期，重启仍有效。验证码是演示机制，不是生产短信身份认证。

## 启动

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

也可使用 `--factory app.main:create_app` 形式。浏览器访问 `/docs`、`/openapi.json`；公开健康检查 `/api/v1/health`，其他 URL 前缀 `/api/v1`。只开一个 worker。F0 默认关闭扫描器；设置 SCANNER_ENABLED=true 后仅运行每 5 秒的可关闭 tick 骨架，不产生真实提醒、60 秒应用或任何模型调用。Ctrl+C 由 lifespan 取消循环并释放 DB engine。

## 演示机准备（重要）

F1 没有迁移工具，`create_all` 只建缺失的表、**不会给旧表加列**。启动时会校验实际表结构，
若 `DATA_DIR` 里是旧库，会直接报 `DATABASE_SCHEMA_OUTDATED: ... missing daily_tasks(cancelled_at)`
这类明确错误而不是在后面冒出离奇的 SQL 错误。

所以演示机一律**从空数据目录开始**：

```powershell
$env:DATA_DIR = 'D:/vitasenior-demo'      # 换一个新目录，或先整个删掉旧目录
$env:MEDIA_TICKET_SECRET = '<至少16位随机串>'   # 媒体链接签名密钥，别用示例值
$env:SCANNER_ENABLED = 'true'             # 需要自动到期结算时打开
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

演示账号不用手工造：`POST /api/v1/demo/experiences` 每次生成一对老人/子女手机号与未确认草稿，
随后用 AUTH01/AUTH02 正常登录即可。数据库与媒体文件都在 `DATA_DIR` 下，删目录即完全重置。

## 验收

工作目录 backend，使用隔离测试数据，不要把运行 DB 交给测试。

```powershell
python -m pytest tests/framework -q
python -m pytest tests -q                 # 框架 + 各领域业务测试
python -m app.tools.export_contract --check
python -m app.tools.check_architecture
```

三轮集成验收的联调脚本（临时库、进程内）：

```powershell
python -m app.tools.integration_smoke            # OK / PENDING / FAIL 三态报告
python -m app.tools.integration_smoke --strict   # 有 PENDING 也判失败，B/C 端口落地后作为合并闸门
python -m app.tools.integration_smoke --base-url http://127.0.0.1:8001
```

`PENDING` 表示该步骤真实返回 501 MODULE_NOT_IMPLEMENTED（依赖端口仍是占位），**不计为成功**；
`FAIL` 是契约或数据不一致。脚本只用自己的临时 DATA_DIR，不写运行库。

测试强制 tmp_path 数据库、关闭扫描器；FakeClock 推进时间，不等待真实 60 秒。覆盖 FG01–FG10、45 个 P0 operation_id、40 个占位、真实账号/资源权限、持久化登录、唯一约束、失败回滚、并发幂等、契约篡改和跨领域导入注入。没有完成总体计划 AC01–AC14 业务验收。

```powershell
# 只有集成人审核契约变更后才重导出，普通验收用 --check
python -m app.tools.export_contract
Get-FileHash contracts/openapi.json -Algorithm SHA256
```

## 公共代码与接手

- app/main.py：唯一 create_app/settings/clock/services 注入入口，lifespan 初始化 DB，统一 JSON/error/request_id/CORS；OpenAPI 导出不启动 lifespan、不创建运行 DB。
- app/core：DB、UTC 类型、UoW、鉴权、时钟与幂等。UnitOfWork(write=True) 使用 BEGIN IMMEDIATE，调用方提交，未提交退出/异常均回滚。读事务用 write=False。
- app/contracts/context.py：唯一 Actor、ElderAccess；SourceRef 复用 schemas/common.py。bundle.py 为 typed ServiceBundle；ports.py 是完整签名，所有业务 port 默认抛 501，只有 access 已可用。
- app/composition.py：唯一具体实现组装入口。routers/application 不能导入 services；跨领域 services 只能使用 port。主 app 可注入 replace(compose(), reports=...) 等测试替身。
- app/models、schemas、contracts、core、main、composition、requirements.lock、contracts/openapi.json 和 tests/framework 在 F2 为公共冻结文件，由集成人统一维护。
- application/{identity,health,agent}_flows.py：本阶段只有明确未实现入口，F2 用具名 flow 取代。routers 中已有真实参数、成功响应和权限检查；服务占位不可直接当作业务能力。

幂等调用顺序：同一写 UoW 内检查实时权限 → Idempotency.execute(...operation=确定性业务写入) → 调用方 commit。scope 为 actor+method+path+key，body 必须传入归一化的 JSON 数据，查询参数影响写结果时应一并计入 body（例如 expected_version）。重复请求返回原业务 data/状态，新请求有自己的 meta；同 key 异体 409。失败不缓存，不在长模型请求期间持有写锁。48 小时后按新请求处理。

资源不存在/无权读取子资源均返回 404；elder_id 越权与未知老人统一 403，避免泄漏。子女写档案/计划/设置 403 PROPOSAL_REQUIRED；老人独占的打卡、通知回执和动作确认不向子女开放。写校验使用同一实际写 Session，不能用前置的另一连接代替。

下一阶段主负责人先从 framework-v1 读取交接记录，发布 A/B/C 白名单与任务单，再开三个 worktree。A 接 identity/auth 后续、建档、绑定、媒体、提案；B 接 health/checkin、计划、通知、汇总及 scheduler；C 接 agent/memory 和 providers。不得另建第二套 DB、DTO、应用或绕过 port。当前未启动任何业务 Agent。
