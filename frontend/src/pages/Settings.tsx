import { exportDiagnostics } from "../media/diagnostics";
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
export default function Settings({ demoMode = false }: { demoMode?: boolean }) {
  const {
    api,
    role,
    setRole,
    signOut,
    session,
    me,
    elderId,
    setElder,
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
      title={demoMode ? "演示设置" : "设置与我的"}
      subtitle="按自己的节奏，安心使用"
      back={session ? (role === "elder" ? "/elder" : "/child") : "/login"}
    >
      {!demoMode && (
        <>
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
        </>
      )}
      {demoMode && (
        <>
          <section className="form-section">
            <h2>连接设置</h2>
            <Button variant="secondary" onClick={exportDiagnostics}>
              导出通话节点日志
            </Button>
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
        </>
      )}
      {!demoMode && (
        <>
          <MenuLink to="/settings/demo" icon={Settings2} title="演示设置" />
          {role === "child" && (
            <Card>
              <Field label="切换正在关心的家人">
                <select
                  value={elderId || ""}
                  onChange={(e) => setElder(e.target.value)}
                >
                  {me?.bound_elders.map((e) => (
                    <option key={e.elder_id} value={e.elder_id}>
                      {e.display_name}
                    </option>
                  ))}
                </select>
              </Field>
              <Link to="/binding">添加家人</Link>
            </Card>
          )}
          <IncentiveRules />
        </>
      )}
      {!demoMode && session && (
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
      {!demoMode && (
        <p className="note-card">
          <Link to="/login">返回登录与体验入口</Link>
        </p>
      )}
    </Page>
  );
}

function IncentiveRules() {
  const [open, setOpen] = useState(false),
    timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stop = () => {
    if (timer.current) clearTimeout(timer.current);
    setOpen(false);
  };
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  return (
    <section className="form-section">
      <h2>
        激励规则{" "}
        <button
          type="button"
          className="icon-button"
          aria-label="长按查看激励规则"
          aria-expanded={open}
          onPointerDown={() => {
            timer.current = setTimeout(() => setOpen(true), 450);
          }}
          onPointerUp={stop}
          onPointerCancel={stop}
          onPointerLeave={stop}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") setOpen(true);
          }}
          onBlur={stop}
        >
          ？
        </button>
      </h2>
      {open && (
        <p role="tooltip" className="note-card">
          每次新的有效打卡奖励一枚鸡蛋，纠正与重试不重复奖励。当前为本设备核对的记录，跨设备余额尚未统一；取消暂不扣回。
        </p>
      )}
    </section>
  );
}
