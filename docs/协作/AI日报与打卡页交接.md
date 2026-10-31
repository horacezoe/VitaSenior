# AI日报与打卡页（2026-11-01）

本轮从已有前端基线增量修改，保留工作树中已有未提交的对话Agent代码与测试，不将其混入本轮提交。

契约：`REPORT01 GET /api/v1/elders/{elder_id}/reports/daily?date=YYYY-MM-DD&include_ai=true`。
原调用省略include_ai时不产生模型费用；详情页显式请求AI。新增可选person、medication_plans、insights、ai_status字段；原始records/progress保持。

OpenAPI：`backend/contracts/openapi.json`，SHA256 `3241bf18af34f1930270489b24f9d5ec181635ad9f2ed89c7f3894d4554f3d1c`。

新ReportWriter Protocol接收已脱离事务的档案、记忆、日报DTO快照；composition集中构造，沿用CHAT_PROVIDER与MiMo凭据/模型。返回六段有长度限制的结构化文字，输入一致时进程内缓存（最多128条）；档案、记忆或记录改变后重新生成。外部请求20秒时限，失败保留完整真实数据，ai_status=unavailable；mock配置明确not_configured，不伪装AI成功。

子女首页仅展示月历，点击日期进入独立日报。顶部档案、当日鸡蛋核对数、AI温情播报、膳食/运动/用药三大记录卡；老人日报以数字人、表扬、鸡蛋进度、打卡卡片、单句提醒展示。两端共享三类详情页，含AI行动建议、分类次数或完成进度、原始记录；老人可进入既有补录/纠正流程，子女只读。用药显示实际计划名称、明确服用记录率，未设计划不会显示100%。

TTS使用`mimo-v2.5-tts-voicedesign`，音色描述严格采用用户指定原文：男性少儿7-10岁，清脆稚嫩童声，普通话标准吐字清晰，活泼可爱热情，语速适中，语调明亮，自然讲述风格。
仅更新本机私有env及无key示例；没有提交密钥。演示设置入口移除，旧直链重定向设置。激励规则补齐三类有效记录、每条1蛋、样例排除、纠正/重试去重及本机积分限制。

边界：现有接口RiskAssessment未配置医学评分，因此显示“尚未进行专业评估”；没有编造风险等级。没有药物相互作用引擎，用药页显示黄色待核验卡，有明确未服记录时另显红色记录核对提示，不冒充真实药物冲突结论。膳食信号反映餐次记录齐全程度，不代表营养风险诊断。当日鸡蛋从有效记录核对，不是跨设备累计账本。

当前含并行对话改动的工作树回归：`python -m pytest -q --tb=short --maxfail=2`：608 passed，42 deselected，1个已有httpx弃用警告（94.15s）。首次唯一失败为本文件尚未登记新OpenAPI hash，登记后FG10及日报测试3项复验通过，随后全量通过。前端`npm.cmd test`：55 passed；类型检查、生产构建、contracts:check通过。export_contract --check与check_architecture通过。真实MiMo临时库烟测已返回HTTP200、ai_status=ready、六段结构完整，模型为mimo-v2.6-flash（11285ms）；输入为framework虚构档案，无个人健康数据。未做实体手机听感与持续语音回合验收。
