# 正式任务单 C：小安、mock 与长期记忆

状态：C1可立即开工；HTTP慢调用与跨域工具集成前合入A0。共同起点 `f1-reviewed-v1`，已复验代码 `497fc4ce6ede5ee951c57cd06913197391633f56`。配套：[验收说明](F1验收与开工说明.md)、[A任务](任务单-A.md)、[B任务](任务单-B.md)。

分支 `backend/agent`；推荐端口8003。先看实际schemas/agent.py、models/agent.py、contracts/ports.py；providers当前只有初始化文件，AgentService尚不存在。

## 1. 文件白名单

- backend/app/routers/agent.py、application/agent_flows.py
- backend/app/services/memory_service.py，以及新建agent_service.py/本域私有辅助文件
- backend/app/providers/**
- A0建立后由C维护的 services/agent_capabilities.py
- backend/fixtures/agent/**、backend/tests/agent/**
- docs/协作/交接/C.md、docs/协作/变更申请/C.md

公共core/models/schemas/contracts/composition/依赖锁不直接改。音频通过A的MediaPort登记；不直接写媒体表或绕过B写健康记录。若AgentService需加入组装，交A按统一入口接线，不在路由里偷建第二套依赖。

## 2. C1：现在可做的独立服务与测试

| 顺序 | 工作 | 实际起点 | 验收 |
| --- | --- | --- | --- |
| C1.1 | MemoryPort.context/on_source_changed、MEM01–03 | MemoryDocument模型有entries_json/revisions_json/version；已有MemoryEntry/SourceRef | 跨会话读取、来源失效、修正/删除、版本冲突、HK日期 |
| C1.2 | mock ASR/理解/TTS协议和纯适配器 | providers目录为空，实际HTTP schema已存在 | 场景确定、未知内容引导、错误可控、结果校验 |
| C1.3 | Agent结构化规划与待确认动作 | AgentTurn/AgentAction及完整Action union已存在 | 生成完整可执行payload，preview只用于展示，不提前打卡 |

此阶段不等待A/B真实业务；测试可以注入符合现有port的替身。A0完成后合入f1-shared-v1，按真实扩展签名连接工具和媒体，不长期保留自己的临时协议。

记忆默认规则：明确偏好可保存；规律至少三个不同日期的有效证据；单次晚饭不写成长期规律。source_ids是SourceRef对象数组，保留来源版本和更新时间。取消/纠正来源使对应归纳失效，删除条目留修订/抑制信息，旧候选重放不能立即复活。Markdown从唯一entries_json渲染，健康档案和用药计划不能被记忆覆盖。

## 3. C2：正式HTTP、工具执行和音频

实现AI01/02、AGENT01/02、MEM01–03；新增服务/协议需沿用A0组装约定。

### 事务与流程

1. 使用A0的短读鉴权入口，读取档案、任务、日报和记忆快照后释放Session。
2. 在数据库写事务之外调用mock/真实provider；默认只用mock。
3. 开新的短写UoW，重新检查本人身份、资源关联、幂等与快照版本，再写轮次、动作或来源失效。
4. 不能在原Context的BEGIN IMMEDIATE里等ASR/LLM/TTS。TTS失败时保留文字，按schema的degraded明确返回。

### 工具行为

- 拍菜品/说运动只生成pending动作；明确确认再调用B CheckinPort。重复确认和client_turn_id重试不重复写入，取消后不可确认，过期明确拒绝。
- 动作必须把执行所需的日期、occurred_at、任务/计划/资源ID、expected_version等保存到payload_json；不要从preview补猜参数。例如UpdatePlanAction.preview本身没有plan_id，完整执行payload必须有已校验的目标。
- 用户下一轮“确认”绑定唯一未完成动作或context.pending_action_id；存在多个动作时追问。
- 生成绑定码调用A BindingPort，查询日报用B ReportPort，模糊药物从B当日任务查询后追问。
- 接受/拒绝修改调用A的决策port；提醒的稍后/处理调用B事件port。客户端播放回执仍以真实播放器事件为准，模型不能凭“我听到了”伪造playback_completed。
- 服务端校验amendments与动作type/目标一致，不允许改目标elder、药品或task偷越权。

### 音频与媒体

- ASR先经MediaPort检查并读取素材；文档中的编码转换方案在真实接入前验证，不能只改扩展名。
- TTS输出通过MediaPort登记并获取可播放地址，不猜磁盘路径或直接向A表插入。
- mock使用真实可播放的预录音或本地离线合成固定素材，并明确is_mock。没有匹配音频时如实降级/保持该能力未实现，不用空文件、静音或音调冒充内容播报。
- 提案只有完整内容已播报才启动窗口；若只有文字且无可用音频，应保留待通知，用户明确接受/拒绝仍可单独走业务接口。

## 4. 必备mock场景

meal_lunch、ingredient_advice、exercise_walk、medication_ambiguous、medication_confirm、binding_code、profile_update、daily_query、explicit_preference、reject_change、provider_timeout。

返回既有scene与ActionType枚举，不另造同义值。mock_fixture_id仅在对应provider为mock时生效；任意新照片不能无条件固定识别成同一道菜。识别不确定时输出clarify或说明演示素材，不自动落记录。

先做文本和图片场景确认闭环，再做音频。真实MiMo或DeepSeek+音频供应商是后续适配；当前Settings拒绝真实provider，需A统一接入配置，不私自跳过校验。

## 5. 必须通过的业务验收

- 同一client_turn_id相同请求重放返回原结果，异体冲突；不会重复记忆或动作。
- 待确认阶段B记录数不变；确认后一次写入，重复确认仍只一条；失败时动作不能标confirmed。
- 跨老人素材/动作/会话/任务引用拒绝；“吃了药”对应多个计划不自行选药。
- 明确偏好能跨conversation_id读取；单次事件不变规律；来源取消、用户修正/删除真正改变后续上下文。
- ASR/模型失败没有健康业务写入；TTS失败按既有nullable reply音频和degraded处理；AI02若无有效音频不可报成功。
- 使用同一FakeClock，10分钟动作过期可直接推进测试时间；模型慢调用期间第二个写事务可进行，避免占锁。
- 正常运行不静默用替身伪装A/B成功；替身仅用于明确的模块测试。核心对应AC11/13/14。

## 6. 交接要求

C1先交MemoryPort与纯mock/规划测试，供A/B替换占位；C2再交可执行工具闭环和音频。提供每个mock场景输入、对应动作、哪些依赖仍501、真实测试结果。只在通过后登记agent领域能力和provider状态。

真实供应商不作为C1阻塞项；后续保留同一接口和业务执行路径，不让模型自行直接写数据库。

## 7. 可复制的初始提示词

```text
你是VitaSenior业务Agent C，负责产品内小安Agent、mock和长期记忆。请从共同标签f1-reviewed-v1创建backend/agent分支，执行docs/协作/任务单-C.md。

先读AGENTS.md、docs/协作/F1验收与开工说明.md、任务单-C.md、实际框架交接记录、接口说明第7节。已复验代码为497fc4ce6ede5ee951c57cd06913197391633f56，核对发布标签的实际HEAD；独立数据目录和端口，不重建公共模型或协议。

立即开始C1：实现MemoryPort和记忆修正/删除、纯mock适配器、完整动作参数生成与测试。A正完成A0，期间不改公共文件；需要的依赖可在模块测试用明确替身。A发布f1-shared-v1后正常merge，读取真实的媒体/任务/通知/决策port和AI事务入口，再做C2 HTTP与工具执行。

图片分析只生成pending动作；确认后调用B正式服务且只执行一次。payload_json保存全部执行参数，preview只展示；药物模糊先追问。绑定码/档案/提案决策走A ports，打卡/日报/通知走B ports，音频走MediaPort。禁止绕过权限直接写A/B表。

模型调用在无写锁的阶段进行；写入时重新验权和幂等。明确偏好可记忆，单次事件不成规律，来源纠正/删除必须反映到后续上下文；Markdown由统一条目渲染。mock和真实结果校验同一schema，不用假音频或虚假成功绕过业务。

按白名单工作，缺口写docs/协作/变更申请/C.md让A统一处理，继续可独立任务。先mock闭环，真实provider稍后接。每批验证后更新自己的能力声明，并在docs/协作/交接/C.md记录实际commit、测试、mock样例、跨域依赖和剩余问题。
```
