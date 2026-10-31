import { it, expect } from "vitest";
import { makeOrder } from "../src/state/shop";
it("creates an explicit demo order for the selected elder with calculated totals", () => {
  const o = makeOrder("elder-a", "演示家人", { towel: 1, cup: 1, socks: 1 });
  expect(o.total).toBe(107);
  expect(o.status).toBe("演示订单");
  expect(o.elderId).toBe("elder-a");
});
it("rejects empty baskets and missing recipients, ignores unknown or invalid quantities", () => {
  expect(() => makeOrder("", "", { cup: 1 })).toThrow();
  expect(() => makeOrder("a", "a", { unknown: 100, cup: -1 })).toThrow();
  expect(makeOrder("a", "a", { cup: 2, socks: 99 }).total).toBe(118);
});
