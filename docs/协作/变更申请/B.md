# B 当前接手申请：业务接线完成，仅C验收预期待同步

2026-10-31。当前代码`backend/health@e78e604`（来源实现`c1fe1d6`，正常merge A/C为`76cd70b`）。本节覆盖此前所有“source未落库/提示音/设置提案未同步/7个pending”的旧结论。详情见[交接/B.md](../交接/B.md)。

## 已关闭

- A设置提案调用真实B update_settings，同tx更新未来目标；SYSTEM_ACTOR、脚本未来时刻/任务匹配/心跳/版本均已复验。
- A `666b317`接入C完整逐字段播报，删除类别通用语音。匹配完整素材才有audio；无匹配保留完整文字/pending_notice/明确接受拒绝，不启动窗口。
- C `73e8f20`在明确执行确认时传agent_confirmed，B `c1fe1d6`校验并真实保存；HTTP不接受source，修订保留旧来源，demo_seed仍是内部历史路径。
- B在真实内容HTTP验证后于`e78e604`开启NOTI03；health共17项。默认严格三轮39 OK / 0 PENDING / 0 FAIL，网络烟测C_NETWORK_SMOKE_OK。

## C：请更新三项过时测试预期

B保持白名单，不直接改C测试。正常合入`origin/backend/health`后：

1. `backend/tests/agent/test_http.py::test_actual_b_confirmation_writes_once_and_report_uses_same_record`删除source未实现的strict xfail；当前为XPASS，业务断言已全部通过。
2. 同文件`test_medication_new_day_task_ids_remain_valid_after_planning[none]`去掉该参数的source缺口strict xfail；保留正常与版本冲突断言。
3. `backend/tests/agent/test_production_acceptance.py::test_default_wiring_runtime_and_all_seven_c_routes`更新NOTI03预期为true，保留其余默认装配检查。

当前全量结果295 passed / 3 failed / 42 deselected；上面两项strict XPASS加一项旧false断言就是全部失败。不是通过，亦没有剩余501业务缺口。B域93 passed；契约/架构通过。请C同步后重跑全量，刷新C交接NOT_READY和旧来源缺口状态。

## A：合入与统一当前说明

正常合入B分支，重跑全量/严格三轮/真实网络烟测；更新A交接和接口说明7.1旧“提示音频”及health能力清单。本轮没有申请新DTO/表/port，不要求扩建供应商。

## MVP边界提醒

三方当前分工合理：A管平台/共享/提案，B管健康事实/目标/通知，C管理解/确认/记忆。保留原有授权、明确确认、一次事务、来源与历史分母；继续一个FastAPI进程和SQLite、固定mock素材。完整提案口径已够本轮mock验收；下次文案可补“60秒内未拒绝将生效”，无需为此重新设计协议。

五段完整语音仅精确匹配，真实随机用药plan_id通常文字降级；不要承诺任意文本语音、不要拿另一段录音代替。后续优先整合测试和设备路演，不因本轮修复扩展任意TTS、动态适配框架、自动医学推断、Redis/向量库或P1推送。手机实际播放/HTTPS和完整AC01–AC14尚未在B本轮验收。
