import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Api, uid, type Schemas, type Role } from "../api/client";

import { SessionContext, type Session, type Demo } from "./session-context";
export { useSession } from "./session-context";
const baseKey = "vitasenior.api-base";
const getBase = () => localStorage.getItem(baseKey) || "";
const key = (base: string, role: Role) =>
  `vitasenior.session.${base || "same-origin"}.${role}`;
function readSession(base: string, role: Role): Session | null {
  try {
    const value = JSON.parse(
      localStorage.getItem(key(base, role)) || "null",
    ) as Session | null;
    return value && Date.parse(value.expires_at) > Date.now() ? value : null;
  } catch {
    return null;
  }
}
export function SessionProvider({ children }: { children: ReactNode }) {
  const [base, setBase] = useState(getBase);
  const [role, setRoleState] = useState<Role>(() =>
    sessionStorage.getItem("vitasenior.role") === "child" ? "child" : "elder",
  );
  const [session, setSession] = useState<Session | null>(() =>
    readSession(base, role),
  );
  const [me, setMe] = useState<Schemas["Me"] | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [runtime, setRuntime] = useState<Schemas["Runtime"] | null>(null);
  const [connectionError, setConnectionError] = useState(false);
  const current = useRef({ base, role, token: session?.access_token });
  const demoRequest = useRef<{ base: string; key: string; personaId: string } | null>(null);
  current.current = { base, role, token: session?.access_token };
  const [demo, setDemo] = useState<Demo | null>(() => {
    try {
      return JSON.parse(
        localStorage.getItem(`vitasenior.demo.${base}`) || "null",
      );
    } catch {
      return null;
    }
  });
  const signOut = useCallback(() => {
    localStorage.removeItem(key(base, role));
    setSession(null);
    setMe(null);
    setChosen(null);
  }, [base, role]);
  const api = useMemo(
    () =>
      new Api(base, session?.access_token || null, () => {
        if (
          current.current.base === base &&
          current.current.role === role &&
          current.current.token === session?.access_token
        )
          signOut();
      }),
    [base, role, session?.access_token, signOut],
  );
  const refreshMe = useCallback(async () => {
    if (api.token) {
      const result = await api.get<Schemas["Me"]>("/api/v1/me");
      if (result.user.role === "child")
        result.bound_elders = (
          await api.get<Schemas["ElderList"]>("/api/v1/me/elders")
        ).items;
      if (
        current.current.token === api.token &&
        current.current.base === api.base
      )
        setMe(result);
    }
  }, [api]);
  useEffect(() => {
    let alive = true;
    if (session)
      api
        .get<Schemas["Runtime"]>("/api/v1/runtime")
        .then((value) => {
          if (alive) {
            setRuntime(value);
            setConnectionError(false);
          }
        })
        .catch(() => {
          if (alive) setConnectionError(true);
        });
    else
      api
        .get<Schemas["Health"]>("/api/v1/health")
        .then(() => {
          if (alive) {
            setRuntime(null);
            setConnectionError(false);
          }
        })
        .catch(() => {
          if (alive) setConnectionError(true);
        });
    if (session)
      refreshMe().catch(() => {
        if (alive) setConnectionError(true);
      });
    return () => {
      alive = false;
    };
  }, [api, session, refreshMe]);
  useEffect(() => {
    const changed = (event: StorageEvent) => {
      if (event.key === key(base, role)) setSession(readSession(base, role));
    };
    window.addEventListener("storage", changed);
    return () => window.removeEventListener("storage", changed);
  }, [base, role]);
  const setRole = (next: Role) => {
    sessionStorage.setItem("vitasenior.role", next);
    setRoleState(next);
    setSession(readSession(base, next));
    setMe(null);
    setChosen(null);
  };
  const login = (value: Session) => {
    localStorage.setItem(key(base, role), JSON.stringify(value));
    setSession(value);
  };
  const createDemo = async (resetSessions = false, signal?: AbortSignal, personaId = "community_sample_001") => {
    if (!demoRequest.current || demoRequest.current.base !== api.base || demoRequest.current.personaId !== personaId)
      demoRequest.current = { base: api.base, key: uid("demo"), personaId };
    const request = demoRequest.current;
    const value = await api.post<Demo>(
      "/api/v1/demo/experiences",
      { persona_id: personaId },
      request.key,
      signal,
    );
    if (demoRequest.current === request) demoRequest.current = null;
    localStorage.setItem(`vitasenior.demo.${base}`, JSON.stringify(value));
    if (current.current.base === api.base) {
      setDemo(value);
      if (resetSessions) {
        localStorage.removeItem(key(base, "elder"));
        localStorage.removeItem(key(base, "child"));
        setSession(null);
        setMe(null);
        setChosen(null);
      }
    }
    return value;
  };
  const changeBase = (value: string) => {
    let normalized = value.trim().replace(/\/$/, "");
    if (normalized) {
      let url: URL;
      try {
        url = new URL(normalized);
      } catch {
        throw new Error("请填写完整的 http 或 https 地址。");
      }
      if (
        !["http:", "https:"].includes(url.protocol) ||
        url.username ||
        url.password ||
        url.search ||
        url.hash ||
        url.pathname !== "/"
      )
        throw new Error(
          "请填写不带账号、路径或参数的 http 或 https 服务地址。",
        );
      normalized = url.origin;
    }
    localStorage.setItem(baseKey, normalized);
    setBase(normalized);
    setSession(readSession(normalized, role));
    setMe(null);
    setChosen(null);
    setRuntime(null);
    try {
      setDemo(
        JSON.parse(
          localStorage.getItem(`vitasenior.demo.${normalized}`) || "null",
        ),
      );
    } catch {
      setDemo(null);
    }
  };
  const elderId =
    role === "elder"
      ? me?.elder_id || session?.elder_id || null
      : chosen && me?.bound_elders.some((e) => e.elder_id === chosen)
        ? chosen
        : me?.bound_elders[0]?.elder_id || null;
  return (
    <SessionContext.Provider
      value={{
        api,
        role,
        session,
        me,
        elderId,
        demo,
        runtime,
        connectionError,
        setRole,
        login,
        signOut,
        setElder: setChosen,
        refreshMe,
        createDemo,
        changeBase,
      }}
    >
      {children}
    </SessionContext.Provider>
  );
}
