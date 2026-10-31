# F2 交接（集成人 A）

基线：`integration/f1` 的 `363f637`，分支 **`f2/platform`**（保留既有数据目录与数据库，不重建）。
本轮：3 小时交主链、4 小时结束后端功能；**2:15 冻结范围**。

## 1. 已完成（第一批，30 分钟内）

| 交付 | 位置 | 状态 |
| --- | --- | --- |
| 前端接入包 | `docs/协作/F2交接/前端接入.md` | ✅ 启动方式、固定契约、错误码、登录→看板 13 步、图片/播放/回执口径、当前边界 |
| 可运行样例 | `backend/app/tools/demo_walkthrough.py` | ✅ `python -m app.tools.demo_walkthrough [--base-url ...]`，逐条打印请求/响应，`WALKTHROUGH_OK` |
| 最小配置/工厂共享提交 | `app/core/config.py`、`app/composition.py`、`app/main.py` | ✅ 已推 `f2/platform`，B/C 直接 merge 即可 |

**Provider 工厂（本轮唯一的共享依赖）**：只切换 TTS，不做通用 provider 平台。

```python
build_agent_providers(settings) -> (chat, asr, tts)   # chat/asr 固定 mock
providers(settings) -> {"chat": "mock", "asr": "mock", "tts": settings.tts_provider}
```

- `TTS_PROVIDER=mock|real`；`real` 时 A 会 `from app.providers import real_tts` 并调用
  `real_tts.build(settings)`——**这个模块由 B 提供**，未提供时启动直接报
  `TTS_PROVIDER=real but app/providers/real_tts.py does not exist yet`，不会假装成功。
- `providers` 状态由实际构建的对象推导，`agent_capabilities.py` 不再保存第二份状态；mock 永远不会
  被标成 real。
- config 只放开 TTS：`CHAT_PROVIDER`/`ASR_PROVIDER` 必须是 mock（ASR 本轮延期）。

## 2. FAST-01–04（发布新标签的门槛）

| 编号 | 含义 | 判定方式 | 当前 |
| --- | --- | --- | --- |
| FAST-01 | 前端可用：地址/启动/固定契约/登录→看板样例 | 前端按 `前端接入.md` 跑通 `demo_walkthrough` | ✅ 文档+脚本+实测 |
| FAST-02 | 真实 TTS 接入且标识准确 | `TTS_PROVIDER=real` 启动、`/runtime.providers.tts=="real"`、`AI02` 返回真实音频字节 | ⏳ 等 B 的 `real_tts.build` |
| FAST-03 | 提案播报保留 F1 全文 fixture；无完整音频不计时 | 有匹配语音 → 播报后 60 秒窗口生效；无匹配 → 只有文字、`auto_apply_at` 恒 null | ✅ 回归已覆盖，B 侧 NOTI03 已验 |
| FAST-04 | 真实文字/餐食照片 → 饮食确认落库 | 前端上传照片+文字 → `AGENT01` → `AGENT02 confirm` → `checkin` 落库并在看板可见 | ✅ 主链已通（mock 理解） |

标签策略：FAST-01–04 全绿后再打新标签（例如 `f2-demo-v1`），**不移动 `f1-integrated-v1`**。
未通过项按编号写在下表，不用"部分通过"含混表述。

## 3. 合并与协作约定

- B/C 随时合 `f2/platform`；A 随到随合他们的分支，冲突只改共享文件。
- 新能力登记仍只看实测：`identity/health/agent_capabilities.py` 由各域自己加，A 不代开。
- 只用现有协议与错误码；不新增 DTO、不建第二套 provider 抽象、不做独立验收页面。
- 现有回归基线：`pytest tests -q` → **300 passed, 42 deselected**；`export_contract --check` →
  `4b7ade26…`；`integration_smoke --strict` → 39/0/0。

## 4. 待办与风险

| 项 | 负责 | 说明 |
| --- | --- | --- |
| 真实 TTS | B | 提供 `app/providers/real_tts.py::build(settings)`，返回对象需有 `synthesize(text, voice_id=None) -> Speech`；随后把 `TTS_PROVIDER=real` 跑一遍 FAST-02 |
| 真实文字/照片理解 | C | 只用现有 `AgentTurnWrite`（`text` + `image_asset_ids`），确认动作仍走 `CheckinPort(source="agent_confirmed")` |
| 提案播报文案 | A/B | 可在文案里补"60 秒内未拒绝将生效"，属文案优化，不另建协议 |
| HTTPS/真机播放 | 延期 | 排障限时；先交前端可用 API，不做独立验收页 |
| P1 接口 | 未排期 | 登出/解绑/删计划/撤销提案/记忆导出/推送仍未挂载 |

## 5. 已知边界（不要当缺陷）

- AI 全部 mock；`providers` 如实标 mock（接入真实 TTS 后只有 tts 变 real）。
- 提案语音只有 5 段精确匹配样例；不匹配时保存完整文字、`audio_asset_id=null`、不启动 60 秒窗口。
- 单一 FastAPI 进程 + SQLite + 现有扫描器；不引入 Redis/Celery/向量库/通用工作流。
