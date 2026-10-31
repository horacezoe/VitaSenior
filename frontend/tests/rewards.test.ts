import { beforeEach, describe, expect, it } from "vitest";
import { RewardLedger } from "../src/state/rewards";
import type { Checkin } from "../src/api/client";

const record = (id = "record-1", patch: Partial<Checkin> = {}): Checkin => ({
  checkin_id: id,
  elder_id: "elder-1",
  type: "exercise",
  local_date: "2026-10-31",
  occurred_at: "2026-10-31T04:00:00Z",
  task_id: null,
  payload: { activity: "散步", duration_minutes: 20 },
  version: 1,
  source: "agent_confirmed",
  created_at: "2026-10-31T04:00:00Z",
  updated_at: "2026-10-31T04:00:00Z",
  cancelled: false,
  ...patch,
});
describe("verified record reward proofs", () => {
  let values: Map<string, string>,
    storage: {
      getItem(key: string): string | null;
      setItem(key: string, value: string): void;
    },
    ledger: RewardLedger;
  beforeEach(() => {
    values = new Map();
    storage = {
      getItem: (key) => values.get(key) || null,
      setItem: (key, value) => {
        values.set(key, value);
      },
    };
    ledger = new RewardLedger("server:elder-1", storage);
  });
  it("does not award seeded history or an empty/pending result", () => {
    ledger.observe([], true);
    ledger.observe([record("seed", { source: "demo_seed" })], true);
    expect(ledger.read()).toEqual([]);
  });
  it("queues one animation for a real record, despite retries and duplicate lists", () => {
    ledger.observe([record()], true);
    ledger.observe([record(), record()], true);
    expect(ledger.read()).toHaveLength(1);
    expect(ledger.pending()).toHaveLength(1);
  });
  it("does not reward a correction or same-meal replacement a second time", () => {
    ledger.observe([record()], true);
    ledger.observe([record("record-1", { version: 2 })], true);
    expect(ledger.read()).toHaveLength(1);
    ledger.complete("record-1");
    ledger.observe([record("record-1", { version: 3 })], true);
    expect(ledger.pending()).toHaveLength(0);
  });
  it("reconciles existing records without replaying old reward animations", () => {
    ledger.observe([record()], false);
    expect(ledger.read()).toHaveLength(1);
    expect(ledger.pending()).toHaveLength(0);
    ledger.observe([record("old-corrected", { version: 2 })], true);
    expect(ledger.read()).toHaveLength(2);
    expect(ledger.pending()).toHaveLength(0);
  });
  it("retains queued proofs across page reloads and consumes each once", () => {
    ledger.observe([record()], true);
    const restarted = new RewardLedger("server:elder-1", storage);
    expect(restarted.pending()).toHaveLength(1);
    restarted.complete("record-1");
    restarted.complete("record-1");
    expect(restarted.pending()).toHaveLength(0);
    expect(restarted.read()).toHaveLength(1);
  });
  it("does not invent a clawback policy when an earned record is cancelled", () => {
    ledger.observe([record()], false);
    ledger.observe([record("record-1", { cancelled: true })], true);
    expect(ledger.read()).toHaveLength(1);
    ledger.observe(
      [record("cancelled-before-observation", { cancelled: true })],
      true,
    );
    expect(ledger.read()).toHaveLength(1);
  });
  it("isolates different elders and API destinations", () => {
    ledger.observe([record()], true);
    expect(new RewardLedger("server:elder-2", storage).read()).toEqual([]);
    expect(new RewardLedger("another-server:elder-1", storage).read()).toEqual(
      [],
    );
  });
});
