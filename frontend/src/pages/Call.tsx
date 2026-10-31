import { retryNode, logNode } from "../media/diagnostics";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { PhoneOff, RotateCcw, Volume2, Mic } from "lucide-react";
import { Avatar, Button } from "../components/ui";
import {
  ApiError,
  friendlyError,
  uid,
  type Schemas,
  type AgentAction,
} from "../api/client";
import { useSession } from "../state/session";
import { useData } from "../state/data";
import { cameraFrame, PcmRecorder } from "../media/pcm";
import { SpeechPlayer } from "../media/player";
import { sendVoiceTurn, type VoiceJob } from "../media/turn";

type Mode =
  "starting" | "listening" | "thinking" | "speaking" | "paused" | "error";
type Job = VoiceJob;
const statusText = {
  starting: "正在准备，请稍等",
  listening: "我在听，您慢慢说",
  thinking: "正在想一想",
  speaking: "小银龄正在说话",
  paused: "通话已暂停",
  error: "这次没有听清，我们再试试",
};

export default function Call() {
  const { api, elderId } = useSession(),
    { refresh, notifications } = useData(),
    navigate = useNavigate();
  const [params] = useSearchParams(),
    notificationId = params.get("notification") || undefined;
  const video = useRef<HTMLVideoElement>(null),
    recorder = useRef<PcmRecorder | null>(null);
  const player = useRef<SpeechPlayer | null>(null),
    streams = useRef<MediaStream[]>([]);
  const controller = useRef<AbortController | null>(null),
    alive = useRef(true),
    busy = useRef(false);
  const conversation = useRef<string | undefined>(undefined),
    selected = useRef<string | undefined>(undefined);
  const lastJob = useRef<Job | null>(null),
    modeRef = useRef<Mode>("starting");
  const [mode, setModeState] = useState<Mode>("starting"),
    [caption, setCaption] = useState("");
  const [transcript, setTranscript] = useState(""),
    [cameraMissing, setCameraMissing] = useState(false);
  const [actions, setActions] = useState<AgentAction[]>([]),
    [level, setLevel] = useState(0);
  const [audioBlocked, setAudioBlocked] = useState(false);
  const [restart, setRestart] = useState(0);
  const setMode = (value: Mode) => {
    modeRef.current = value;
    if (alive.current) setModeState(value);
  };
  const active = (signal?: AbortSignal) => {
    if (
      !alive.current ||
      signal?.aborted ||
      document.visibilityState !== "visible"
    )
      throw new DOMException("通话已暂停", "AbortError");
  };
  const listen = () => {
    if (alive.current && document.visibilityState === "visible") {
      if (recorder.current?.listen()) setMode("listening");
      else {
        setCaption(
          recorder.current?.startError
            ? friendlyError(recorder.current.startError)
            : "轻点继续聆听，让麦克风开始工作。",
        );
        setMode("paused");
      }
    }
  };
  async function speak(job: Job, signal: AbortSignal) {
    const turn = job.result!;
    if (!job.ttsId) {
      job.ttsId = turn.reply.audio_asset_id || undefined;
      if (!job.ttsId) {
        try {
          const speech = await retryNode(job.id, "tts", signal, () =>
            api.post<Schemas["TTSResult"]>(
              "/api/v1/ai/tts",
              { elder_id: elderId!, text: turn.reply.text },
              `${job.id}-final-speech`,
              signal,
            ),
          );
          job.ttsId = speech.audio_asset.asset_id;
        } catch (error) {
          if (
            !(error instanceof ApiError) ||
            ![501, 502, 504].includes(error.status)
          )
            throw error;
          active(signal);
          setCaption(`${turn.reply.text}\n这次暂时只有文字。`);
          setMode("paused");
          return;
        }
      }
    }
    active(signal);
    setMode("speaking");
    logNode(job.id, "playback", 1, "started");
    await player.current!.play(api, job.ttsId, signal);
    logNode(job.id, "playback", 1, "succeeded");
    active(signal);
    await new Promise<void>((resolve) => setTimeout(resolve, 400));
    active(signal);
    setAudioBlocked(false);
    listen();
  }
  async function process(job: Job) {
    if (busy.current || !alive.current) return;
    busy.current = true;
    recorder.current?.pause();
    setMode("thinking");
    setAudioBlocked(false);
    const abort = new AbortController();
    controller.current = abort;
    try {
      active(abort.signal);
      if (!job.result) {
        job.result = await sendVoiceTurn(
          api,
          elderId!,
          job,
          {
            conversationId: conversation.current,
            pendingActionId: selected.current,
            notificationId,
          },
          abort.signal,
          () => active(abort.signal),
        );
        conversation.current = job.result.conversation_id;
        selected.current =
          job.result.actions.filter((action) => action.status === "pending")
            .length === 1
            ? job.result.actions.find((action) => action.status === "pending")!
                .action_id
            : undefined;
        if (alive.current) {
          setCaption(job.result.reply.text);
          setTranscript(job.result.transcript);
          setActions(job.result.actions);
        }
        refresh();
      }
      active(abort.signal);
      await speak(job, abort.signal);
    } catch (error) {
      if (!alive.current || controller.current !== abort) return;
      if (error instanceof DOMException && error.name === "AbortError") {
        setMode("paused");
        return;
      }
      const blocked =
        error instanceof DOMException && error.name === "NotAllowedError";
      setAudioBlocked(blocked);
      setCaption(
        blocked ? "点一下，即可听小银龄的回复。" : friendlyError(error),
      );
      setMode("error");
    } finally {
      if (controller.current === abort) busy.current = false;
    }
  }
  useEffect(() => {
    let mounted = true;
    alive.current = true;
    busy.current = false;
    controller.current = null;
    const ownedStreams: MediaStream[] = [],
      ownedRecorder = new PcmRecorder();
    recorder.current = ownedRecorder;
    player.current = new SpeechPlayer();
    async function start() {
      try {
        if (document.visibilityState !== "visible") {
          setMode("paused");
          return;
        }
        if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia)
          throw new Error(
            "通话需要安全连接。请使用 localhost 或手机 HTTPS 地址，也可以先用文字交流。",
          );
        ownedRecorder.prepare();
        setCameraMissing(false);
        const audio = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        });
        if (!mounted || document.visibilityState !== "visible") {
          audio.getTracks().forEach((track) => track.stop());
          if (mounted) setMode("paused");
          return;
        }
        ownedStreams.push(audio);
        streams.current = ownedStreams;
        audio.getAudioTracks().forEach((track) => {
          track.onended = () => {
            if (mounted) {
              ownedRecorder.pause();
              controller.current?.abort();
              player.current?.stop();
              setCaption("麦克风已断开，请检查后继续，或改用文字辅助。");
              setMode("error");
            }
          };
        });
        try {
          const camera = await navigator.mediaDevices.getUserMedia({
            video: {
              facingMode: "environment",
              width: { ideal: 1280 },
              height: { ideal: 720 },
            },
          });
          if (!mounted || document.visibilityState !== "visible") {
            camera.getTracks().forEach((track) => track.stop());
            ownedStreams.forEach((stream) =>
              stream.getTracks().forEach((track) => track.stop()),
            );
            if (mounted) setMode("paused");
            return;
          }
          ownedStreams.push(camera);
          camera.getVideoTracks().forEach((track) => {
            track.onended = () => {
              if (mounted) {
                setCameraMissing(true);
                if (video.current) video.current.srcObject = null;
              }
            };
          });
          if (video.current) {
            video.current.srcObject = camera;
            await video.current.play();
          }
        } catch {
          ownedStreams.forEach((stream) =>
            stream.getVideoTracks().forEach((track) => track.stop()),
          );
          if (video.current) video.current.srcObject = null;
          if (mounted) setCameraMissing(true);
        }
        if (!mounted || document.visibilityState !== "visible") {
          ownedStreams.forEach((stream) =>
            stream.getTracks().forEach((track) => track.stop()),
          );
          if (mounted) setMode("paused");
          return;
        }
        await ownedRecorder.start(
          audio,
          (wav) => {
            if (!mounted || busy.current || modeRef.current !== "listening")
              return;
            ownedRecorder.pause();
            setMode("thinking");
            void cameraFrame(video.current)
              .then((frame) => {
                if (!mounted || document.visibilityState !== "visible") return;
                const job: Job = { id: uid("turn"), audio: wav, frame };
                lastJob.current = job;
                void process(job);
              })
              .catch((error) => {
                if (mounted) {
                  setCaption(friendlyError(error));
                  setMode("error");
                }
              });
          },
          (value) => {
            if (mounted) setLevel(value);
          },
        );
        if (mounted) listen();
      } catch (error) {
        if (mounted) {
          setCaption(friendlyError(error));
          setMode("error");
        }
      }
    }
    void start();
    const visibility = () => {
      if (document.visibilityState !== "visible") {
        ownedRecorder.pause();
        controller.current?.abort();
        player.current?.stop();
        ownedStreams.forEach((stream) =>
          stream.getTracks().forEach((track) => {
            track.enabled = false;
          }),
        );
        setMode("paused");
      }
    };
    document.addEventListener("visibilitychange", visibility);
    return () => {
      mounted = false;
      alive.current = false;
      controller.current?.abort();
      player.current?.stop();
      ownedStreams.forEach((stream) =>
        stream.getTracks().forEach((track) => track.stop()),
      );
      void ownedRecorder.stop();
      if (video.current) video.current.srcObject = null;
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [api, elderId, restart]);
  const hangup = () => {
    alive.current = false;
    controller.current?.abort();
    recorder.current?.pause();
    player.current?.stop();
    streams.current.forEach((stream) =>
      stream.getTracks().forEach((track) => track.stop()),
    );
    navigate("/elder");
  };
  const resume = async () => {
    if (
      !recorder.current?.configured ||
      !streams.current.some((stream) =>
        stream.getAudioTracks().some((track) => track.readyState === "live"),
      )
    ) {
      setMode("starting");
      setRestart((value) => value + 1);
      return;
    }
    try {
      await recorder.current.resume();
    } catch (error) {
      setCaption(friendlyError(error));
      setMode("error");
      return;
    }
    if (!alive.current || document.visibilityState !== "visible") return;
    streams.current.forEach((stream) =>
      stream.getTracks().forEach((track) => {
        track.enabled = true;
      }),
    );
    if (
      lastJob.current &&
      (modeRef.current === "error" || !lastJob.current.result)
    )
      void process(lastJob.current);
    else listen();
  };
  const avatarState =
    mode === "thinking"
      ? "thinking"
      : mode === "speaking"
        ? "speaking"
        : mode === "listening"
          ? "listening"
          : mode === "error"
            ? "error"
            : "idle";
  return (
    <main className="call-page" aria-label="与小银龄通话">
      <video
        ref={video}
        className="camera-preview"
        autoPlay
        muted
        playsInline
        aria-label="摄像头实时预览"
      />
      <div className="call-shade" />
      <div className="call-top">
        <span className="call-private">
          <span className="status-dot" />
          {cameraMissing ? "语音通话" : "小银龄通话"}
        </span>
        <Avatar state={avatarState} className="call-avatar" />
        <h1>小银龄</h1>
        <p role="status" aria-live="polite">
          {statusText[mode]}
        </p>
        {mode === "listening" && (
          <div className="voice-wave" aria-hidden>
            {[0.4, 0.7, 1, 0.6, 0.85, 0.45, 0.7].map((value, i) => (
              <i key={i} style={{ height: `${8 + level * value * 28}px` }} />
            ))}
          </div>
        )}
      </div>
      <div className="call-caption" aria-live="polite">
        {transcript && <small>您说：{transcript}</small>}
        {caption && <p>{caption}</p>}
        {actions.some((action) => action.status === "pending") && (
          <span className="confirm-hint">
            请核对后说“确认”，也可以说“取消”或说明更正。
          </span>
        )}
        {(mode === "error" || mode === "paused") && (
          <div className="call-recovery">
            <Button
              icon={audioBlocked ? Volume2 : RotateCcw}
              variant="light"
              onClick={() => {
                void resume();
              }}
            >
              {audioBlocked
                ? "点一下听回复"
                : lastJob.current && mode === "error"
                  ? "再试一次"
                  : "继续聆听"}
            </Button>
            <Link
              to={`/assist${conversation.current ? `?conversation=${encodeURIComponent(conversation.current)}` : ""}`}
            >
              改用文字辅助
            </Link>
          </div>
        )}
        {mode === "listening" && !caption && (
          <p className="call-first-hint">
            <Mic size={18} />
            聊聊午餐，或说说刚刚完成的运动。
          </p>
        )}
        {notifications.length > 0 && (
          <p className="call-pending">
            有 {notifications.length} 条留言或提醒，可在通话后查看。
          </p>
        )}
      </div>
      <button
        className="hangup"
        type="button"
        onClick={hangup}
        aria-label="挂断电话"
      >
        <PhoneOff size={31} fill="currentColor" strokeWidth={1.4} />
      </button>
      <span className="hangup-label">挂断</span>
    </main>
  );
}
