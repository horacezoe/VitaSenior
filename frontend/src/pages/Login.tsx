import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Phone, HeartHandshake } from "lucide-react";
import { type Schemas } from "../api/client";
import { useSession } from "../state/session";
import {
  Avatar,
  Brand,
  Button,
  ErrorNotice,
  Field,
  useAction,
} from "../components/ui";

export default function Login() {
  const { api, role, setRole, login, connectionError } = useSession();
  const navigate = useNavigate(),
    action = useAction();
  const [phone, setPhone] = useState(""),
    [code, setCode] = useState(""),
    [challenge, setChallenge] = useState<string | null>(null);
  const changeRole = (value: "elder" | "child") => {
    action.clearError();
    setRole(value);
    setPhone("");
    setChallenge(null);
    setCode("");
  };
  const sendCode = () =>
    action.run(async (keys) => {
      const body = { phone, role },
        path = "/api/v1/auth/code";
      const value = await api.post<Schemas["CodeResponse"]>(
        path,
        body,
        keys.for(path, body),
      );
      setChallenge(value.challenge_id);
    });
  const submit = () =>
    action.run(async (keys) => {
      if (!challenge) return;
      const body = { phone, role, challenge_id: challenge, code },
        path = "/api/v1/auth/login";
      const value = await api.post<Schemas["LoginResponse"]>(
        path,
        body,
        keys.for(path, body),
      );
      login(value);
      navigate(role === "elder" ? "/elder" : "/child", { replace: true });
    });
  return (
    <main className="login-page">
      <div className="login-top">
        <Brand />
        <span className="small-label">你自在，我安心</span>
      </div>
      <section className="login-intro">
        <Avatar />
        <span className="eyebrow">你自在，我安心</span>
        <h1>
          你好，
          <br />
          我是小银龄<span className="title-dot">。</span>
        </h1>
        <p>
          陪你聊聊今天，
          <br />
          也帮家人多一份安心。
        </p>
      </section>
      <section className="login-form">
        <div className="role-switch" role="group" aria-label="选择身份">
          <button
            type="button"
            disabled={action.busy}
            aria-pressed={role === "elder"}
            className={role === "elder" ? "selected" : ""}
            onClick={() => changeRole("elder")}
          >
            <Phone size={18} />
            我自己使用
          </button>
          <button
            type="button"
            disabled={action.busy}
            aria-pressed={role === "child"}
            className={role === "child" ? "selected" : ""}
            onClick={() => changeRole("child")}
          >
            <HeartHandshake size={18} />
            我来关心家人
          </button>
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void (challenge ? submit() : sendCode());
          }}
        >
          <Field label="手机号码">
            <input
              disabled={action.busy}
              autoComplete="tel"
              inputMode="tel"
              aria-label="手机号码"
              placeholder="请输入手机号码"
              value={phone}
              required
              pattern="[0-9]{11}"
              maxLength={11}
              onChange={(e) => {
                action.clearError();
                setPhone(e.target.value);
                setChallenge(null);
              }}
            />
          </Field>
          {challenge && (
            <Field
              label="验证码"
              hint="请填写验证码"
            >
              <input
                disabled={action.busy}
                autoComplete="one-time-code"
                inputMode="numeric"
                aria-label="验证码"
                value={code}
                required
                onChange={(e) => setCode(e.target.value)}
              />
            </Field>
          )}
          <ErrorNotice error={action.error} />
          {connectionError && (
            <p className="form-hint">暂时未能连接服务，请稍后重试。</p>
          )}
          <Button
            type="submit"
            icon={ArrowRight}
            loading={action.busy}
            className="full"
          >
            {challenge ? "安心登录" : "获取验证码"}
          </Button>
        </form>
      </section>
      <footer className="login-footer">
        <span>你自在，我安心</span>

      </footer>
    </main>
  );
}
