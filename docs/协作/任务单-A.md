# 正式任务单 A：平台、家庭档案与集成

状态：可从第一批开工。共同起点：`f1-reviewed-v1`；已复验代码为 `497fc4ce6ede5ee951c57cd06913197391633f56`。先读[本轮验收说明](F1验收与开工说明.md)、AGENTS.md、实际框架交接记录和接口说明第7节。

分支：`backend/platform`；独立数据目录/SQLite；推荐端口8001。A兼任集成人，负责共享代码更新，业务实现优先完成A1，不把时间耗在额外基础设施上。

## 1. 文件白名单

主责文件：

- backend/app/routers/identity.py
- backend/app/application/identity_flows.py
- backend/app/services/identity_service.py（保留既有登录能力）
- backend/app/services/binding_service.py、profile_service.py、change_service.py、media_service.py
- backend/fixtures/identity/**、backend/tests/identity/**
- docs/协作/交接/A.md、docs/协作/变更申请/A.md

集成权限：core、models、schemas、contracts、main.py、composition.py、routers/dependencies.py、routers/system.py、seed.py、依赖锁、OpenAPI快照与公共测试。A0可在B/C服务占位类补齐统一构造器/新port桩和能力声明，但不替B/C实现业务；发布前同步准确差异。完成A0后不擅自改B/C私有文件。

## 2. A0：共享适配，目标30–60分钟

详见[验收说明第5节](F1验收与开工说明.md)。必须形成可合入的独立提交，发布 `f1-shared-v1`，记录在自己的交接文件。

- 将F0-only占位/provider/能力断言与长期框架测试分开；保留原断言作为明确阶段用例。不能把全部测试改成允许任意成功/失败。
- 为每个领域建立独立的能力声明文件，例如 services/identity_capabilities.py、health_capabilities.py、agent_capabilities.py，composition汇总，system路由只读取。初始只有原五项为true。
- 给AI流程可用的鉴权上下文：短读验证后释放事务，模型调用后另开短写UoW再验权/幂等。不要把供应商调用夹在现有非GET的BEGIN IMMEDIATE中。
- 统一时钟/配置注入，沿用create_app的clock和services可替换入口。测试时服务须使用同一个FakeClock。
- 补齐必要ports并记录实际签名：Profile读取、当日任务读取、通知事件处理、提案明确接受/拒绝、媒体受控读取、生成音频登记。返回复用Profile/TaskList/EventResult/ChangeProposal/MediaAsset等已有DTO。
- 通知事件port须承担完整回执语义，播报完成和mark_played同tx；可以显式注入ChangePort，避免C重复实现状态机。
- 为DEMO01确认后的历史导入约定统一seed入口，B/C提供fixture，A总入口统一调度；不要求B/C另建观众账号。
- 媒体生成/读取约定区分外部音频生成与短事务登记，路径由媒体服务控制。MEDIA03实现时允许有效ticket单独授权，仍保留Bearer访问。

交接最低内容：实际签名、哪些port仍501、能力声明写入位置、AI事务入口、构造器约定、测试命令与结果、共享提交/hash。B/C无需等业务完成，但依赖这些入口前必须合入该提交。

## 3. A1：先把家庭与媒体接通

| 顺序 | 接口/工作 | 完成条件 |
| --- | --- | --- |
| A1.1 | DEMO01 | 每次独立账号和老人草稿；同幂等key重放原家庭；不自动建立亲属关系 |
| A1.2 | PROF01/02、ONB01/02 | 样本匹配/不匹配可确认；草稿未确认不改正式档案；确认时调用B import_draft；保留版本 |
| A1.3 | BIND01–04 | 四位码有前导零、5分钟有效、旧码失效、事务内一次消费；子女绑定后才共享 |
| A1.4 | MEDIA01–03及MediaPort | 文件真实保存与读取、限额/MIME/归属校验、ticket过期、浏览器无Bearer可用ticket播放 |

框架中的AUTH01/02/04、Access、幂等和UoW已经可用，不重复实现。DEMO01应能让新手机号走原登录流程。

### A1验收

正常/无匹配建档；草稿重复确认无重复计划；绑定码过期/消费竞争/更新旧码；未绑定403；不同观众不串数据；图片/音频可取；外人/过期票据不可取。使用真实数据库，跨域依赖在本模块测试可注入明确替身。

## 4. A2：代维护与自动生效

实现CHANGE01–04及既有ChangePort.mark_played/apply_due，保持状态字段和版本规则：

1. 子女提交只写提案与通知，不提前改目标；source_key去重。
2. 未进入、未接听、未完整播报，auto_apply_at必须null。
3. 完成播报后60秒窗口，仅服务端时间；重复回执不重设时间。
4. 明确接受/拒绝和到期竞争只有一个终态，应用时再校验目标版本及仍有效的授权。
5. 修改用药计划调用B MedicationPort；来源失效调用C MemoryPort。共享tx内提交，不跳过子服务错误而标成功。
6. 已应用后的纠正走新提案，before_snapshot和状态保留。重启后的到期结算不依赖原Python计时器。

A2验收：离线推进时间无应用、播报完成再应用、窗口内拒绝、重复事件/幂等、版本冲突、重启、绑定撤销后不静默写入。核心对应AC01/02/03/08/09/12。

## 5. 交接和集成责任

- 首批先发布A0共享适配，不把它与全部A业务绑成一个大提交。
- 每组接口实际通过后才登记本域capability=true；未完成仍501。
- B/C提交变更申请时，A统一改公共定义、快照和测试，发布共享提交；不要让三人分别改同一份schema。
- 最先集成登录→建档→绑定→C午餐动作→B记录与子女看板；然后才是完整提醒/提案窗口。
- 实际执行本域测试、框架持续测试、契约/导入检查；列明F0阶段测试和业务测试的区别及未运行项。

## 6. 可复制的初始提示词

```text
你是VitaSenior业务Agent A及集成人。请从共同标签f1-reviewed-v1创建backend/platform分支，执行docs/协作/任务单-A.md。

先读AGENTS.md、docs/协作/F1验收与开工说明.md、任务单-A.md、实际框架交接记录、接口说明第7节。核对标签解析出的真实commit。原始framework-v1为40b736bd41f758e5f9d1579df586f23de47d267f；本轮已验证的兼容修正代码为497fc4ce6ede5ee951c57cd06913197391633f56，OpenAPI hash仍为73f9920606bdd8c6338c67327e72adef1ea1a474352aa4c22c949e071ad75657。不要从只有README的main新建项目。

第一批优先完成A0共享适配，实际运行测试，单独提交并发布f1-shared-v1，写清精确port签名、注入/事务约定和仍未实现的入口。此过程是团队内部工程对齐，不重新询问用户已确定的产品需求。其他人可以准备自己的服务/fixture；不要等A全部业务完成才交共享适配。

然后依次完成A1独立演示家庭/建档/绑定/媒体，再做A2代维护提案。保留已有真实登录和Access。只在任务单授权范围内编辑；公共变更统一维护并告知B/C，A0之后不改他们的私有业务代码。

用typed ports调用B/C；未实现依赖仅在测试里替换，真实运行不得吞501伪造成功。写事务由调用方一次提交；所有时刻使用注入Clock。子女修改只有老人收到并完整播放通知后才能启动60秒窗口，播放提醒不代表服药。

每批先验证再登记能力。将实际commit、文件清单、接口、测试结果、缺口及接手样例写入docs/协作/交接/A.md。不要重打既有标签，不强推或覆盖他人分支，不删除他人数据库。
```
