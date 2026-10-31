import { createContext, useContext } from "react";
import type { Checkin, Notification, Schemas } from "../api/client";
import type { RewardLedger } from "./rewards";

type DataState = {
  calendarAnomalies?: Schemas["HealthAnomaly"][];
  observeCalendar?: (
    elder: string,
    anomalies: Schemas["HealthAnomaly"][],
  ) => void;
  dailyReport?: Schemas["DailyReport"] | null;
  revision: number;
  refresh(): void;
  notifications: Notification[];
  notificationError: unknown;
  ledger: RewardLedger | null;
  observe(records: Checkin[], animate?: boolean): void;
};
export const DataContext = createContext<DataState | null>(null);
export const useData = () => {
  const value = useContext(DataContext);
  if (!value) throw new Error("Data context missing");
  return value;
};
