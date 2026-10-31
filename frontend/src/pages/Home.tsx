import Calendar from "./Calendar";
import { Link, Navigate } from "react-router-dom";
import {
  ShoppingBag,
  ArrowUpRight,
  Bell,
  CalendarDays,
  Heart,
  HeartPulse,
  Phone,
  Settings,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import {
  Avatar,
  Brand,
  Button,
  Card,
  Empty,
  ErrorNotice,
  Loading,
  MenuLink,
  Page,
  useResource,
  useAction,
} from "../components/ui";
import { EggBasket } from "../components/EggBasket";
import { ProgressTiles, RecordRow, reminderTitle } from "../components/records";
import { displayDay, elderPath, localDay, type Schemas } from "../api/client";
import { useSession } from "../state/session";
import { useData } from "../state/data";
import { NoticeBanner } from "../components/NoticeBanner";

export function ElderHome() {
  const { api, elderId, runtime } = useSession(),
    { revision } = useData();
  const resource = useResource(
    `elder-home:${api.base}:${elderId}`,
    async () => {
      const profile = await api.get<Schemas["Profile"]>(
        elderPath(elderId!, "profile"),
      );
      const dashboard =
        profile.onboarding_status === "confirmed"
          ? await api.get<Schemas["Dashboard"]>(
              elderPath(elderId!, "dashboard"),
            )
          : null;
      return { profile, dashboard };
    },
    revision,
  );
  if (resource.data?.profile.onboarding_status === "draft")
    return <Navigate to="/onboarding" replace />;
  const name = resource.data?.profile.display_name || "朋友";
  const hour = Number(
    new Intl.DateTimeFormat("en-US", {
      hour: "numeric",
      hour12: false,
      timeZone: "Asia/Hong_Kong",
    }).format(api.now()),
  );
  const greeting =
    hour < 11
      ? "早上好"
      : hour < 14
        ? "中午好"
        : hour < 18
          ? "下午好"
          : "晚上好";
  return (
    <main className="page elder-home">
      <header className="home-heading">
        <Brand />
        <Link to="/settings" className="icon-button" aria-label="设置">
          <Settings size={22} strokeWidth={1.6} />
        </Link>
      </header>
      <div className="greeting">
        <p>{displayDay(localDay(api.now()))}</p>
        <h1>
          {greeting}，{name}
          <span className="greeting-leaf">❧</span>
        </h1>
      </div>
      <ErrorNotice
        error={resource.error}
        retry={() => {
          void resource.refresh();
        }}
      />
      <section className="companion-hero">
        <div className="hero-badge">
          <span className="status-dot" />
          {runtime?.providers.chat === "mock"
            ? "演示模式 · 小银龄陪伴中"
            : "今天，也有小银龄陪着你"}
        </div>
        <Avatar />
        <div className="companion-copy">
          <h2>聊聊今天的生活</h2>
          <p>
            吃了什么，走了多远，
            <br />
            生活里的小事，我都愿意听。
          </p>
        </div>
        <Link className="button button-primary call-entry" to="/call">
          <span className="call-entry-icon">
            <Phone size={25} fill="currentColor" strokeWidth={1.3} />
          </span>
          <span>
            和小银龄通话<small>说说话，记下每一天</small>
          </span>
          <ArrowUpRight size={22} />
        </Link>
      </section>
      <NoticeBanner />
      <Link className="health-shortcut" to="/elder/health">
        <span className="health-shortcut-icon">
          <HeartPulse size={25} strokeWidth={1.5} />
        </span>
        <span>
          <strong>我的健康</strong>
          <small>健康日报与个人档案</small>
        </span>
        <ArrowUpRight size={21} />
      </Link>
      <EggBasket />
      <footer className="home-footer">
        <ShieldCheck size={14} />
        <span>用心陪伴，安心记录</span>
      </footer>
    </main>
  );
}

export function ChildHome() {
  const { api, me, elderId, setElder, refreshMe, connectionError } =
      useSession(),
    { revision } = useData(),
    action = useAction();
  const resource = useResource(
    `child-home:${api.base}:${elderId}`,
    async () =>
      elderId
        ? api.get<Schemas["Dashboard"]>(elderPath(elderId, "dashboard"))
        : null,
    revision,
  );
  if (!me)
    return (
      <Page
        title="正在了解家人的近况"
        back={false}
        action={
          <Link to="/settings" className="icon-button" aria-label="设置">
            <Settings size={22} />
          </Link>
        }
      >
        {connectionError ? (
          <Empty title="暂未连上家人的信息" text="请核对连接后，再试一次。">
            <Button
              loading={action.busy}
              onClick={() => {
                void action.run(refreshMe);
              }}
            >
              重新读取
            </Button>
          </Empty>
        ) : (
          <Loading />
        )}
        <ErrorNotice error={action.error} />
      </Page>
    );
  if (!elderId)
    return (
      <Page
        title="把关心，送到身边"
        subtitle="先与家人建立连接"
        back={false}
        action={
          <Link to="/settings" className="icon-button" aria-label="设置">
            <Settings size={22} />
          </Link>
        }
      >
        <div className="unbound-hero">
          <span className="family-symbol">
            <Heart size={54} strokeWidth={1.1} />
          </span>
          <h2>
            多一份了解
            <br />
            少一些牵挂
          </h2>
          <p>
            输入家人分享的四位绑定码，
            <br />
            看看他们今天过得怎么样。
          </p>
          <Link className="button button-primary" to="/binding">
            绑定我的家人
          </Link>
        </div>
        <Button
          variant="text"
          loading={action.busy}
          onClick={() => {
            void action.run(refreshMe);
          }}
        >
          我已绑定，刷新看看
        </Button>
        <ErrorNotice error={action.error} />
      </Page>
    );
  const dashboard = resource.data;
  const records = dashboard
    ? [
        ...dashboard.today_records.diet,
        ...dashboard.today_records.exercise,
        ...dashboard.today_records.medication,
      ].sort((a, b) => b.occurred_at.localeCompare(a.occurred_at))
    : [];
  return (
    <main className="page child-home">
      <header className="home-heading">
        <Brand />
        <Link to="/settings" className="icon-button" aria-label="设置">
          <Settings size={22} />
        </Link>
      </header>
      <div className="child-title">
        <span className="eyebrow">把安心，送给彼此</span>
        <h1>
          家人的日常，
          <br />
          我们一起放在心上。
        </h1>
      </div>
      <p>
        正在关心：
        {me?.bound_elders.find((e) => e.elder_id === elderId)?.display_name}
      </p>
      <Calendar embedded />{" "}
      <ErrorNotice
        error={resource.error}
        retry={() => {
          void resource.refresh();
        }}
      />
      {resource.loading && !dashboard ? (
        <Loading />
      ) : (
        dashboard && (
          <>
            <Link className="care-entry" to="/care">
              <span className="care-heart">
                <Heart size={26} strokeWidth={1.5} />
              </span>
              <span>
                <strong>送一份关心</strong>
                <small>一句叮嘱，或一段熟悉的声音</small>
              </span>
              <ArrowUpRight size={22} />
            </Link>
            {dashboard.attention_items.length > 0 && (
              <section className="attention">
                <h3>
                  <Bell size={18} />
                  可以关心一下
                </h3>
                {dashboard.attention_items.slice(0, 3).map((item) => (
                  <Link key={item.id} to="/care">
                    {reminderTitle(item.title)}
                    <span>送个提醒 →</span>
                  </Link>
                ))}
                <small>暂无记录，不代表实际未完成。</small>
              </section>
            )}
            <div className="quiet-links">
              <MenuLink
                to="/profile"
                icon={UserRound}
                title="协助维护"
                text="档案、用药与提醒设置"
              />
            </div>
          </>
        )
      )}
      <ChildNav />
    </main>
  );
}
export function ChildNav() {
  return (
    <nav className="child-nav" aria-label="家人端导航">
      <Link to="/child">
        <HeartPulse size={22} />
        <span>家人近况</span>
      </Link>

      <Link to="/shop">
        <ShoppingBag size={22} />
        <span>虚拟商城</span>
      </Link>
      <Link to="/settings">
        <UserRound size={22} />
        <span>我的</span>
      </Link>
    </nav>
  );
}

export function HealthPanel() {
  return (
    <Page title="健康日报">
      <Calendar embedded />
      <div className="menu-card section">
        <MenuLink
          to="/profile"
          icon={UserRound}
          title="个人档案"
          text="档案、用药计划与提醒设置"
        />
        <MenuLink to="/notifications" icon={Bell} title="家人留言与提醒" />
      </div>
    </Page>
  );
}
