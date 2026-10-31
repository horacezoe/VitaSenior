# C mock 素材

scenarios.json 列出任务单要求的 11 个场景及文本样例。指定 mock_fixture_id 是显式选择演示，不会把任意新照片当固定菜品；不指定 fixture 的未知照片返回 clarify。

mock_audio.py 只对 audio_manifest.json 中 SHA-256 匹配的真实 PCM WAV 返回对应文字。不匹配的录音返回明确错误，不能声称已经识别。TTS 只返回文字完全一致的固定语音；其他文本返回 501，C2 保留文字并标 tts_unavailable。

五个 WAV 来自 Windows 内置 Microsoft Huihui Desktop 的离线中文语音合成，包含完整实际文本，没有静音或音调代替内容。服务器读取 WAV 不依赖 Windows/SAPI；需要重新生成时，在安装该声音的 Windows 上执行 `generate_audio.ps1`，会重新写入固定音频及完整性清单。生成后的语音不应被当作任意新提案已经完整播报。

exercise_input.wav 为“我散步了20分钟。”；exercise_reply.wav 和 preference_reply.wav 分别是对应的完整模拟回复。生成脚本及清单记录声音与文本来源。C2 使用真实 MediaPort 校验、登记与签发内容地址，不直接插入媒体表。

C2 新增 greeting.wav，真实内容为“您好”，用于固定问候播报。其余任意新文本仍不得借用该音频冒充播报。

本轮新增 proposal_change_example.wav，逐字播报“孩子申请将医疗备注修改为补充社区复查记录”的固定演示修改及拒绝提示。它只对应此完整固定文本，不能当作任意新提案已经播报的证明。

## 完整提案播报补充（2026-10-31）

新增独立的 `proposal_cases.json`、`proposal_manifest.json` 与五个 `proposal_*_full.wav`，分别包含档案实际备注、关闭运动/语音的设置值、新建计划完整字段、修改计划实际剂量与餐后时段、停用的实际计划及原因。全部由离线 Windows SAPI Huihui 生成，16kHz/16bit/mono PCM；manifest 记录逐字文本与 SHA-256。服务器读取这些文件不依赖 Windows、SAPI 或供应商密钥。它们不扩展已有 ASR 清单，也不承诺任意文本 TTS。

`app.providers.proposal_notice.proposal_text(body, *, plan=None)` 按真实 Pydantic 提案生成完整文字。更新仅播报提交字段，显式 null/空值会说清清除；创建包含默认值；计划修改/停用必须提供 ID 和版本相符的真实 MedicationPlan。`prepare_proposal_notice(body, *, tts, plan=None)` 在所有数据库事务外运行，返回 `(完整文字, SpokenNotice | None)`；`ProposalFixtureTTS()` 只匹配完整文字。不同的备注、用量、时间、计划 ID 等不会复用无关录音。缺素材或已知 provider 失败时仍返回完整文字、无音频，提案应保持 pending_notice。

重新生成（backend 目录，准备素材的 Windows 机器需已安装 Huihui；运行服务器不需要）：

```powershell
python fixtures/agent/prepare_proposal_manifest.py
powershell.exe -NoProfile -NonInteractive -File fixtures/agent/generate_proposal_audio.ps1
python -m pytest tests/agent/test_proposal_notice.py -q
```

A 已在 `666b317` 将默认 CHANGE01 HTTP 接到 C 的完整 body 准备器，删除旧按类别录音；B 的 `d8c2ad1` 已包含真实内容 HTTP 回归并开启 NOTI03。无匹配语音时保存完整文字、audio=null、保持 pending_notice，不启动窗口；固定样例满足本轮 MVP，不代表任意文本 TTS 或手机实际播放已经验收。具体结果见 C 最新交接。
