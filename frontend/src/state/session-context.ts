import { createContext, useContext } from "react";
import type { Api, Schemas, Role } from "../api/client";

export type Session = Schemas["LoginResponse"];
export type Demo = Schemas["DemoExperience"];
export type SessionState = {
  api: Api;
  role: Role;
  session: Session | null;
  me: Schemas["Me"] | null;
  elderId: string | null;
  demo: Demo | null;
  runtime: Schemas["Runtime"] | null;
  connectionError: boolean;
  setRole(role: Role): void;
  login(session: Session): void;
  signOut(): void;
  setElder(id: string): void;
  refreshMe(): Promise<void>;
  createDemo(resetSessions?: boolean, signal?: AbortSignal): Promise<Demo>;
  changeBase(base: string): void;
};
export const SessionContext = createContext<SessionState | null>(null);
export const useSession = () => {
  const value = useContext(SessionContext);
  if (!value) throw new Error("Session context missing");
  return value;
};
