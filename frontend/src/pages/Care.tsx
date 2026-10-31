import { useEffect, useRef, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { Heart, Mic, Square } from "lucide-react";
import {
  Button,
  Card,
  ErrorNotice,
  Field,
  Page,
  Success,
  useAction,
} from "../components/ui";
import { elderPath, type Schemas } from "../api/client";
import { useSession } from "../state/session";
import { useData } from "../state/data";
import { WavMessageRecorder } from "../media/message";

const templates = {
  general: "家人惦记着您，有需要时请告诉我们。",
  diet: "记得记录今天的餐食，有需要时告诉我。",
  exercise: "今天活动了吗？可以告诉我您的运动记录。",
  medication: "请核对既定用药任务，服用后请明确确认。",
};
export default function Care() {
  const { api, role, elderId, me } = useSession(),
    { refresh } = useData(),
    action = useAction();
  const [mode, setMode] = useState<"template" | "text" | "voice">("template"),
    [category, setCategory] = useState<keyof typeof templates>("general");
  const [text, setText] = useState(""),
    [repeat, setRepeat] = useState(1),
    [recording, setRecording] = useState(false);
  const [voice, setVoice] = useState<Blob | null>(null),
    [voiceURL, setVoiceURL] = useState(""),
    [uploaded, setUploaded] = useState<string | null>(null);
  const [sent, setSent] = useState<Schemas["Notification"] | null>(null);
  const [paused, setPaused] = useState(false);
  const recordingAttempt = useRef(0);
  const recorder = useRef<WavMessageRecorder | null>(null),
    timeout = useRef<ReturnType<typeof setTimeout> | null>(null),
    mounted = useRef(true);
  const audio = useRef<HTMLAudioElement | null>(null);
  useEffect(() => {
    mounted.current = true;
    const hide = () => {
      if (document.visibilityState !== "visible") {
        recordingAttempt.current++;
        audio.current?.pause();
        if (timeout.current) clearTimeout(timeout.current);
        if (recorder.current) {
          void recorder.current.stop();
          setPaused(true);
          setRecording(false);
        }
      }
    };
    document.addEventListener("visibilitychange", hide);
    return () => {
      mounted.current = false;
      recordingAttempt.current++;
      document.removeEventListener("visibilitychange", hide);
      audio.current?.pause();
      if (timeout.current) clearTimeout(timeout.current);
      void recorder.current?.stop();
    };
  }, []);
  useEffect(() => {
    if (mode !== "voice") audio.current?.pause();
  }, [mode]);
  useEffect(() => {
    if (!voice) return;
    const url = URL.createObjectURL(voice);
    setVoiceURL(url);
    return () => URL.revokeObjectURL(url);
  }, [voice]);
  const finish = () =>
    action.run(async () => {
      if (!recorder.current) return;
      const attempt = recordingAttempt.current;
      try {
        const blob = await recorder.current.finish();
        if (
          mounted.current &&
          attempt === recordingAttempt.current &&
          document.visibilityState === "visible"
        ) {
          setVoice(blob);
          setRecording(false);
          setUploaded(null);
        }
      } finally {
        if (timeout.current) clearTimeout(timeout.current);
        if (mounted.current) setRecording(false);
      }
    });
  const record = () =>
    action.run(async () => {
      audio.current?.pause();
      const attempt = ++recordingAttempt.current;
      setPaused(false);
      const capture = new WavMessageRecorder();
      recorder.current = capture;
      try {
        await capture.start();
        if (
          !mounted.current ||
          document.visibilityState !== "visible" ||
          attempt !== recordingAttempt.current
        ) {
          await capture.stop();
          return;
        }
        setRecording(true);
        timeout.current = setTimeout(() => {
          void finish();
        }, 60000);
      } catch (error) {
        await capture.stop();
        if (
          !mounted.current ||
          document.visibilityState !== "visible" ||
          attempt !== recordingAttempt.current
        )
          return;
        throw error;
      }
    });
  const send = () =>
    action.run(async (keys) => {
      let asset = uploaded;
      if (mode === "voice") {
        if (!voice) throw new Error("请先录制并试听留言。");
        asset =
          asset ||
          (await api.upload(elderId!, voice, "voice_message")).asset_id;
        setUploaded(asset);
      }
      const body: Schemas["FamilyReminderWrite"] = {
        category,
        repeat_count: repeat,
        ...(mode === "template"
          ? { template_id: category }
          : mode === "voice"
            ? {
                audio_asset_id: asset!,
                ...(text.trim() ? { text: text.trim() } : {}),
              }
            : { text: text.trim() }),
      };
      const path = elderPath(elderId!, "family-reminders");
      const result = await api.post<Schemas["Notification"]>(
        path,
        body,
        keys.for(path, body),
      );
      setSent(result);
      refresh();
    });
  if (role !== "child") return <Navigate to="/notifications" replace />;
  return (
    <Page
      title="把关心，送到身边"
      subtitle={`送给 ${me?.bound_elders.find((elder) => elder.elder_id === elderId)?.display_name || "家人"} 的一句叮嘱`}
    >
      {sent ? (
        <>
          <Success>关怀已保存，等待家人进入应用查看</Success>
          <Card>
            <span className="eyebrow">
              <Heart size={15} />
              已送出的心意
            </span>
            <p className="note-card">{sent.text}</p>
            <p className="form-hint">
              {sent.audio_asset_id
                ? "已附可播放语音。"
                : "这次只有完整文字，语音暂不可用。"}
              送出不代表已经接听。
            </p>
            <Link to="/notifications" className="button button-secondary full">
              查看送达与处理进度
            </Link>
          </Card>
        </>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
        >
          <div className="record-filter" role="group" aria-label="关怀方式">
            {[
              ["template", "预设关怀"],
              ["text", "写一段话"],
              ["voice", "录下我的声音"],
            ].map(([value, label]) => (
              <button
                type="button"
                disabled={recording || action.busy}
                className={mode === value ? "active" : ""}
                key={value}
                onClick={() => setMode(value as typeof mode)}
              >
                {label}
              </button>
            ))}
          </div>
          <Card>
            <Field label="关心的日常">
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value as typeof category)}
              >
                <option value="general">日常问候</option>
                <option value="diet">餐食记录</option>
                <option value="exercise">活动记录</option>
                <option value="medication">既定用药任务</option>
              </select>
            </Field>
            {mode === "template" ? (
              <>
                <p className="chat-line">{templates[category]}</p>
                <p className="form-hint">按完整原文调用配置的语音合成服务。</p>
              </>
            ) : (
              <>
                {mode === "voice" && (
                  <div className="section">
                    <Button
                      type="button"
                      variant="secondary"
                      icon={recording ? Square : Mic}
                      loading={action.busy}
                      onClick={() => {
                        void (recording ? finish() : record());
                      }}
                    >
                      {recording
                        ? "结束并使用这段录音"
                        : voice
                          ? "重新录制"
                          : "开始录音"}
                    </Button>
                    <p className="form-hint">最长一分钟，发送前请先试听。</p>
                    {voiceURL && !recording && (
                      <audio
                        ref={audio}
                        aria-label="试听我的留言"
                        src={voiceURL}
                        controls
                        style={{ width: "100%" }}
                      />
                    )}
                  </div>
                )}
                <Field
                  label={
                    mode === "voice" ? "录音说明（可选）" : "想对家人说的话"
                  }
                  hint="文字语音一次最多200字，过长或暂不可用时保留完整文字。"
                >
                  <textarea
                    required={mode === "text"}
                    maxLength={200}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                  />
                </Field>
              </>
            )}
            <Field label="完整播放次数">
              <select
                value={repeat}
                onChange={(e) => setRepeat(Number(e.target.value))}
              >
                <option value={1}>一遍</option>
                <option value={2}>两遍</option>
                <option value={3}>三遍</option>
              </select>
            </Field>
            {paused && (
              <p className="note-card" role="status">
                页面离开前台，录音与试听已停止；中断的录音请重新录制。
              </p>
            )}
            <ErrorNotice error={action.error} />
            <Button
              type="submit"
              icon={Heart}
              loading={action.busy}
              disabled={recording}
              className="full"
            >
              把这份关心送出去
            </Button>
          </Card>
        </form>
      )}
    </Page>
  );
}
