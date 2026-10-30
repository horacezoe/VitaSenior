# C1 mock 素材

scenarios.json 列出任务单要求的 11 个场景及文本样例。指定 mock_fixture_id 是显式选择演示，不会把任意新照片当固定菜品；不指定 fixture 的未知照片返回 clarify。

mock_audio.py 只对 audio_manifest.json 中 SHA-256 匹配的真实 PCM WAV 返回对应文字。不匹配的录音返回明确错误，不能声称已经识别。TTS 只返回文字完全一致的固定语音；其他文本返回 501，由未来 C2 保留文字并标 tts_unavailable。

五个 WAV 来自 Windows 内置 Microsoft Huihui Desktop 的离线中文语音合成，包含完整实际文本，没有静音或音调代替内容。服务器读取 WAV 不依赖 Windows/SAPI；需要重新生成时，在安装该声音的 Windows 上执行 `generate_audio.ps1`，会重新写入固定音频及完整性清单。生成后的语音不应被当作任意新提案已经完整播报。

exercise_input.wav 为“我散步了20分钟。”；exercise_reply.wav 和 preference_reply.wav 分别是对应的完整模拟回复。生成脚本及清单记录声音与文本来源。这些文件暂未通过 HTTP 提供：仍需要 A0 的 MediaPort.read/register_generated 真实接口来校验、登记、签发播放地址，C 不直接插入媒体表。

C2 新增 greeting.wav，真实内容为“您好”，用于固定问候播报。其余任意新文本仍不得借用该音频冒充播报。

本轮新增 proposal_change_example.wav，逐字播报“孩子申请将医疗备注修改为补充社区复查记录”的固定演示修改及拒绝提示。它只对应此完整固定文本，不能当作任意新提案已经播报的证明。
