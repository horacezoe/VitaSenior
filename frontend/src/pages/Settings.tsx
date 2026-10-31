import { useEffect, useRef, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import {
  LogOut,
  HeartHandshake,
  Phone,
  Settings2,
  ArrowRight,
} from "lucide-react";
import {
  Button,
  Card,
  ErrorNotice,
  Field,
  MenuLink,
  Page,
  Success,
  useAction,
} from "../components/ui";
import { useSession } from "../state/session";

const providerLabel = (mode: string) =>
  mode === "real" ? "真实服务" : mode === "mock" ? "演示样例" : "暂未接通";
export default function Settings() {
  const {
    api,
    role,
    setRole,
    signOut,
    session,
    demo,
    runtime,
    changeBase,
    createDemo,
  } = useSession();
  const navigate = useNavigate(),
    action = useAction(),
    [base, setBase] = useState(api.base),
    [saved, setSaved] = useState(false);
  const [large, setLarge] = useState(
    localStorage.getItem("vitasenior.large-text") === "true",
  );
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  const freshDemo = () =>
    action.run(async () => {
      const controller = new AbortController();
      pending.current = controller;
      await createDemo(true, controller.signal);
      navigate("/login", { replace: true });
    });
  const switchRole = (next: "elder" | "child") => {
    setRole(next);
    navigate(next === "elder" ? "/elder" : "/child", { replace: true });
  };
  return (
    <Page
      title="设置与我的"
      subtitle="按自己的节奏，安心使用"
      back={session ? (role === "elder" ? "/elder" : "/child") : "/login"}
    >
      {session && (
        <Card>
          <span className="eyebrow">
            {role === "elder" ? "本人账号" : "关心家人的账号"}
          </span>
          <h2>{session.user.phone}</h2>
          <p className="form-hint">不同身份分别保存登录状态。</p>
        </Card>
      )}
      <div className="menu-card section">
        <MenuLink
          to="/binding"
          icon={HeartHandshake}
          title="家庭连接"
          text="绑定家人或分享绑定码"
        />
        <button
          className="menu-link full"
          type="button"
          onClick={() => switchRole(role === "elder" ? "child" : "elder")}
        >
          <span className="menu-icon">
            <Phone size={23} />
          </span>
          <span>
            <strong>
              {role === "elder" ? "切换到关心家人" : "切换到本人使用"}
            </strong>
            <small>两个身份的数据与权限保持独立</small>
          </span>
          <ArrowRight size={18} />
        </button>
      </div>
      <Card>
        <div className="toggle-row">
          <span>使用更大的文字</span>
          <input
            type="checkbox"
            aria-label="使用更大的文字"
            checked={large}
            onChange={(e) => {
              setLarge(e.target.checked);
              localStorage.setItem(
                "vitasenior.large-text",
                String(e.target.checked),
              );
              window.dispatchEvent(new Event("vitasenior:preferences"));
            }}
          />
        </div>
        <p className="form-hint">
          减少动态效果跟随系统设置，鸡蛋奖励仍会保留。
        </p>
      </Card>
      <section className="form-section">
        <h2>连接设置</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void action.run(async () => {
              changeBase(base);
              setSaved(true);
            });
          }}
        >
          <Field
            label="服务地址"
            hint="与前端同地址时留空。这里不填写模型密钥。"
          >
            <input
              type="url"
              placeholder="默认：与当前页面同地址"
              value={base}
              onChange={(e) => {
                setBase(e.target.value);
                setSaved(false);
              }}
            />
          </Field>
          <Button
            variant="secondary"
            icon={Settings2}
            type="submit"
            loading={action.busy}
          >
            保存连接
          </Button>
        </form>
        {saved && <Success>连接设置已更新</Success>}
        <ErrorNotice error={action.error} />
        <p className="note-card">
          {runtime
            ? `当前语音识别：${providerLabel(runtime.providers.asr)}；交流：${providerLabel(runtime.providers.chat)}；播报：${providerLabel(runtime.providers.tts)}。`
            : "尚未读取到服务状态。"}
        </p>
      </section>
      {demo && (
        <section className="form-section">
          <h2>这组演示家庭</h2>
          <dl className="details-list">
            <div>
              <dt>老人账号</dt>
              <dd>{demo.elder_account.phone}</dd>
            </div>
            <div>
              <dt>子女账号</dt>
              <dd>{demo.child_account.phone}</dd>
            </div>
          </dl>
          <p className="form-hint">
            登录验证码采用演示验证，绑定关系和新记录仍真实保存。
          </p>
        </section>
      )}
      <section className="form-section">
        <h2>重新体验</h2>
        <p className="form-hint">
          创建新演示家庭后，两个身份都需重新登录。原有数据保留。
        </p>
        <Button
          variant="secondary"
          loading={action.busy}
          onClick={() => {
            void freshDemo();
          }}
        >
          创建另一组演示家庭并重新登录
        </Button>
      </section>
      <section className="form-section">
        <h2>奖励与素材</h2>
        <p className="note-card">
          鸡蛋由本设备已核对的真实打卡记录生成。纠正、同餐替换与重试不重复奖励；尚无跨设备奖励余额。取消记录暂不自动扣回已获得的奖励。
        </p>
        <p className="asset-note">
          已接入小银龄的待机、聆听与思考图片；播报和异常暂复用待机图。鸡蛋和篮子仍为中性素材占位。
        </p>
      </section>
      {session && (
        <Button
          variant="text"
          icon={LogOut}
          onClick={() => {
            signOut();
            navigate("/login", { replace: true });
          }}
        >
          退出本设备的当前身份
        </Button>
      )}
      <p className="note-card">
        <Link to="/login">返回登录与体验入口</Link>
      </p>
    </Page>
  );
}
