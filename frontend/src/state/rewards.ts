import type { Checkin } from "../api/client";

export type RewardProof = {
  id: string;
  savedAt: string;
  source: string;
  played: boolean;
  queued: boolean;
};
type Store = Pick<Storage, "getItem" | "setItem">;
/** A local index of server-confirmed records, never an invented server balance. */
export class RewardLedger {
  readonly key: string;
  constructor(
    scope: string,
    private store: Store,
  ) {
    this.key = `vitasenior.reward-proofs.${scope}`;
  }
  read(): RewardProof[] {
    try {
      return JSON.parse(this.store.getItem(this.key) || "[]");
    } catch {
      return [];
    }
  }
  observe(records: Checkin[], animate: boolean) {
    const proofs = new Map(this.read().map((proof) => [proof.id, proof]));
    for (const record of records) {
      if (
        record.source === "demo_seed" ||
        record.cancelled ||
        proofs.has(record.checkin_id)
      )
        continue;
      const fresh = animate && record.version === 1;
      proofs.set(record.checkin_id, {
        id: record.checkin_id,
        savedAt: record.created_at,
        source: record.source,
        played: !fresh,
        queued: fresh,
      });
    }
    this.store.setItem(this.key, JSON.stringify([...proofs.values()]));
  }
  complete(id: string) {
    this.store.setItem(
      this.key,
      JSON.stringify(
        this.read().map((proof) =>
          proof.id === id ? { ...proof, played: true, queued: false } : proof,
        ),
      ),
    );
  }
  pending() {
    return this.read().filter((proof) => proof.queued && !proof.played);
  }
}
