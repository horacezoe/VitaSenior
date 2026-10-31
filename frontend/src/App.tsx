import DailyReport from "./pages/DailyReport";
import Shop from "./pages/Shop";
import { useEffect, useState } from "react";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { SessionProvider, useSession } from "./state/session";
import { DataProvider } from "./state/data";
import { Empty, Page } from "./components/ui";
import Login from "./pages/Login";
import { ChildHome, ElderHome, HealthPanel } from "./pages/Home";
import Call from "./pages/Call";
import Onboarding from "./pages/Onboarding";
import Binding from "./pages/Binding";
import Settings from "./pages/Settings";
import { Records, RecordEditorPage } from "./pages/Records";
import Calendar from "./pages/Calendar";
import { Profile, Plans, PlanEditorPage, Reminders } from "./pages/Maintenance";
import Memory from "./pages/Memory";
import Care from "./pages/Care";
import {
  Notifications,
  NotificationCall,
  Proposals,
} from "./pages/Notifications";
import Assist from "./pages/Assist";

function Guard({
  children,
  role,
}: {
  children: React.ReactNode;
  role?: "elder" | "child";
}) {
  const state = useSession();
  if (!state.session) return <Navigate to="/login" replace />;
  if (role && state.role !== role)
    return (
      <Navigate to={state.role === "elder" ? "/elder" : "/child"} replace />
    );
  return children;
}
function MobileApp() {
  const { role, session } = useSession(),
    location = useLocation();
  const [large, setLarge] = useState(
    localStorage.getItem("vitasenior.large-text") === "true",
  );
  useEffect(() => {
    const changed = () =>
      setLarge(localStorage.getItem("vitasenior.large-text") === "true");
    window.addEventListener("vitasenior:preferences", changed);
    return () => window.removeEventListener("vitasenior:preferences", changed);
  }, []);
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" });
    document.title = "银龄 · 小银龄陪你每一天";
  }, [location.pathname]);
  return (
    <div className={`app-shell theme-${role}${large ? " large-text" : ""}`}>
      <Routes>
        <Route
          path="/"
          element={
            <Navigate
              replace
              to={session ? (role === "elder" ? "/elder" : "/child") : "/login"}
            />
          }
        />
        <Route
          path="/daily/:date"
          element={
            <Guard>
              <DailyReport key={location.key} />
            </Guard>
          }
        />
        <Route
          path="/daily/:date/:dimension"
          element={
            <Guard>
              <DailyReport key={location.key} />
            </Guard>
          }
        />
        <Route path="/login" element={<Login />} />
        <Route
          path="/shop"
          element={
            <Guard role="child">
              <Shop key={location.key} />
            </Guard>
          }
        />
        <Route path="/settings" element={<Settings />} />
        <Route
          path="/settings/demo"
          element={<Navigate replace to="/settings" />}
        />
        <Route
          path="/elder"
          element={
            <Guard role="elder">
              <ElderHome />
            </Guard>
          }
        />
        <Route
          path="/elder/health"
          element={
            <Guard role="elder">
              <HealthPanel />
            </Guard>
          }
        />
        <Route
          path="/child"
          element={
            <Guard role="child">
              <ChildHome />
            </Guard>
          }
        />
        <Route
          path="/call"
          element={
            <Guard role="elder">
              <Call />
            </Guard>
          }
        />
        <Route
          path="/onboarding"
          element={
            <Guard role="elder">
              <Onboarding />
            </Guard>
          }
        />
        <Route
          path="/binding"
          element={
            <Guard>
              <Binding />
            </Guard>
          }
        />
        <Route
          path="/records"
          element={
            <Guard>
              <Navigate to="/calendar" replace />
            </Guard>
          }
        />
        <Route
          path="/records/:id"
          element={
            <Guard role="elder">
              <RecordEditorPage key={location.pathname + location.search} />
            </Guard>
          }
        />
        <Route
          path="/calendar"
          element={
            <Guard>
              <Calendar />
            </Guard>
          }
        />
        <Route
          path="/profile"
          element={
            <Guard>
              <Profile />
            </Guard>
          }
        />
        <Route
          path="/plans"
          element={
            <Guard>
              <Plans />
            </Guard>
          }
        />
        <Route
          path="/plans/:id"
          element={
            <Guard>
              <PlanEditorPage key={location.pathname} />
            </Guard>
          }
        />
        <Route
          path="/reminders"
          element={
            <Guard>
              <Reminders />
            </Guard>
          }
        />
        <Route
          path="/memory"
          element={
            <Guard>
              <Navigate to="/elder/health" replace />
            </Guard>
          }
        />
        <Route
          path="/care"
          element={
            <Guard role="child">
              <Care />
            </Guard>
          }
        />
        <Route
          path="/notifications"
          element={
            <Guard>
              <Notifications />
            </Guard>
          }
        />
        <Route
          path="/notifications/:id"
          element={
            <Guard>
              <NotificationCall key={location.pathname} />
            </Guard>
          }
        />
        <Route
          path="/proposals"
          element={
            <Guard>
              <Proposals />
            </Guard>
          }
        />
        <Route
          path="/assist"
          element={
            <Guard role="elder">
              <Assist />
            </Guard>
          }
        />
        <Route
          path="*"
          element={
            <Page title="这条路暂时走不到">
              <Empty title="页面没有找到" text="请返回首页，继续您的日常。">
                <a className="button button-secondary" href="/">
                  返回首页
                </a>
              </Empty>
            </Page>
          }
        />
      </Routes>
    </div>
  );
}
export default function App() {
  return (
    <BrowserRouter>
      <SessionProvider>
        <DataProvider>
          <MobileApp />
        </DataProvider>
      </SessionProvider>
    </BrowserRouter>
  );
}
