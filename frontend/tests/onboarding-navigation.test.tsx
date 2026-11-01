import { expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import Onboarding from "../src/pages/Onboarding";
import { CallEntry } from "../src/App";
import { SessionContext, type SessionState } from "../src/state/session-context";
import { DataContext } from "../src/state/data-context";

const resource = vi.hoisted(() => ({
  loading: true,
  data: undefined as { onboarding_status: string } | undefined,
  error: null as Error | null,
  refresh: vi.fn(),
}));
vi.mock("../src/components/ui", async (original) => ({
  ...(await original<typeof import("../src/components/ui")>()),
  useResource: () => resource,
}));

it.each([
  ["/onboarding"],
  ["/call", "/onboarding"],
  ["/call", "/elder", "/onboarding"],
])("onboarding always offers a login exit regardless of old history: %j", (...entries) => {
  const session = { api: { base: "", token: "test-token" }, elderId: "new-elder" } as SessionState;
  const page = renderToStaticMarkup(
    <MemoryRouter initialEntries={entries} initialIndex={entries.length - 1}>
      <SessionContext.Provider value={session}>
        <DataContext.Provider value={{ refresh: vi.fn(), revision: 0, notifications: [],
          notificationError: null, ledger: null, observe: vi.fn() }}>
          <Onboarding />
        </DataContext.Provider>
      </SessionContext.Provider>
    </MemoryRouter>,
  );
  expect(page).toMatch(/<a[^>]*aria-label="返回登录"[^>]*href="\/login"/);
  expect(page).not.toContain('aria-label="返回上一页"');
  expect(page).not.toContain('href="/call"');
  expect(page).not.toContain("disabled");
});

it("does not mount camera content while profile is loading, failed or unfinished", () => {
  const session = { api: { base: "", token: "test-token" }, elderId: "new-elder" } as SessionState;
  const render = () => renderToStaticMarkup(<MemoryRouter>
    <SessionContext.Provider value={session}>
      <CallEntry><video aria-label="camera-would-start" /></CallEntry>
    </SessionContext.Provider>
  </MemoryRouter>);
  for (const state of [
    { loading: true, data: undefined, error: null },
    { loading: false, data: undefined, error: new Error("offline") },
    { loading: false, data: { onboarding_status: "draft" }, error: null },
  ]) {
    Object.assign(resource, state);
    expect(render()).not.toContain("camera-would-start");
  }
  Object.assign(resource, { loading: false, data: { onboarding_status: "confirmed" }, error: null });
  expect(render()).toContain("camera-would-start");
  Object.assign(resource, { loading: true, data: undefined, error: null });
});
