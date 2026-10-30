# B 健康域交接

日期：2026-10-31。当前分支 `backend/health`；A先前指出的七个health接口均已启用，health共16项能力为true。B剩余路由与新模型适配已完成；**NOTI03仍为false，完整P0尚未验收**，原因是A的提案音频只播放提示音，不能当作实际修改内容的完整播报。另有一项A设置提案未来目标不同步的明确strict xfail，不能计为通过。

## 1. 基线与提交

- 独立checkout：`E:/CUHKSZ/project/vitasenior/.health-work`；远端：[backend/health](https://github.com/horacezoe/VitaSenior/tree/backend/health)。根目录原文件、`.framework-review` 和他人的运行库未改。
- 起点：`f1-reviewed-v1` → `1034c7698de4394b3e7695a3a820df2dcfeaf28b`，其父提交为已复验 `497fc4ce6ede5ee951c57cd06913197391633f56`。
- A0：`f1-shared-v1` → `10d51af92715354a2ecd1d5469810272a406c621`，正常merge `aae25c4`。
- A1/A2：正常merge `72d7610` 为 `998ec83`。
- 最新共享集成：正常快进 `integration/f1@51dc555`，包含A的真实组装、B ports、Task/History绑定、新模型以及C2启用。
- 最新C：正常merge `backend/agent@1e31bb6` 为 `25925ad`，包含C用药任务ID持久化及版本复核修正。
- 最后fetch又合入A文档更新 `integration/f1@6774083`（仅接口补充与A交接，业务代码与最终266项验证一致）。其7.1将提示音等同完整播报的描述仍需按原业务约束修正，B不据此开启NOTI03。

| B批次 | 提交 |
| --- | --- |
| 初批B1计划/任务/打卡/汇总服务 | `9299f2c` |
| B2回执/扫描/已有port HTTP协调 | `6ef7e66` |
| 演示历史与未来目标边界 | `b1535f8` |
| 真实A窗口/拒绝/重启、Clock注入检查 | `9cfe39b` |
| 首次交接 | `8fc6289` |
| 剩余路由、新模型、亲情语音、16项激活 | `b8b064a` |
| 合入最新C | `25925ad` |
| 稍后提醒恢复、typed flow协调 | `be0ae4c924fc73801e2c365764cf9447ccd36d54` |

全部正常merge/快进，不reset、不移动发布标签。B未直接编辑公共文件。

## 2. 当前可调用接口

已启用并有默认组装真实HTTP验证：

| 编号 | 行为 |
| --- | --- |
| PLAN01–03 | 计划列表/创建/合并校验后更新；乐观版本；子女直接写拒绝 |
| SET01–02 | 设置读取/本人更新，与Profile共用版本；未来目标及记忆来源同tx更新 |
| TASK01 | 日期目标快照；复用CheckinService.today；批次区分已生成零目标与从未生成 |
| REC01–04 | 类型分页、同餐替换、运动多条、具体药物任务唯一、纠正与软取消 |
| REPORT01 / DASH01 / CAL01 | 共用计算入口；明确taken、明确not_taken、未记录区分；记忆上下文来自真实C |
| NOTI01–02 | 25秒可见心跳/多页有效性；列表无送达副作用、分页与权限隔离 |
| NOTI04 | 本人录音优先、亲情预设文字与匹配的真实中文演示语音、明确文字降级 |

NOTI03的服务与flow已实现，测试验证顺序/幂等/可见性/多次播放/同事务调用A窗口/播放不等于taken。公开能力暂未开启，因为该入口同时覆盖修改提案；A当前的0.8秒双音不能作为本次修改已播报的证据。NOTI03普通提醒在隔离验收时显式开启测试，不冒充正常部署已经启用。老人明确接受/拒绝提案仍可使用A CHANGE04，不需要虚构播放。

实际内部port：

```python
services.medication.import_draft(tx, actor, elder_id, confirmed_plans)
services.medication.apply_change(tx, actor, elder_id, operation, target_id, patch, expected_version)
services.medication.get_plan(tx, actor, plan_id)
services.medication.list(tx, actor, elder_id, active)
services.medication.settings(tx, actor, elder_id)
services.medication.update_settings(tx, actor, elder_id, expected_version, patch)
services.tasks.today(tx, actor, elder_id, hk_day)
services.history.import_demo_history(tx, actor, elder_id, demo_id=demo_id, days=14)
services.checkins.create_or_update(tx, actor, elder_id, payload, checkin_id)
services.checkins.list(tx, actor, elder_id, hk_day, category, limit, cursor)
services.checkins.cancel(tx, actor, elder_id, checkin_id, expected_version)
services.reports.daily(tx, actor, elder_id, hk_day)
services.reports.dashboard(tx, actor, elder_id, hk_day)
services.reports.calendar(tx, actor, elder_id, month)
services.notifications.enqueue(tx, actor, source_key, payload)
services.notifications.handle_event(tx, actor, notification_id, event, clock.now())
services.notifications.scan(tx, clock.now())  # 系统入口，不伪造Actor
```

所有入口使用调用方同一tx；服务不commit/rollback/另开连接。flow在写事务内重新验证真实会话/访问权，成功业务与幂等结果一次提交。TASK/report物化使用BEGIN IMMEDIATE串行化，C也已修复先持久化用药任务ID再退出事务调用provider。

## 3. 重要行为与数据约定

- DailyTask.cancelled_at软停用，只处理尚未发生、无记录、未送达的未来任务；历史与已确认快照保留。删时段/停用计划不删FK引用行，重加未来slot复用原行。
- DailyGoalBatch按elder/date/category持久化；当前/未来正常物化，历史未生成日期不从新计划回填。显式计划/设置变更可更新未来目标，过去分母不被重写。
- 新计划/改期不补造已过去的固定义务；餐后无餐时waiting_for_meal，纠正/取消餐食后按保存的计划快照重算时间。已送达通知不回退、不重复来电。
- 记录修订JSON重新赋值；纠正/取消调用C来源失效，与业务和幂等同tx。真实C记忆观察失效与看板同步已有HTTP回归。
- 旧存储中不合法的计划（例如空slots）返回422，不放宽schema；合法schedule patch可修复，失败不增加版本。
- 演示历史只在确认的同一demo家庭显式导入，source=demo_seed，稳定source_key去重；不覆盖用户记录、不生成历史来电、不猜多药物计划的fixture映射。
- 亲情录音经MediaPort.assert_owned_voice核对上传者；受控字节在事务外读取，再通过A的媒体port登记到目标家庭，老人可正常取回。录音优先于模板。
- fixtures/health四个WAV由离线Windows SAPI生成，含明确“模拟”，显示文本与实际语音匹配且有SHA-256；服务器不依赖SAPI。任意未匹配文字保留原文、audio_asset_id=null，不返回无关语音。
- 完整播放每次使用独立event_id，达到repeat_count才置played；相同ID不累计。播放/handled都不创建服药记录。snoozed截止持久化，扫描到期只恢复open，不重设送达/播放。
- 系统扫描只生成当天待办，不调用TTS/推送、不创建用户Actor。A在同一tick内协调它和ChangePort.apply_due；未启动第二套扫描循环。

## 4. 实际验证

Windows / Python 3.11.5 / 既有 `.review-venv` 与锁定依赖，无新依赖。pytest全部tmp_path SQLite，基目录为本checkout的`.pytest_cache`；网络冒烟另用独立临时DATA_DIR和127.0.0.1随机端口，进程已退出。未启动持久服务、未清空运行库；正式B端口预留8002。

在backend目录使用 `../../.review-venv/Scripts/python.exe`：

| 命令 | 实际结果 |
| --- | --- |
| python -m pytest tests/health -q --tb=short -rx --basetemp=.pytest_cache/b-verified-routing | 85 passed / 1 xfailed（稍后恢复新增前） |
| python -m pytest tests -q --tb=short -rx --basetemp=.pytest_cache/b-final-integrated | 265 passed / 42 deselected / 1 xfailed（含最新C，稍后恢复新增前） |
| python -m pytest tests -q --tb=short -rx --basetemp=.pytest_cache/b-delivery-active | **266 passed / 42 deselected / 1 xfailed**（最终代码） |
| python -m pytest tests/health/test_b2.py tests/health/test_activation.py tests/health/test_shared_settings_gap.py -q --tb=short -rx --basetemp=.pytest_cache/b-final-scanner | 40 passed / 1 xfailed |
| python tests/agent/smoke_network.py | C_NETWORK_SMOKE_OK，真实默认Uvicorn/鉴权/建档/绑定/Agent确认与重放/日报与记忆/音频字节/提案明确接受 |
| python -m app.tools.export_contract --check | matches，`4b7ade26f590902a4eb131920589184b95e0b54a293e9df80ac9f8aa4859532c` |
| python -m app.tools.check_architecture | Architecture OK |
| python -m pip check | No broken requirements found |
| git diff --check | 无错误 |

最终全量复验已结束，无非预期失败；1项strict xfail仍是明确未解决的A共享问题。唯一既有warning为Starlette/TestClient的httpx弃用提示，未屏蔽。

**strict xfail不是通过**：`test_approved_settings_proposal_updates_existing_future_goals` 使用真实默认HTTP，A接受关闭运动的设置提案后settings=false，但已生成的明日运动expected仍为1。A直接改JSON绕过B入口，待A修复后strict XPASS会要求移除标记。其余设置本人更新、未来任务停用与来源失效已通过。

`python -m app.tools.integration_smoke --strict`：**34 OK / 4 PENDING / 0 FAIL，退出1**。3项是NOTI03保留501；另1项为脚本中午创建当天08:00计划，B不生成过去任务。药物新计划13:00→匹配task→明确taken→重放仅一条→日报completed=1已有默认HTTP验收。不能把该脚本PENDING当作成功，也不能为消除它补造过去目标。

未运行手机HTTPS/真实设备播放、真实供应商、完整AC01–AC14或零PENDING三轮验收。P0尚未完成，因此P1系统推送未尝试，push_state保持unsupported。

## 5. 需 A/C 继续

详见 [变更申请/B.md](../变更申请/B.md)，当前只剩共享事项：

1. A/C提供与本次提案内容一致的真实播报，明确拒绝提示音作为完成证据；B随后验收并开启NOTI03。
2. A的settings提案在同tx调用已冻结B update_settings，修复未来目标不同步，避免重复版本递增。
3. A统一真正的系统授权入口，替换超时处理中构造老人Actor的做法。
4. A修正其联调脚本的计划时间、plan/task匹配与可见心跳。
5. A/C冻结Agent确认记录的可信来源参数；当前C真实确认结果source仍为user，B不接受客户端自报来源。

请正常合入 `origin/backend/health`，不移动标签、不覆盖他人改动。B业务代码/测试/素材/文档均在白名单，公共定义仅来自已发布A/C正常merge。
