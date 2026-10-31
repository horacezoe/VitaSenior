import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  elderPath,
  localDay,
  query,
  uid,
  type Checkin,
  type Notification,
  type Page as ApiPage,
  type Schemas,
} from "../api/client";
import { useSession } from "./session";
import { RewardLedger } from "./rewards";
import { useResource } from "../components/ui";
import { DataContext } from "./data-context";
export { useData } from "./data-context";

export function DataProvider({ children }: { children: ReactNode }) {
  const { api, role, elderId, session } = useSession(),
    [revision, setRevision] = useState(0);
  const scope = `${api.base}:${elderId || ""}`;
  const [syncError, setSyncError] = useState<unknown>(null);
  const ledger = useMemo(
    () => (elderId ? new RewardLedger(scope, localStorage) : null),
    [scope, elderId],
  );
  const profile = useResource(
    `background-profile:${api.base}:${role}:${elderId}`,
    async () =>
      session && elderId && role === "elder"
        ? api.get<Schemas["Profile"]>(elderPath(elderId, "profile"))
        : null,
  );
  const ready =
    !!session &&
    !!elderId &&
    (role !== "elder" || profile.data?.onboarding_status === "confirmed");
  const notifications = useResource(
    `notifications:${api.base}:${role}:${elderId}:${ready}`,
    async () => {
      const items: Notification[] = [],
        seen = new Set<string>();
      let cursor: string | undefined;
      if (ready && role === "elder")
        do {
          const page = await api.get<ApiPage<Notification>>(
            elderPath(elderId!, "notifications") +
              query({ task_state: "open", limit: 100, cursor }),
          );
          items.push(...page.items);
          cursor = page.next_cursor || undefined;
          if (cursor && seen.has(cursor))
            throw new Error("提醒列表未能完整同步，请重新尝试。");
          if (cursor) seen.add(cursor);
        } while (cursor);
      items.sort(
        (a, b) =>
          Number(!!b.proposal_id) - Number(!!a.proposal_id) ||
          Number(b.kind === "family_voice") -
            Number(a.kind === "family_voice") ||
          b.due_at.localeCompare(a.due_at),
      );
      return { items, next_cursor: null };
    },
  );
  useEffect(() => {
    if (revision) {
      void profile.refresh();
      void notifications.refresh();
    }
  }, [revision, profile.refresh, notifications.refresh]);
  const initialised = useRef(new Set<string>());
  const observe = useCallback(
    (records: Checkin[], animate = true) => {
      if (!ledger || role !== "elder") return;
      ledger.observe(
        records.filter((record) => record.elder_id === elderId),
        animate,
      );
      window.dispatchEvent(new Event("vitasenior:rewards"));
    },
    [ledger, role, elderId],
  );
  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    if (!ready) return;
    const update = () => {
      if (document.visibilityState === "visible") refresh();
    };
    const timer = setInterval(update, 20000);
    document.addEventListener("visibilitychange", update);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", update);
    };
  }, [ready, refresh]);
  useEffect(() => setSyncError(null), [api, role, elderId]);
  useEffect(() => {
    if (!ready || role !== "elder") return;
    const controller = new AbortController();
    let alive = true;
    const sync = async () => {
      if (document.visibilityState !== "visible") return;
      const records: Checkin[] = [];
      let cursor: string | undefined;
      try {
        do {
          const page = await api.get<ApiPage<Checkin>>(
            elderPath(elderId!, "checkins") +
              query({ date: localDay(api.now()), limit: 100, cursor }),
            controller.signal,
          );
          records.push(...page.items);
          cursor = page.next_cursor || undefined;
        } while (cursor);
        if (alive) {
          observe(records, initialised.current.has(scope));
          initialised.current.add(scope);
          setSyncError(null);
        }
      } catch (error) {
        if (!controller.signal.aborted && alive) setSyncError(error);
      }
    };
    void sync();
    return () => {
      alive = false;
      controller.abort();
    };
  }, [api, ready, role, elderId, scope, observe, revision, refresh]);
  useEffect(() => {
    if (!ready || role !== "elder") return;
    const clientId =
      sessionStorage.getItem("vitasenior.client-id") || uid("client");
    sessionStorage.setItem("vitasenior.client-id", clientId);
    const presence = () => {
      void api
        .post<Schemas["Presence"]>(elderPath(elderId!, "presence"), {
          client_id: clientId,
          visible: document.visibilityState === "visible",
        })
        .catch((error) => setSyncError(error));
    };
    presence();
    const timer = setInterval(presence, 20000);
    document.addEventListener("visibilitychange", presence);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", presence);
    };
  }, [api, ready, role, elderId]);
  return (
    <DataContext.Provider
      value={{
        revision,
        refresh,
        notifications: notifications.data?.items || [],
        notificationError: notifications.error || profile.error || syncError,
        ledger,
        observe,
      }}
    >
      {children}
    </DataContext.Provider>
  );
}
