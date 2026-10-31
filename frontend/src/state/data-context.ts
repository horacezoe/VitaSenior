import { createContext, useContext } from "react";
import type { Checkin, Notification } from "../api/client";
import type { RewardLedger } from "./rewards";

type DataState = {
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
