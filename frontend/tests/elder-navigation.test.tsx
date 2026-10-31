import { expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import {
  SessionContext,
  type SessionState,
} from "../src/state/session-context";
import { DataContext } from "../src/state/data-context";
import { NoticeBanner } from "../src/components/NoticeBanner";
import DailyReport from "../src/pages/DailyReport";
import type { Notification } from "../src/api/client";

vi.mock("../src/components/ReportSpeech", () => ({
  default: () => <button>听播报</button>,
}));
vi.mock("../src/components/ui", async (original) => ({
  ...(await original<typeof import("../src/components/ui")>()),
  useResource: () => ({
    data: report,
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));
const report = {
  date: "2026-11-01",
  ai_status: "ready",
  reward_summary: { cumulative: 7, on_date: 2 },
  person: { display_name: "测试老人", conditions: [] },
  records: { diet: [], exercise: [], medication: [] },
  completion: {
    progress: {
      diet: { expected: 3, completed: 0 },
      exercise: { expected: 1, completed: 0 },
      medication: { expected: 0, completed: 0 },
    },
  },
  insights: {
    warm_message: "温情内容",
    elder_praise: "当日总结",
    reminder: "一句提醒",
  },
};
function html(
  content: React.ReactNode,
  role: "elder" | "child" = "elder",
  notifications: Notification[] = [],
) {
  const session = {
    role,
    api: { base: "", now: () => Date.parse("2026-11-01T02:00:00+08:00") },
    elderId: "test",
  } as SessionState;
  return renderToStaticMarkup(
    <MemoryRouter>
      <SessionContext.Provider value={session}>
        <DataContext.Provider
          value={{
            notifications,
            notificationError: null,
            revision: 0,
            refresh: vi.fn(),
            observe: vi.fn(),
            ledger: null,
          }}
        >
          {content}
        </DataContext.Provider>
      </SessionContext.Provider>
    </MemoryRouter>,
  );
}
const note = (id: string, state = "open") =>
  ({
    notification_id: id,
    task_state: state,
    title: "待核对内容",
    audio_asset_id: null,
  }) as Notification;
it("opens a sole pending notice directly, excluding already handled items", () => {
  const page = html(<NoticeBanner />, "elder", [
    note("one"),
    note("old", "handled"),
  ]);
  expect(page).toContain('href="/notifications/one"');
  expect(page).not.toContain('href="/notifications"');
});
it("routes multiple pending items to the inbox instead of selecting the first", () => {
  const page = html(<NoticeBanner />, "elder", [note("one"), note("two")]);
  expect(page).toContain('href="/notifications"');
  expect(page).toContain("2条");
  expect(page).not.toContain("/notifications/one");
});
it("health overview has broadcast, cumulative eggs with today note, then check-ins", () => {
  const page = html(<DailyReport embedded view="health" />);
  expect(page.indexOf("AI管家温情播报")).toBeLessThan(
    page.indexOf("累计鸡蛋积分"),
  );
  expect(page.indexOf("累计鸡蛋积分")).toBeLessThan(
    page.indexOf("三大打卡记录"),
  );
  expect(page).toContain("今日积累");
  expect(page).toContain("温情内容");
  expect(page).not.toContain("当日总结");
});
it("elder dated report contains only greeting/summary and check-ins, without overview blocks", () => {
  const page = html(<DailyReport embedded />);
  expect(page).toContain("小银龄陪您看今天");
  expect(page).toContain("当日总结");
  expect(page).toContain("三大打卡记录");
  expect(page).not.toContain("温情内容");
  expect(page).not.toContain("鸡蛋积分");
  expect(page).not.toContain("一句提醒");
});
it("child report no longer exposes the warm broadcast block", () => {
  const page = html(<DailyReport embedded />, "child");
  expect(page).toContain("长辈基础信息");
  expect(page).not.toContain("AI管家温情播报");
  expect(page).not.toContain("温情内容");
});

it("both roles show the same server cumulative and dated earnings; child footer addresses family", () => {
  const elder = html(<DailyReport embedded view="health" />),
    child = html(<DailyReport embedded />, "child");
  for (const page of [elder, child]) {
    expect(page).toContain('class="report-eggs">7');
    expect(page).toContain("今日积累：2");
  }
  expect(child).toContain("建议您与长辈核对");
  expect(child).not.toContain("一句提醒");
});
