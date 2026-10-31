import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Bell,
  Check,
  Heart,
  Mic,
  Phone,
  PhoneOff,
  Volume2,
} from "lucide-react";
import {
  Button,
  Card,
  Empty,
  ErrorNotice,
  Loading,
  Page,
  useAction,
  useResource,
} from "../components/ui";
import {
  elderPath,
  friendlyError,
  query,
  uid,
  type Notification,
  type Page as ApiPage,
  type Schemas,
} from "../api/client";
import { useSession } from "../state/session";
import { useData } from "../state/data";
import { SpeechPlayer } from "../media/player";
import { PcmRecorder } from "../media/pcm";
import { reminderTitle } from "../components/records";

const deliveryNames = {
  pending: "待家人看到",
  displayed: "已看到",
  answered: "已接听",
  played: "已完整播报",
};
const taskNames = {
  open: "待处理",
  snoozed: "稍后提醒",
  handled: "已处理",
  dismissed: "已关闭",
};
const deliveryRank = { pending: 0, displayed: 1, answered: 2, played: 3 };
export const proposalNames = {
  pending_notice: "等待完整告知",
  awaiting_decision: "家人决定中",
  applied: "已生效",
  rejected: "已拒绝",
  cancelled: "已取消",
  conflicted: "需要重新核对",
};

export function Notifications() {
  const { api, elderId, role } = useSession(),
    { revision } = useData();
  const [items, setItems] = useState<Notification[]>([]),
    [cursor, setCursor] = useState<string | null>(null),
    action = useAction();
  const resource = useResource(
    `inbox:${api.base}:${role}:${elderId}`,
    () =>
      api.get<ApiPage<Notification>>(
        elderPath(elderId!, "notifications") + query({ limit: 30 }),
      ),
    revision,
  );
  useEffect(() => {
    setItems(resource.data?.items || []);
    setCursor(resource.data?.next_cursor || null);
  }, [resource.data]);
  const more = () =>
    action.run(async () => {
      if (!cursor) return;
      const page = await api.get<ApiPage<Notification>>(
        elderPath(elderId!, "notifications") + query({ limit: 30, cursor }),
      );
      setItems((old) => [...old, ...page.items]);
      setCursor(page.next_cursor);
    });
  return (
    <Page
      title={role === "elder" ? "家人留言与提醒" : "关怀的送达进度"}
      subtitle="发送、看到、接听与处理，分别记录"
    >
      <ErrorNotice
        error={resource.error || action.error}
        retry={() => {
          void resource.refresh();
        }}
      />
      {resource.loading && !resource.data ? (
        <Loading />
      ) : items.length ? (
        items.map((item) => (
          <Link
            to={`/notifications/${item.notification_id}`}
            key={item.notification_id}
            className="notification-card"
            style={{ display: "block" }}
          >
            <span className="proposal-state">
              <Bell size={13} />
              {deliveryNames[item.delivery_state]} ·{" "}
              {taskNames[item.task_state]}
            </span>
            <h3>{reminderTitle(item.title)}</h3>
            <p>{item.text}</p>
            <div className="card-actions">
              <span className="tag">
                {role === "elder"
                  ? item.audio_asset_id
                    ? "打开并接听 →"
                    : "查看完整文字 →"
                  : "查看详情 →"}
              </span>
            </div>
          </Link>
        ))
      ) : (
        <Empty
          title="关心，会在这里相遇"
          text="有新的留言和提醒时，会保留在这里。"
        />
      )}
      {cursor && (
        <Button
          variant="text"
          className="full"
          loading={action.busy}
          onClick={() => {
            void more();
          }}
        >
          查看更多
        </Button>
      )}
    </Page>
  );
}

export function NotificationCall() {
  const { id } = useParams(),
    { api, elderId, role } = useSession(),
    { refresh } = useData(),
    action = useAction();
  const resource = useResource(
    `notification:${api.base}:${role}:${elderId}:${id}`,
    async () => {
      let cursor: string | undefined;
      do {
        const page = await api.get<ApiPage<Notification>>(
          elderPath(elderId!, "notifications") + query({ limit: 100, cursor }),
        );
        const found = page.items.find((item) => item.notification_id === id);
        if (found) return found;
        cursor = page.next_cursor || undefined;
      } while (cursor);
      throw new Error("这条提醒已不可用，请返回列表查看。");
    },
  );
  const [notification, setNotification] = useState<Notification | null>(null),
    [proposal, setProposal] = useState<Schemas["ChangeProposal"] | null>(null);
  const [playing, setPlaying] = useState(false),
    [caption, setCaption] = useState(""),
    [error, setError] = useState<unknown>(null);
  const [now, setNow] = useState(api.now()),
    [voiceOn, setVoiceOn] = useState(false);
  const player = useRef<SpeechPlayer | null>(null),
    abort = useRef(new AbortController()),
    alive = useRef(true);
  const voice = useRef<PcmRecorder | null>(null),
    voiceStream = useRef<MediaStream | null>(null),
    voiceBusy = useRef(false);
  const voiceAbort = useRef<AbortController | null>(null),
    playbackAttempt = useRef(0);
  const stopVoice = () => {
    voiceAbort.current?.abort();
    voiceStream.current?.getTracks().forEach((track) => track.stop());
    void voice.current?.stop();
    voice.current = null;
    voiceStream.current = null;
    setVoiceOn(false);
  };
  const pendingReceipt = useRef<{
    event: Schemas["NotificationEvent"];
    key: string;
  } | null>(null);
  const handlingIds = useRef(new Map<string, string>());
  const current = notification || resource.data;
  useEffect(() => {
    alive.current = true;
    const scope = new AbortController(),
      ownedPlayer = new SpeechPlayer();
    abort.current = scope;
    player.current = ownedPlayer;
    return () => {
      alive.current = false;
      scope.abort();
      voiceAbort.current?.abort();
      ownedPlayer.stop();
      voiceStream.current?.getTracks().forEach((track) => track.stop());
      void voice.current?.stop();
    };
  }, []);
  useEffect(() => {
    if (!resource.data) return;
    setNotification(resource.data);
    if (resource.data.audio_asset_id)
      void player
        .current!.preload(api, resource.data.audio_asset_id)
        .catch(setError);
    if (resource.data.proposal_id)
      void api
        .get<Schemas["ChangeProposal"]>(
          `/api/v1/change-proposals/${resource.data.proposal_id}`,
        )
        .then(setProposal)
        .catch(setError);
  }, [api, resource.data]);
  useEffect(() => {
    if (!proposal) return;
    const timer = setInterval(() => {
      setNow(api.now());
      if (document.visibilityState === "visible")
        void api
          .get<Schemas["ChangeProposal"]>(
            `/api/v1/change-proposals/${proposal.proposal_id}`,
          )
          .then((value) => {
            if (alive.current) setProposal(value);
          })
          .catch(setError);
    }, 2000);
    return () => clearInterval(timer);
  }, [api, proposal?.proposal_id]);
  useEffect(() => {
    if (
      !proposal ||
      ["pending_notice", "awaiting_decision"].includes(proposal.status)
    )
      return;
    voiceStream.current?.getTracks().forEach((track) => track.stop());
    void voice.current?.stop();
    setVoiceOn(false);
    void resource.refresh();
  }, [proposal?.status]);
  const updateDelivery = (next: Notification) =>
    setNotification((old) => {
      if (!old) return next;
      if (deliveryRank[old.delivery_state] > deliveryRank[next.delivery_state])
        return old;
      return {
        ...old,
        delivery_state: next.delivery_state,
        displayed_at: next.displayed_at,
        answered_at: next.answered_at,
        played_at: next.played_at,
      };
    });
  async function event(kind: Schemas["EventType"], eventId?: string) {
    const key = eventId || uid(kind);
    return api.post<Schemas["EventResult"]>(
      `/api/v1/notifications/${id}/events`,
      { event_id: key, event_type: kind },
      key,
      abort.current.signal,
    );
  }
  async function syncCompletion() {
    if (!pendingReceipt.current) return null;
    const { event: payload, key } = pendingReceipt.current;
    const result = await api.post<Schemas["EventResult"]>(
      `/api/v1/notifications/${id}/events`,
      payload,
      key,
      abort.current.signal,
    );
    pendingReceipt.current = null;
    setNotification(result.notification);
    if (result.change_proposal) setProposal(result.change_proposal);
    return result.notification;
  }
  const answer = async () => {
    if (!current?.audio_asset_id || playing) return;
    const attempt = ++playbackAttempt.current;
    setError(null);
    setPlaying(true);
    voice.current?.pause();
    try {
      const wasPending = !!pendingReceipt.current;
      let latest = wasPending ? (await syncCompletion())! : current;
      if (wasPending && latest.delivery_state === "played") {
        setCaption("完整播放状态已同步。");
        refresh();
        return;
      }
      for (
        let index = 0;
        index < current.repeat_count && alive.current;
        index++
      ) {
        // Start on the answer gesture (preloaded ticket), then require the
        // actual displayed/answered sequence AND real ended before completion.
        const playback = player.current!.play(
          api,
          current.audio_asset_id,
          abort.current.signal,
        );
        const receipts = (async () => {
          const displayKey = `vitasenior.display-event.${id}`,
            answerKey = `vitasenior.answer-event.${id}`;
          const displayId =
            sessionStorage.getItem(displayKey) || uid("display");
          sessionStorage.setItem(displayKey, displayId);
          const shown = await event("displayed", displayId);
          if (alive.current) updateDelivery(shown.notification);
          const answerId = sessionStorage.getItem(answerKey) || uid("answer");
          sessionStorage.setItem(answerKey, answerId);
          const answered = await event("answered", answerId);
          if (alive.current) updateDelivery(answered.notification);
        })();
        await Promise.all([playback, receipts]);
        if (
          !alive.current ||
          playbackAttempt.current !== attempt ||
          document.visibilityState !== "visible"
        )
          throw new DOMException("播放已中断", "AbortError");
        const eventId = uid("full-play");
        pendingReceipt.current = {
          event: { event_id: eventId, event_type: "playback_completed" },
          key: eventId,
        };
        latest = (await syncCompletion())!;
        if (latest.delivery_state === "played") break;
      }
      setCaption("完整内容已播报。听完提醒不等于完成打卡。");
      refresh();
    } catch (e) {
      if (playbackAttempt.current === attempt) {
        player.current?.stop();
        if (alive.current)
          setError(
            e instanceof DOMException && e.name === "AbortError"
              ? new Error("播放被中断，请保持页面在前台后重新接听。")
              : e instanceof DOMException && e.name === "NotAllowedError"
                ? new Error("浏览器暂未开始播放，请再点一下接听。")
                : e,
          );
      }
    } finally {
      if (alive.current && playbackAttempt.current === attempt)
        setPlaying(false);
    }
  };
  const stopPlayback = () => {
    playbackAttempt.current++;
    player.current?.stop();
    setPlaying(false);
    setCaption("这次播放已停止，您可以重新接听。");
  };
  const decide = (decision: "accept" | "reject") =>
    action.run(async (keys) => {
      if (!proposal || role !== "elder") return;
      stopVoice();
      player.current?.stop();
      const path = `/api/v1/change-proposals/${proposal.proposal_id}/decision`,
        body = { decision };
      const result = await api.post<Schemas["ChangeProposal"]>(
        path,
        body,
        keys.for(path, body),
      );
      setProposal(result);
      refresh();
    });
  const handle = (kind: "handled" | "snoozed" | "dismissed") =>
    action.run(async (keys) => {
      const eventId = handlingIds.current.get(kind) || uid(kind);
      handlingIds.current.set(kind, eventId);
      const path = `/api/v1/notifications/${id}/events`,
        body = {
          event_id: eventId,
          event_type: kind,
          ...(kind === "snoozed" ? { snooze_minutes: 10 } : {}),
        };
      const result = await api.post<Schemas["EventResult"]>(
        path,
        body,
        keys.for(path, body),
      );
      setNotification(result.notification);
      handlingIds.current.delete(kind);
      refresh();
    });
  const startVoice = () =>
    action.run(async () => {
      if (!proposal || role !== "elder") return;
      stopVoice();
      player.current?.stop();
      if (!navigator.mediaDevices?.getUserMedia)
        throw new Error(
          "语音决定需要安全连接和麦克风，也可以直接使用下方决定按钮。",
        );
      const signal = new AbortController();
      voiceAbort.current = signal;
      const capture = new PcmRecorder();
      voice.current = capture;
      capture.prepare();
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true },
        });
      } catch (error) {
        await capture.stop();
        throw error;
      }
      if (
        !alive.current ||
        signal.signal.aborted ||
        document.visibilityState !== "visible"
      ) {
        stream.getTracks().forEach((track) => track.stop());
        await capture.stop();
        return;
      }
      voiceStream.current = stream;
      try {
        await capture.start(stream, (wav) => {
          if (
            voiceBusy.current ||
            !alive.current ||
            signal.signal.aborted ||
            document.visibilityState !== "visible"
          )
            return;
          voiceBusy.current = true;
          capture.pause();
          void (async () => {
            const media = await api.upload(
              elderId!,
              wav,
              "voice_message",
              signal.signal,
            );
            const asr = await api.post<Schemas["ASRResult"]>(
              "/api/v1/ai/asr",
              { elder_id: elderId!, audio_asset_id: media.asset_id },
              uid("decision-asr"),
              signal.signal,
            );
            if (
              !alive.current ||
              signal.signal.aborted ||
              document.visibilityState !== "visible"
            )
              return;
            const text = asr.transcript.replace(/[\s，,。.!！]/g, "");
            if (text === "拒绝修改" || text === "取消修改")
              await decide("reject");
            else if (text === "接受修改") await decide("accept");
            else {
              setCaption("请明确说“拒绝修改”或“接受修改”，也可以用下方按钮。");
              capture.listen();
            }
          })()
            .catch((e) => {
              if (
                alive.current &&
                !signal.signal.aborted &&
                document.visibilityState === "visible"
              ) {
                setError(e);
                capture.listen();
              }
            })
            .finally(() => {
              voiceBusy.current = false;
            });
        });
        if (alive.current && !signal.signal.aborted) {
          if (!capture.listen())
            throw new Error("录音未开始，请再点一次语音决定，或使用决定按钮。");
          setVoiceOn(true);
          setCaption("我在听，请说“拒绝修改”或“接受修改”。");
        }
      } catch (error) {
        stream.getTracks().forEach((track) => track.stop());
        await capture.stop();
        throw error;
      }
    });
  useEffect(() => {
    const hide = () => {
      if (document.visibilityState !== "visible") {
        playbackAttempt.current++;
        player.current?.stop();
        stopVoice();
        setPlaying(false);
        setCaption("页面离开前台，播放与录音已停止。请重新接听。");
      }
    };
    document.addEventListener("visibilitychange", hide);
    return () => document.removeEventListener("visibilitychange", hide);
  }, []);
  const seconds =
    proposal?.auto_apply_at && proposal.status === "awaiting_decision"
      ? Math.max(
          0,
          Math.ceil((Date.parse(proposal.auto_apply_at) - now) / 1000),
        )
      : null;
  return (
    <Page
      title={role === "elder" ? "一份熟悉的关心" : "关怀详情"}
      back="/notifications"
    >
      <ErrorNotice
        error={resource.error || error || action.error}
        retry={() => {
          setError(null);
          void resource.refresh();
        }}
      />
      {!current ? (
        <Loading />
      ) : (
        <>
          <div className="incoming-hero">
            <span className="family-symbol">
              <Heart size={49} strokeWidth={1.15} />
            </span>
            <h2>
              {current.proposal_id
                ? "家人有一项修改申请"
                : reminderTitle(current.title)}
            </h2>
            <p>
              {deliveryNames[current.delivery_state]} ·{" "}
              {taskNames[current.task_state]}
            </p>
          </div>
          <Card>
            <p
              style={{ whiteSpace: "pre-line", fontSize: 16, lineHeight: 1.9 }}
            >
              {current.text}
            </p>
          </Card>
          {role === "elder" && current.audio_asset_id && (
            <div className="section">
              <Button
                icon={playing ? PhoneOff : Phone}
                variant={playing ? "danger" : "primary"}
                className="full"
                onClick={() => {
                  if (playing) {
                    stopPlayback();
                  } else void answer();
                }}
              >
                {playing
                  ? "结束本次播放"
                  : current.delivery_state === "played"
                    ? "再听一遍"
                    : "接听这份关心"}
              </Button>
              <p className="form-hint">
                按要求完整播放 {current.repeat_count}{" "}
                遍。中途结束不会上报为完整播放。
              </p>
            </div>
          )}
          {!current.audio_asset_id && (
            <p className="note-card">
              这次暂时只有完整文字。没有完整播报，不会启动自动生效倒计时。
            </p>
          )}
          {caption && (
            <p className="notice notice-success" role="status">
              {caption}
            </p>
          )}
          {proposal && (
            <Card className="section">
              <span className="proposal-state">
                <Check size={15} />
                {proposalNames[proposal.status]}
              </span>
              {seconds !== null && (
                <>
                  <div className="countdown" role="timer">
                    {seconds}
                    <small> 秒</small>
                  </div>
                  <p className="form-hint">
                    完整播报后由服务端计时；到期状态仍以服务端确认为准。
                  </p>
                </>
              )}
              {role === "elder" &&
                ["pending_notice", "awaiting_decision"].includes(
                  proposal.status,
                ) && (
                  <>
                    <div className="form-actions">
                      <Button
                        variant="danger"
                        loading={action.busy}
                        onClick={() => {
                          void decide("reject");
                        }}
                      >
                        拒绝这次修改
                      </Button>
                      <Button
                        variant="secondary"
                        loading={action.busy}
                        onClick={() => {
                          void decide("accept");
                        }}
                      >
                        明确接受
                      </Button>
                    </div>
                    <Button
                      className="full"
                      variant="text"
                      icon={Mic}
                      disabled={voiceOn || playing}
                      loading={action.busy}
                      onClick={() => {
                        void startVoice();
                      }}
                    >
                      {voiceOn ? "正在聆听您的决定" : "用语音说明决定"}
                    </Button>
                  </>
                )}
              {proposal.conflict_reason && (
                <p className="notice notice-error">
                  内容或家庭关系已有变化，请重新核对后提出修改。
                </p>
              )}
            </Card>
          )}
          {role === "elder" &&
            !current.proposal_id &&
            ["open", "snoozed"].includes(current.task_state) && (
              <div className="inline-actions">
                <Button
                  variant="secondary"
                  loading={action.busy}
                  onClick={() => {
                    void handle("handled");
                  }}
                >
                  我知道了
                </Button>
                <Button
                  variant="text"
                  loading={action.busy}
                  onClick={() => {
                    void handle("snoozed");
                  }}
                >
                  十分钟后提醒
                </Button>
                <Button
                  variant="text"
                  loading={action.busy}
                  onClick={() => {
                    void handle("dismissed");
                  }}
                >
                  关闭提醒
                </Button>
              </div>
            )}
          {role === "elder" && (
            <Link className="text-button" to={`/call?notification=${id}`}>
              与小银龄说明实际情况 →
            </Link>
          )}
        </>
      )}
    </Page>
  );
}

const fieldNames: Record<string, string> = {
  display_name: "称呼",
  birth_date: "出生日期",
  sex: "性别",
  conditions: "已确认疾病",
  allergies: "过敏信息",
  medical_notes: "健康备注",
  name: "药品名称",
  dose_display: "既定用量",
  schedule: "服药安排",
  start_date: "开始日期",
  end_date: "结束日期",
  medicine_asset_id: "药品照片",
  notes: "备注",
  meals: "餐食提醒",
  exercise: "运动提醒",
  daily_summary: "每日小结",
  voice_enabled: "语音提醒",
};
function humanValue(value: unknown): string {
  if (value === null) return "清空此项";
  if (typeof value === "boolean") return value ? "开启" : "关闭";
  if (Array.isArray(value))
    return value.length ? value.map(humanValue).join("；") : "清空列表";
  if (typeof value === "object" && value) {
    const obj = value as Record<string, unknown>;
    if (obj.slots) return humanValue(obj.slots);
    if (obj.local_time)
      return `${obj.enabled === false ? "关闭" : ""}${obj.slot ? ({ breakfast: "早餐", lunch: "午餐", dinner: "晚餐" } as Record<string, string>)[String(obj.slot)] || "" : ""} ${obj.local_time}`;
    if (obj.meal_slot)
      return `${({ breakfast: "早餐", lunch: "午餐", dinner: "晚餐" } as Record<string, string>)[String(obj.meal_slot)]}后 ${obj.delay_minutes} 分钟`;
    return "已提交对应内容，请在详情中核对";
  }
  return (
    (
      {
        male: "男",
        female: "女",
        other: "其他",
        unknown: "暂未填写",
      } as Record<string, string>
    )[String(value)] || String(value || "空白")
  );
}
export function Proposals() {
  const { api, role, elderId } = useSession(),
    { revision } = useData(),
    [params] = useState("");
  const [extra, setExtra] = useState<Schemas["ChangeProposal"][]>([]),
    [cursor, setCursor] = useState<string | null>(null),
    action = useAction();
  const resource = useResource(
    `proposals:${api.base}:${role}:${elderId}:${params}`,
    () =>
      api.get<ApiPage<Schemas["ChangeProposal"]>>(
        elderPath(elderId!, "change-proposals") + query({ limit: 20 }),
      ),
    revision,
  );
  useEffect(() => {
    setExtra([]);
    setCursor(resource.data?.next_cursor || null);
  }, [resource.data]);
  const more = () =>
    action.run(async () => {
      if (!cursor) return;
      const next = await api.get<ApiPage<Schemas["ChangeProposal"]>>(
        elderPath(elderId!, "change-proposals") + query({ limit: 20, cursor }),
      );
      setExtra((old) => [...old, ...next.items]);
      setCursor(next.next_cursor);
    });
  return (
    <Page
      title="修改申请进展"
      subtitle="原内容保持不变，直到家人决定或按规则生效"
    >
      <ErrorNotice
        error={resource.error || action.error}
        retry={() => {
          void resource.refresh();
        }}
      />
      {resource.loading && !resource.data ? (
        <Loading />
      ) : resource.data?.items.length || extra.length ? (
        [...(resource.data?.items || []), ...extra].map((proposal) => (
          <ProposalCard key={proposal.proposal_id} proposal={proposal} />
        ))
      ) : (
        <Empty title="还没有修改申请" text="协助维护的每一步，都让家人知道。" />
      )}
      {cursor && (
        <Button
          variant="text"
          loading={action.busy}
          onClick={() => {
            void more();
          }}
        >
          查看更多
        </Button>
      )}
    </Page>
  );
}
export function ProposalCard({
  proposal,
}: {
  proposal: Schemas["ChangeProposal"];
}) {
  const { role } = useSession();
  return (
    <Card className="section">
      <span className="proposal-state">{proposalNames[proposal.status]}</span>
      <h2 style={{ fontSize: 19 }}>
        {
          {
            profile: "个人档案",
            reminder_settings: "提醒设置",
            medication_plan: "用药计划",
          }[proposal.target_type]
        }{" "}
        ·{" "}
        {
          { create: "新增", update: "修改", deactivate: "停用" }[
            proposal.operation
          ]
        }
      </h2>
      <dl className="details-list">
        {Object.entries(proposal.patch)
          .filter(([key]) => fieldNames[key])
          .map(([key, value]) => (
            <div key={key}>
              <dt>{fieldNames[key]}</dt>
              <dd>{humanValue(value)}</dd>
              {proposal.before_snapshot && key in proposal.before_snapshot && (
                <small className="muted">
                  原来：
                  {humanValue(
                    (
                      proposal.before_snapshot as unknown as Record<
                        string,
                        unknown
                      >
                    )[key],
                  )}
                </small>
              )}
            </div>
          ))}
      </dl>
      {proposal.operation === "deactivate" && (
        <p className="note-card">申请停用原有计划，保留历史信息。</p>
      )}
      {proposal.auto_apply_at && (
        <p className="form-hint">
          服务端决定时间：
          {new Date(proposal.auto_apply_at).toLocaleTimeString("zh-CN", {
            timeZone: "Asia/Hong_Kong",
          })}
        </p>
      )}
      {proposal.notification_id && role === "elder" && (
        <Link
          className="button button-secondary full"
          to={`/notifications/${proposal.notification_id}`}
        >
          查看完整内容并决定
        </Link>
      )}
      {proposal.conflict_reason && (
        <p className="notice notice-error">
          版本或家庭关系已有变化，需要重新核对。
        </p>
      )}
    </Card>
  );
}
