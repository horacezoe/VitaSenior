# 正式任务单 B：健康记录、任务与提醒

状态：B1可立即开工；跨模块集成前合入A0。共同起点 `f1-reviewed-v1`，已复验代码 `497fc4ce6ede5ee951c57cd06913197391633f56`。配套：[验收说明](F1验收与开工说明.md)、[A任务](任务单-A.md)、[C任务](任务单-C.md)。

分支 `backend/health`；推荐端口8002。先核对真实models/health.py、schemas/health.py、contracts/ports.py及框架交接，不从计划中的简写推断新字段。

## 1. 文件白名单

- backend/app/routers/health.py、application/health_flows.py
- backend/app/services/health_service.py、medication_service.py、notification_service.py、report_service.py
- backend/app/scheduler.py
- A0建立后由B维护的 services/health_capabilities.py
- backend/fixtures/health/**、backend/tests/health/**
- docs/协作/交接/B.md、docs/协作/变更申请/B.md

公共模型/schema/core/ports/composition/依赖锁/框架测试不由B直接修改。有缺口写变更申请，A统一处理。可以在本域新增私有纯函数与测试文件，不新增第二套共有DTO。

## 2. B1：现在可先做的服务与测试

| 顺序 | 工作 | 复用入口/模型 | 验收 |
| --- | --- | --- | --- |
| B1.1 | PLAN01–03、SET01–02 | MedicationPlan/ReminderSettings，MedicationPort.import_draft/apply_change | 固定/餐后计划、字段合并后重新验证、版本冲突、子女不能直接写 |
| B1.2 | TASK01、每日目标快照 | DailyTask，按日期/category/slot唯一 | 三餐/每日运动/具体用药时段，餐后先waiting_for_meal；历史目标不被新计划改写 |
| B1.3 | REC01–04 | CheckinPort.create_or_update，Checkin/revisions_json | 同餐更新、运动多次、具体服药任务唯一、取消和纠正 |
| B1.4 | REPORT01、CAL01、DASH01 | ReportPort.daily，现有CalendarDay/Records/Dashboard | 同一计算入口、绿色/黄色/灰色/未来、未配置药物不算缺卡 |

A0发布前，可在独立临时库实现确定性服务并注入测试用Clock/MemoryPort；先不改共享ports。合入f1-shared-v1后按真实构造器和新增读取入口接HTTP路由，不能长期保留两套签名。

关键规则：

- 同餐按elder/local_date/meal_slot替换，不重复累计；exercise多条独立；药物必须核对task_id、plan_id、slot_id同属本老人且类型匹配。
- 只有taken计入已确认服用，not_taken是明确记录，稍后是提醒状态。听完音频不能创建taken。
- 补录、纠正和取消更新日报/日历；调用MemoryPort.on_source_changed使相关归纳失效。
- 原计划修改只影响尚未发生的未来任务，保留历史快照。若现有模型不足以表示真实所需的任务停用状态，写具体变更申请，不往无约定JSON里暗塞字段。
- SQLAlchemy JSON更新使用重新赋值或正确变更标记，确保SQLite实际保存；测试必须关闭Session再读。
- 所有时间使用注入Clock、UTC存储和HK划日，不在测试里真实等待。

## 3. B2：通知、回执与扫描器

实现NOTI01–04及NotificationPort.enqueue、A0新增的事件处理port：

1. 可见心跳10秒、25秒失效；列表读取不更改delivery_state。
2. displayed→answered→played单向；完整播放前不调用A mark_played；事件event_id幂等，跨老人/子女回执拒绝。
3. 通知事件与提案窗口必须同tx，使用A0冻结的协调方式，不另写一份60秒状态机。
4. handled/snoozed/dismissed与播放状态分开；提案通知不能dismiss绕过接受/拒绝。
5. 亲情提醒优先用户录音，否则预设文字/TTS；调用媒体port校验归属，不假定audio_asset_id可随意引用。
6. 到期扫描生成提醒、更新餐后任务；调用A apply_due(tx,now)。系统任务使用明确内部入口，不伪造一个用户Actor跳过鉴权。
7. 扫描器与应用使用同一factory/clock，短事务；不在持有SQLite写锁时调用TTS或推送。
8. source_key去重，重启补偿；历史seed不生成过期来电，上线只汇总待核对事项。

系统推送是P1，最多1小时探测，失败标unsupported/failed保留待办。P0尚未通过不开始推送集成。

## 4. 必须通过的业务验收

- 同餐并发替换/幂等重放只一条有效记录，运动可多条，药物任务不能重复计数。
- 错elder、错类型/plan/task、过期版本均拒绝且无部分写入。
- 取消/纠正后重新打开Session，日报/看板/日历一致；Memory来源失效在同tx调用。
- 关闭网页/推送成功不算送达；未接听/未播报完成不触发自动应用。
- 播报完成后再过60秒由A结算；重复事件不重置，服务重启可恢复。
- 餐后计划无进餐时不假定已吃；记录后时间正确，已送达提醒不重复来电。
- 不同观众数据隔离。核心对应AC04/05/06/07/10，与A共验AC08/09。

## 5. 交接要求

B1先交付已有port的真实实现和服务测试，A可接建档计划导入，C可接确认打卡和读日报。B2再交可见/回执/扫描器，不把两批绑成一个大合并。

A0合入后运行框架持续测试、本域测试、契约和导入检查；F0-only用例按A发布的方式单独保留。每个能力true对应实际可用路由和测试，不在自己的分支随意修改system.py。

## 6. 可复制的初始提示词

```text
你是VitaSenior业务Agent B。请从共同标签f1-reviewed-v1创建backend/health分支，执行docs/协作/任务单-B.md。

先读AGENTS.md、docs/协作/F1验收与开工说明.md、任务单-B.md、实际框架交接记录与接口说明第7节。已复验代码为497fc4ce6ede5ee951c57cd06913197391633f56，按发布标签核对实际HEAD，不从main重建框架。独立DATA_DIR/SQLite/端口，测试用tmp_path。

立即开始B1的计划、每日任务、打卡和汇总纯服务与测试，复用现有模型/schema和ports。A正完成A0公共适配，期间只在本域工作，依赖未实现时测试注入明确替身。A发布f1-shared-v1后正常merge并读取实际签名，再接需要新增port的路由与全链路，不猜测或另造协议。

核心约束：同餐更新、运动多次、每个用药任务唯一；必须核对elder/type/plan/task；taken需明确确认，播放完和未记录都不能冒充taken或明确漏服；历史分母不被新计划改写。记录纠正调用C来源失效port。

B2实现通知/可见心跳/回执和扫描器。未进入应用、未接听、未完整播放不启动窗口；调用A ChangePort，不复制提案逻辑。通知与窗口同事务，外部TTS/推送不占写锁。P0完成后才限时尝试系统推送。

严格按任务单文件白名单修改。共享定义缺口写docs/协作/变更申请/B.md交A统一处理，继续不受阻的工作，不删公共测试或放宽schema。

每批实际验证后再登记health能力，更新docs/协作/交接/B.md，列出commit、接口、测试、未实现依赖和给A/C的调用样例。
```
