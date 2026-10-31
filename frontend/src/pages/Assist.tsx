import { useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Check, ImagePlus, Send, X } from "lucide-react";
import {
  Button,
  Card,
  ErrorNotice,
  Field,
  Page,
  useAction,
} from "../components/ui";
import { type Schemas, type AgentAction, uid } from "../api/client";
import { useSession } from "../state/session";
import { useData } from "../state/data";

type TurnJob = {
  fingerprint: string;
  id: string;
  media?: string;
  body?: Schemas["AgentTurnWrite"];
};
export default function Assist() {
  const { api, elderId } = useSession(),
    { observe, refresh } = useData(),
    [params] = useSearchParams(),
    action = useAction();
  const [conversation, setConversation] = useState<string | undefined>(
    params.get("conversation") || undefined,
  );
  const [text, setText] = useState(""),
    [file, setFile] = useState<File | null>(null),
    [scene, setScene] = useState<"meal" | "ingredient">("meal");
  const [turns, setTurns] = useState<Schemas["AgentTurn"][]>([]),
    [pending, setPending] = useState<AgentAction[]>([]);
  const [decided, setDecided] = useState(new Set<string>()),
    job = useRef<TurnJob | null>(null);
  const send = () =>
    action.run(async (keys) => {
      if (!text.trim() && !file)
        throw new Error("请写一句话，或选择要核对的图片。");
      const fingerprint = JSON.stringify([
        text,
        file?.name,
        file?.lastModified,
        file?.size,
        scene,
        conversation,
      ]);
      if (job.current?.fingerprint !== fingerprint)
        job.current = { fingerprint, id: uid("text-turn") };
      const current = job.current!;
      if (file && !current.media)
        current.media = (await api.upload(elderId!, file, scene)).asset_id;
      if (!current.body)
        current.body = {
          elder_id: elderId!,
          client_turn_id: current.id,
          conversation_id: conversation,
          ...(text.trim() ? { text: text.trim() } : {}),
          image_asset_ids: current.media ? [current.media] : [],
          context: {
            ...(file ? { scene } : {}),
            ...(pending.length === 1
              ? { pending_action_id: pending[0].action_id }
              : {}),
          },
        };
      const path = "/api/v1/agent/turns";
      const turn = await api.post<Schemas["AgentTurn"]>(
        path,
        current.body,
        keys.for(path, current.body),
      );
      setConversation(turn.conversation_id);
      setTurns((old) => [...old, turn]);
      setPending(turn.actions.filter((item) => item.status === "pending"));
      setText("");
      setFile(null);
      job.current = null;
      refresh();
    });
  const decision = (item: AgentAction, value: "confirm" | "cancel") =>
    action.run(async (keys) => {
      const path = `/api/v1/agent/actions/${item.action_id}/decision`,
        body = { decision: value };
      const result = await api.post<Schemas["ActionResult"]>(
        path,
        body,
        keys.for(path, body),
      );
      if (result.result && "checkin_id" in result.result)
        observe([result.result]);
      setDecided((old) => new Set([...old, item.action_id]));
      setPending((old) =>
        old.filter((previous) => previous.action_id !== item.action_id),
      );
      refresh();
    });
  return (
    <Page
      title="用文字慢慢说"
      subtitle="不方便说话时，也能继续同一份核对"
      back="/elder"
    >
      <div className="text-chat" aria-live="polite">
        {!turns.length && (
          <p className="note-card">
            可以说“今天午餐吃了青菜和豆腐”，或者上传餐食照片。先核对，再明确确认保存。
          </p>
        )}
        {turns.slice(-6).map((turn) => (
          <div key={turn.turn_id}>
            <div className="chat-line chat-line-user">
              <small>您说</small>
              {turn.transcript || "发送了一张图片"}
            </div>
            <div className="chat-line">
              <small>小银龄</small>
              {turn.reply.text}
            </div>
          </div>
        ))}
      </div>
      {pending
        .filter((item) => !decided.has(item.action_id))
        .map((item) => (
          <Card key={item.action_id} className="section">
            <span className="tag">等待本人确认</span>
            <p className="note-card" style={{ color: "var(--text)" }}>
              {item.type === "record_diet"
                ? `${{ breakfast: "早餐", lunch: "午餐", dinner: "晚餐" }[item.preview.meal_slot]}：${item.preview.foods.join("、")}`
                : item.type === "record_exercise"
                  ? `${item.preview.activity}，${item.preview.duration_minutes}分钟`
                  : "请核对上方的具体内容。"}
            </p>
            <div className="form-actions">
              <Button
                icon={X}
                variant="secondary"
                loading={action.busy}
                onClick={() => {
                  void decision(item, "cancel");
                }}
              >
                取消
              </Button>
              <Button
                icon={Check}
                loading={action.busy}
                onClick={() => {
                  void decision(item, "confirm");
                }}
              >
                确认并保存
              </Button>
            </div>
            <p className="form-hint">
              需要更正时，请在下面说明，例如“改成晚餐”。
            </p>
          </Card>
        ))}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <Field label="想对小银龄说的话">
          <textarea
            value={text}
            maxLength={4000}
            onChange={(e) => setText(e.target.value)}
            placeholder="您可以慢慢说清楚…"
          />
        </Field>
        <Field label="配一张图片（可选）">
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            capture="environment"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
          />
        </Field>
        {file && (
          <Field label="图片想帮您做什么">
            <select
              value={scene}
              onChange={(e) => setScene(e.target.value as typeof scene)}
            >
              <option value="meal">核对餐食记录</option>
              <option value="ingredient">看看食材，聊聊做法</option>
            </select>
          </Field>
        )}
        <ErrorNotice error={action.error} />
        <Button
          type="submit"
          icon={Send}
          className="full"
          loading={action.busy}
        >
          发送给小银龄
        </Button>
      </form>
    </Page>
  );
}
