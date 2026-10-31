# F2 B：MVP 音频交接

2026-10-31（Asia/Hong_Kong）。目标是尽快形成可用 MVP；只验证改动和关键主链，已完成项目不反复全量复验。

## 当前基线

- 共同起点：`363f6376a63d696ba36b1bc7fc426e8b159dc196`。
- B：`backend/f2-audio`，工作区 `E:/CUHKSZ/project/vitasenior/.audio-work`，独立 `backend/data/f2-audio-b` / 8022，未清空或修改其他人的库。
- 已包含 C `dfb41df` 的多意图/确认/取消/更正/澄清续接；最新正常合入 A `baa0351`（`f2-demo-v5`），合并提交 `18c347a`，无冲突，标签未移动。
- A 最新交接明确把 ReportService 来源读取和 NOTI04 新关怀文字 TTS 接线交给 B；本轮按这项安排收尾，未改公共 schema、配置、路由、依赖或提案状态机。
- B 本机被忽略的 `backend/.env` 已为 chat/asr/tts 全 real；模型分别为 `mimo-v2.6-flash`、`mimo-v2.5-asr`、`mimo-v2.5-tts`，TTS 音色 `冰糖`。只复用用户本机同一 MiMo 账号，密钥未输出或提交。

## 本轮实际产出

1. A 已将 CHANGE01 提案播报接到已配置的真实 TTS；B 的针对性回归验证新 patch 全文进入实际适配器，生成非预录 WAV，未完整播放时仍为 pending_notice、auto_apply_at=null。
2. `backend/app/services/report_service.py`：默认 provider_mode=mock，实际看板读取 A composition 注入的 self.provider_mode。chat=real 时看板现在返回 real；统计仍来自真实 SQLite，不声称由模型生成统计。
3. `backend/app/application/health_flows.py`：NOTI04 的任意新关怀文字在未附家人录音、也未匹配预设全文时，使用现有真实 TTSProvider。供应商调用在写事务外完成，音频通过已有 MediaPort.store_upload 作为该子女的 voice_message 保存并通知老人，不新增媒体库。
4. TTS 超时、无效音频或全文超限：通知保留完整原文，audio_asset_id=null，标题明确包含“语音暂不可用”；不播放其他固定句子冒充原文。有效家人录音优先，既有预设保持可用。
5. 新关怀动态 TTS 在计费调用前复用共享幂等入口检查已完成请求与 body 冲突；顺序重放直接返回原通知/原音频，不再合成。首次检查无记录时立即退出短事务，合成后重新鉴权并在最终短事务登记/发送。
6. `backend/tests/providers/test_real_audio.py`：补覆盖上述关怀成功/播放回执/重放/冲突、失败全文降级、权限、录音和预设优先、真实提案装配及看板 mock/real 来源。

## 实际验证

命令均在 backend，Python 使用 `../../.review-venv/Scripts/python.exe -X utf8`。免费测试子进程显式设 CHAT_PROVIDER/ASR_PROVIDER/TTS_PROVIDER=mock；测试内部按场景通过正常工厂构建真实对象，仅替换 HTTP transport，使用临时数据库。

| 命令 | 本轮结果 |
| --- | --- |
| `python -m pytest tests/providers/test_real_audio.py -q --tb=short --basetemp=.pytest_cache/b-v5-family-tts` | **170 passed / 1 既有弃用 warning / 16.10s** |
| `python -m pytest tests/health/test_activation.py::test_family_voice_priority_shared_copy_repeats_and_no_taken tests/health/test_activation.py::test_family_fixed_speech_exact_fixture_integrity tests/health/test_activation.py::test_family_ownership_permissions_and_text_fallback tests/health/test_notice_http.py -q --tb=short --basetemp=.pytest_cache/b-v5-reminder-regression` | **10 passed / 1 既有 warning / 8.21s** |
| `python -m app.tools.export_contract --check` | 匹配 A 新契约 `6c1e8d96bfe881605d5d7ffd99a4da93b52d0682c01dbda4be9f9629d8e7f500` |
| `python -m app.tools.check_architecture` | Architecture OK |
| `git diff --check` | 通过 |

未重复全量、strict 或 ASR 真实调用。C 的完整工作流与 A 的真实提案网络结果继续引用各自最新交接，不冒充 B 本轮重复运行。

### 新关怀文字：一次真实 MiMo 调用

- 显式命令：`../../.review-venv/Scripts/python.exe -X utf8 - --live`，通过 stdin 提交一次性探针；读取本机 .env，正常 Settings/create_app/工厂，用临时 SQLite 和真实认证→NOTI04→MEDIA03，未注入 provider/service。此探针没有落入默认 pytest。
- 结果：**B_LIVE_FAMILY_TTS_OK**，`mimo-v2.5-tts / 冰糖 / provider=real / is_mock=false / audio/wav`，**407084 字节 / 8480 ms / 3.609 秒**。同 key 重放得到相同通知及音频。
- 原文：“妈妈，周日下午三点我们来看您。今天有任何需要，记得告诉我们。这是一条新生成的家人关怀消息。”
- 本机证据：`backend/data/f2-audio-b/family-evidence/20261031T105911Z/speech.wav` 与 `evidence.json`；SHA-256 `099001794e56b7349b17947d5cd8400c826b1b27ba645cc3a02d8575f68d6768`。证据被 data/ 忽略，未保存 key/token/票据。
- 仅一次实际 TTS 请求，无 chat/ASR 调用、无自动重试。新文件标记 listened=false，尚未实听；不能以容器校验代替音质或逐字完整性确认。

## 下一步与高频坑

- A 正常合入 B 最新提交并加载各自本机 env 重启，即可使用提案、新关怀语音和正确看板模式。应用不自动加载 .env；确认运行实例使用三项 real。
- 用户已确认“前端未就绪”。正式 Edge 页面完成后才做真麦克风、摄像头持续预览、句末取帧、最终回复播放与真实回执；目前不要求用户另建录音页或手动准备文件。
- 产品主链：说话结束→PCM WAV ASR→截图+转写交给 Agent→意图/业务子流程→必要的明确确认→真实保存→最终文字 TTS→历史回看。前端保留 conversation_id，标点/附带截图的控制由 C 已交付逻辑处理。
- ASR 只接完整 16-bit PCM WAV，最多 60 秒/7 MiB；Edge 默认 WebM 不能直接交给它，正式前端按既定方案直接采集 PCM 组装 WAV，无服务端转码或新依赖。
- TTS 单次最多 200 字；超长明确全文降级，不截断。执行后最终回复变化时前端用 AI02 补播 reply.text，不能重执行业务来获取音频。
- 已有用户“全文清楚、无截断”实听仅对应旧证据 `data/f2-audio-b/evidence/20261031T074100Z-7238915d/speech.wav`；不外推为本轮新关怀或真机验收通过。
- 外部模型调用放在数据库写事务外；提案只有完整播放后才启动既定 60 秒窗口；普通提醒/播放不代表已服药或已完成运动。
- 短信、社区匹配仍是演示接入，需要各自外部服务，MiMo key 不替代它们；历史种子/预设素材如实标记，后续业务记录实际保存和查询。

默认测试不收费；独立真实探针必须显式 --live。密钥只留本机被忽略的 .env，不提交音频/运行数据。
