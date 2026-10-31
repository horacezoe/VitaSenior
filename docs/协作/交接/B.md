# B 健康域交接

日期：2026-10-31。分支 `backend/health`。本文件当前状态覆盖历史交接中的“B桩/7个pending/提示音/source未接线”结论。

**B的17项health能力已全部开启，包含NOTI03。** 可信Agent确认来源已落库；默认部署严格三轮为 **39 OK / 0 PENDING / 0 FAIL**，真实Uvicorn网络烟测通过。全量暂为 **295 passed / 3 failed / 42 deselected**：3项均是C旧测试预期（2个修复后strict XPASS、1个仍要求NOTI03=false），未改C文件掩盖失败。尚不能宣称全量测试或完整产品P0已经全部通过。

## 1. 基线与本轮提交

- 独立checkout：`E:/CUHKSZ/project/vitasenior/.health-work`；远端：[backend/health](https://github.com/horacezoe/VitaSenior/tree/backend/health)。根目录原文件及他人运行数据库未改。
- 共同起点 `f1-reviewed-v1` → `1034c7698de4394b3e7695a3a820df2dcfeaf28b`，父提交为已复验代码 `497fc4ce6ede5ee951c57cd06913197391633f56`；正常合入 `f1-shared-v1`（`10d51af`），没有从main重建框架。
- 既有B：`9299f2c` B1服务；`6ef7e66` B2回执/扫描；`b1535f8`演示历史；`9cfe39b`真实A窗口/重启；`b8b064a`剩余HTTP、模型适配和16项能力；`be0ae4c`稍后提醒恢复；`ce472da`上轮交接。
- 本轮先快进A `0894154`，关闭设置提案/系统主体/脚本时刻等旧缺口。
- `c1fe1d6`：实现冻结的CheckinPort来源参数及持久化/修订测试。
- `76cd70b`：正常merge A `integration/f1@666b317`，其中已含C `backend/agent@974d719`/`73e8f20`的完整播报与可信来源调用。
- `e78e604`：通过实际完整内容HTTP验证后开启NOTI03，移除B测试的临时能力覆盖，默认应用直接验证全部17项。

本轮B实际编辑：`services/health_service.py`、`services/health_capabilities.py`、`tests/health/test_checkin_provenance.py`、`test_notice_http.py`、`test_activation.py`、`test_change_integration.py`及本角色两份文档。公共/C文件变化仅来自正常merge；不reset、不强推、不移动标签。

## 2. 可调用接口和来源约定

| 能力 | 行为 |
| --- | --- |
| PLAN01–03、SET01–02 | 计划/设置读写，合并后校验、版本冲突、未来目标同步；子女走A提案 |
| TASK01 | 当日目标快照；A已将TaskPort绑定到真实CheckinService.today |
| REC01–04 | 同餐替换、运动多次、具体药物任务唯一、纠正/软取消与C来源失效 |
| REPORT01、DASH01、CAL01 | 同一计算入口，明确taken/明确not_taken/未记录分开，历史分母不重建 |
| NOTI01–02 | 可见心跳25秒有效；通知列表无送达副作用、分页/权限隔离 |
| NOTI03 | displayed→answered→完整播放，事件幂等；同tx调A窗口，播放不产生taken |
| NOTI04 | 家人录音优先；固定完整中文关怀语音，未匹配文字明确降级 |

冻结的内部写入口：

```python
def create_or_update(self, tx, actor, elder_id, payload, checkin_id=None, *,
                     source: Literal["user", "agent_confirmed"] = "user") -> Checkin: ...
```

C调用样例（仅在本人明确确认后，使用调用方的同一tx）：

```python
record = services.checkins.create_or_update(
    tx, actor, elder_id, validated_checkin, source="agent_confirmed",
)
assert record.source == "agent_confirmed"
# 调用方把Action结果、业务、幂等一起commit；B不自行提交。
```

普通HTTP不接受source字段，客户端自报仍422；默认服务调用记user。每次有效修订保存本次操作者来源，旧来源先留在revisions_json；取消不改写来源。demo_seed只走原内部演示历史导入，不开放为该参数值。

A调用样例沿冻结入口，不直接写B表：

```python
services.medication.update_settings(tx, actor, elder_id, expected_version, patch)
services.medication.import_draft(tx, actor, elder_id, confirmed_plans)
services.history.import_demo_history(tx, actor, elder_id, demo_id=demo_id, days=14)
services.tasks.today(tx, actor, elder_id, hk_day)
services.reports.daily(tx, actor, elder_id, hk_day)
services.notifications.handle_event(tx, actor, notification_id, event, clock.now())
```

现有list/cancel/calendar/dashboard/presence/query/scan等port签名见共享`contracts/ports.py`，没有第二套DTO或协议。所有跨域写使用同一tx；服务不commit/rollback/另开连接，来源失效也在其中。C先持久化所需task_id并退出短事务，再调慢provider；确认时重验计划/任务。

## 3. NOTI03与语音口径结论

已读取交接目录A/B/C，当前应以A的11.7和本次提交为准，旧11.6类别录音及C旧NOT_READY不是当前事实。A已删除按类型播放的五段通用录音，改接C的`proposal_text/prepare_proposal_notice/ProposalFixtureTTS`。

当前完整样例包含具体修改字段/值、申请语气、完整播放后60秒可拒绝、可明确接受/拒绝；用药样例包含药名、用量、时间/停用对象，显式清空也有描述。生成清单、实际媒体字节与默认HTTP已核对，**满足本轮mock演示的内容口径**。建议下次调整文案时补一句“60秒内未拒绝将生效”，提升老人理解；这是文案优化，不为它另建协议或重新阻塞本轮能力。

范围必须如实说明：

- 只有五个精确匹配的预录完整样例；不是任意文本TTS。SAPI只离线制作素材，运行时不依赖Windows语音。
- 不同备注/原因/药品/ID没有对应语音时，保存完整文字、audio=null、pending_notice；本人仍可明确接受/拒绝。用药修改/停用样例含example-plan，真实随机plan_id通常走此文字降级，不声称五种任意真实请求都有语音。
- 未进入/未接听/未完成播放不计时；查询和推送不算送达。B只消费真实播放器完整回执，C不能生成播放证据；没有加ASR核验音频、声音签名或另一份窗口状态机。
- 音频准备在写事务外；通知事件与A mark_played窗口同tx。超时使用A冻结SYSTEM_ACTOR；播放和handled均不产生服药事实。
- 手机实际播放/HTTPS尚未验收，不能把字节验证等同设备实听。

## 4. 仍保留的业务边界

- DailyGoalBatch区分已生成零目标与从未生成；历史日期不按新计划回填。DailyTask.cancelled_at只停用尚未发生、未记录/未送达的未来任务，不删除外键行。
- 同餐按elder/date/meal_slot替换；运动可多条；用药逐一核对elder/type/plan/task/slot。未打卡不是明确漏服。
- 餐后无进餐则waiting_for_meal；纠正/取消餐食按任务快照重算，已送达不重复来电。snoozed到期只恢复open，不回退delivery。
- 纠正/取消同tx调用C on_source_changed；日报/日历/看板重开Session后仍一致。
- 家人录音通过A媒体归属校验，事务外取受控字节，再登记为目标老人可访问的媒体；录音优先。B四段关怀预设和C五段完整提案素材用途不同，勿复制成第三套提案语音。
- 扫描器沿用统一factory/Clock/单循环；只生成当天提醒，不向演示历史补发来电。无外部TTS/推送写锁。

## 5. 本轮实际验证

Windows / Python 3.11.5 / 既有`.review-venv`和锁定依赖，无新依赖。pytest使用tmp_path，基目录在本checkout`.pytest_cache`；网络烟测临时DATA_DIR、随机本机端口，结束已退出。未清空运行数据库；正式B端口预留8002。

在backend目录使用`../../.review-venv/Scripts/python.exe`：

| 命令 | 实际结果 |
| --- | --- |
| python -m pytest tests/health/test_checkin_provenance.py -q --tb=short --basetemp=.pytest_cache/b-source-contract | 2 passed |
| python -m pytest tests/health/test_notice_http.py -q --tb=short --basetemp=.pytest_cache/b-full-notice-http | 4 passed（先验收再激活） |
| python -m pytest tests/health -q --tb=short --basetemp=.pytest_cache/b-noti03-enabled | **93 passed**，默认声明，无临时覆盖 |
| python -m pytest tests -q --tb=short -rx --basetemp=.pytest_cache/b-final-source-notice | **295 passed / 3 failed / 42 deselected**，129.90s |
| python -m app.tools.integration_smoke --strict | **39 OK / 0 PENDING / 0 FAIL，exit 0**，默认能力无临时开启 |
| python tests/agent/smoke_network.py | C_NETWORK_SMOKE_OK，默认真实Uvicorn、A/B/C写入/重放/日报/记忆/媒体/明确接受 |
| python -m app.tools.export_contract --check | matches，4b7ade26f590902a4eb131920589184b95e0b54a293e9df80ac9f8aa4859532c |
| python -m app.tools.check_architecture | Architecture OK |
| git diff --check | 通过 |

唯一warning为既有Starlette/httpx弃用提示，未屏蔽。42 deselected是A0原有F0阶段分类；未删公共测试、未放宽schema、未用排除C失败来宣称全量绿。

## 6. 给A/C的最后接手项

C需正常合入`origin/backend/health`，只更新过时验收预期，保留原业务断言：

1. `tests/agent/test_http.py::test_actual_b_confirmation_writes_once_and_report_uses_same_record` 删除source缺口的strict xfail；当前实际断言全部成功，报XPASS。
2. 同文件`test_medication_new_day_task_ids_remain_valid_after_planning[none]`移除该参数的source缺口strict xfail；其余版本冲突参数不改。
3. `tests/agent/test_production_acceptance.py::test_default_wiring_runtime_and_all_seven_c_routes`把NOTI03=false过时预期改为true。

B未编辑C白名单外测试。A合入后重跑全量、严格三轮、网络烟测，刷新A/C交接的当前状态与接口说明7.1“提示音频”旧描述。无新的B业务port依赖未实现；当前剩余是上述C测试同步与尚未执行的设备/总体验收。

## 7. MVP初衷与三方边界复核

目标始终是黑客松路演的轻量家庭健康闭环：**业务记录、家庭授权、确认和提案状态真实落库；AI/ASR/TTS可明确mock。** 根据现有代码与交接，A维护平台/共享契约/提案，B维护健康记录/目标/通知，C维护理解/确认编排/记忆，分工合理。授权、一次事务、明确服药确认、来源修订、历史分母和播报后窗口都是原需求所需，不属于额外生产化。

接下来应停止横向扩建：维持一个FastAPI进程、SQLite、现有扫描器和typed ports，不引入Redis/Celery/向量库/通用工作流；不为了少量演示语音建设任意文本TTS供应链或动态协议协商。C当前为旧B适配器加的签名检查属于短期集成保护，统一版本后可在常规整理时收敛，不发展成兼容平台，也不为清理它阻塞路演。

优先顺序：更新这三条验收预期→A一次整合全量验证→固定演示脚本与设备演练。未做真实供应商、手机HTTPS/播放器、完整AC01–AC14或P1推送，不列为通过。P1系统推送至多按原计划限时探测，不能反过来延迟P0；当前不自动扩展该范围。
