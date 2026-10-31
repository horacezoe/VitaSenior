import { expect, it } from "vitest";
import { reportMetrics } from "../src/state/report";
import type { Schemas } from "../src/api/client";
const record = (id: string, source: string, payload: object) => ({
  checkin_id: id,
  source,
  payload,
  cancelled: false,
});
it("uses confirmed facts, counts food groups once per meal and excludes seed eggs", () => {
  const r = {
    records: {
      diet: [
        record("meal", "user", {
          food_groups: ["vegetable", "vegetable", "protein"],
        }),
      ],
      exercise: [record("walk", "demo_seed", { duration_minutes: 20 })],
      medication: [
        record("med", "agent_confirmed", { intake_status: "not_taken" }),
      ],
    },
    completion: {
      progress: {
        diet: { expected: 3, completed: 1 },
        exercise: { expected: 1, completed: 1 },
        medication: { expected: 2, completed: 0 },
      },
    },
  } as unknown as Schemas["DailyReport"];
  const m = reportMetrics(r);
  expect(m.eggs).toBe(2);
  expect(m.groups.vegetable).toBe(1);
  expect(m.minutes).toBe(20);
  expect(m.adherence).toBe(0);
});
it("never presents an unset medication plan as 100 percent adherence", () => {
  const r = {
    records: { diet: [], exercise: [], medication: [] },
    completion: {
      progress: {
        diet: { expected: 3, completed: 0 },
        exercise: { expected: 1, completed: 0 },
        medication: { expected: 0, completed: 0 },
      },
    },
  } as unknown as Schemas["DailyReport"];
  expect(reportMetrics(r).adherence).toBeNull();
  expect(reportMetrics(r).eggs).toBe(0);
});
