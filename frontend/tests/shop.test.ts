import { it, expect } from "vitest";
import { makeOrder, recommendProducts } from "../src/state/shop";
it("creates an explicit demo order for the selected elder with calculated totals", () => {
  const o = makeOrder("elder-a", "演示家人", { towel: 1, cup: 1, socks: 1 });
  expect(o.total).toBe(107);
  expect(o.status).toBe("待确认");
  expect(o.elderId).toBe("elder-a");
});
it("rejects empty baskets and missing recipients, ignores unknown or invalid quantities", () => {
  expect(() => makeOrder("", "", { cup: 1 })).toThrow();
  expect(() => makeOrder("a", "a", { unknown: 100, cup: -1 })).toThrow();
  expect(makeOrder("a", "a", { cup: 2, socks: 99 }).total).toBe(118);
});

it("tailors the basket to diabetes without implying no sugar means no carbs",()=>{
 const r=recommendProducts({conditions:["高血压","2型糖尿病"],allergies:[],medicationNames:["非洛地平缓释片"],verified:true});
 expect(r.items.map(p=>p.id)).toContain("whole-toast");expect(r.reason).toContain("总碳水");
 expect(r.bundle.some(p=>p.id==="vitamin-d")).toBe(false);
});
it("does not treat potassium salt or supplements as universal products",()=>{
 for(const context of [{conditions:["慢性肾脏病G3a","高血压"],verified:true},{conditions:["高血压"],medicationNames:["氯沙坦钾片"],verified:true},{conditions:["高血压"],verified:false}]){
  const r=recommendProducts(context);expect(r.items.map(p=>p.id)).not.toContain("low-salt");
 }
 expect(recommendProducts({conditions:["高血压"],medicationNames:["氨氯地平"],verified:true}).items.map(p=>p.id)).toContain("low-salt");
});
it("rechecks allowed products at order creation and preserves old order catalog",()=>{
 expect(()=>makeOrder("e","家人",{"low-salt":1},["kettle"])).toThrow();
 expect(makeOrder("e","家人",{kettle:1,"vitamin-d":1},["kettle"]).total).toBe(129);
 expect(recommendProducts({allergies:["小麦过敏"],verified:true}).items.map(p=>p.id)).not.toContain("whole-toast");
});
