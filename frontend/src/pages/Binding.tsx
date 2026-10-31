import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { HeartHandshake, Volume2 } from "lucide-react";
import {
  Button,
  Card,
  ErrorNotice,
  Field,
  Page,
  useAction,
} from "../components/ui";
import { useSession } from "../state/session";
import { elderPath, type Schemas } from "../api/client";
import { SpeechPlayer } from "../media/player";

export default function Binding() {
  const { api, role, elderId, refreshMe } = useSession(),
    action = useAction(),
    navigate = useNavigate();
  const [binding, setBinding] = useState<Schemas["BindingCode"] | null>(null),
    [code, setCode] = useState("");
  const [preview, setPreview] = useState<Schemas["BindingPreview"] | null>(
      null,
    ),
    [relationship, setRelationship] = useState("子女");
  const player = useRef<SpeechPlayer | null>(null),
    readController = useRef<AbortController | null>(null),
    [now, setNow] = useState(api.now());
  if (!player.current) player.current = new SpeechPlayer();
  useEffect(() => {
    const timer = setInterval(() => setNow(api.now()), 1000);
    return () => {
      clearInterval(timer);
      readController.current?.abort();
      player.current?.stop();
    };
  }, [api]);
  const expired = !!binding && Date.parse(binding.expires_at) <= now;
  const generate = () =>
    action.run(async (keys) => {
      const path = elderPath(elderId!, "binding-codes");
      setBinding(
        await api.post<Schemas["BindingCode"]>(
          path,
          undefined,
          keys.for(path, {}),
        ),
      );
      keys.reset();
      setNow(api.now());
    });
  const inspect = () =>
    action.run(async (keys) => {
      const path = "/api/v1/family-bindings/preview",
        body = { code };
      setPreview(
        await api.post<Schemas["BindingPreview"]>(
          path,
          body,
          keys.for(path, body),
        ),
      );
    });
  const bind = () =>
    action.run(async (keys) => {
      const path = "/api/v1/family-bindings",
        body = { code, relationship };
      await api.post<Schemas["BindingResult"]>(
        path,
        body,
        keys.for(path, body),
      );
      await refreshMe();
      navigate("/child", { replace: true });
    });
  const readCode = () =>
    action.run(async () => {
      if (!binding) return;
      const controller = new AbortController();
      readController.current = controller;
      const speech = await api.post<Schemas["TTSResult"]>(
        "/api/v1/ai/tts",
        {
          elder_id: elderId!,
          text: `您的家人绑定码是，${binding.code.split("").join("，")}。请仅分享给要绑定的家人。`,
        },
        undefined,
        controller.signal,
      );
      await player.current!.play(
        api,
        speech.audio_asset.asset_id,
        controller.signal,
      );
    });
  return (
    <Page
      title={role === "elder" ? "让家人，多一份安心" : "连接我的家人"}
      subtitle={
        role === "elder"
          ? "将四位数字分享给要绑定的家人"
          : "请向家人获取四位绑定码"
      }
    >
      <div className="incoming-hero">
        <span className="family-symbol">
          <HeartHandshake size={49} strokeWidth={1.2} />
        </span>
      </div>
      {role === "elder" ? (
        <Card>
          {binding ? (
            <>
              <div
                className="binding-code"
                aria-label={`绑定码 ${binding.code}`}
              >
                {binding.code.split("").map((digit, i) => (
                  <span key={i}>{digit}</span>
                ))}
              </div>
              <p className="binding-note">
                {expired
                  ? "绑定码已过期，请重新生成"
                  : `有效至 ${new Date(binding.expires_at).toLocaleTimeString("zh-CN", { timeZone: "Asia/Hong_Kong", hour: "2-digit", minute: "2-digit" })}`}
                <br />
                仅使用一次，请只告诉要绑定的家人。
              </p>
              <div className="form-actions">
                <Button
                  variant="secondary"
                  icon={Volume2}
                  disabled={expired}
                  loading={action.busy}
                  onClick={() => {
                    void readCode();
                  }}
                >
                  读出数字
                </Button>
                <Button
                  variant="text"
                  disabled={action.busy}
                  onClick={() => {
                    player.current?.stop();
                    setBinding(null);
                  }}
                >
                  重新生成
                </Button>
              </div>
            </>
          ) : (
            <>
              <p className="binding-note">
                家人绑定后，可以查看您的记录、
                <br />
                送出关怀，并向您提出修改申请。
              </p>
              <Button
                className="full"
                loading={action.busy}
                onClick={() => {
                  void generate();
                }}
              >
                生成家人绑定码
              </Button>
            </>
          )}
        </Card>
      ) : (
        <Card>
          {!preview ? (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void inspect();
              }}
            >
              <Field label="四位绑定码">
                <input
                  inputMode="numeric"
                  autoComplete="off"
                  value={code}
                  maxLength={4}
                  pattern="[0-9]{4}"
                  required
                  placeholder="例如 0123"
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                />
              </Field>
              <Button className="full" type="submit" loading={action.busy}>
                核对家人身份
              </Button>
            </form>
          ) : (
            <>
              <h2>{preview.elder_display_name}</h2>
              <p className="note-card">请确认这是您要关心的家人。</p>
              <Field label="您与家人的关系">
                <select
                  value={relationship}
                  onChange={(e) => setRelationship(e.target.value)}
                >
                  <option>子女</option>
                  <option>儿子</option>
                  <option>女儿</option>
                  <option>配偶</option>
                  <option>亲属</option>
                </select>
              </Field>
              <Button
                className="full"
                loading={action.busy}
                onClick={() => {
                  void bind();
                }}
              >
                确认绑定
              </Button>
              <Button variant="text" onClick={() => setPreview(null)}>
                重新输入
              </Button>
            </>
          )}
        </Card>
      )}
      <ErrorNotice error={action.error} />
    </Page>
  );
}
