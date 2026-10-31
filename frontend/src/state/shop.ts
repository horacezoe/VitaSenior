import { uid } from "../api/client";
const legacyProducts = [
  {
    id: "towel",
    name: "柔软棉质毛巾",
    price: 19,
    icon: "🧺",
    note: "日常洗护用品",
  },
  {
    id: "cup",
    name: "轻便保温杯",
    price: 59,
    icon: "☕",
    note: "随手喝一杯温水",
  },
  {
    id: "socks",
    name: "舒适居家袜",
    price: 29,
    icon: "🧦",
    note: "柔软舒适的日常心意",
  },
  {
    id: "bag",
    name: "轻便购物袋",
    price: 15,
    icon: "🛍️",
    note: "出门买菜的小帮手",
  },
] as const;
export type Product = {id:string;name:string;price:number;icon:string;note:string};
const healthProducts:Product[] = [
 {id:"whole-toast",name:"谷禾全麦吐司",price:26,icon:"🍞",note:"全麦主食选择，按份量搭配三餐"},
 {id:"soda",name:"谷禾无添加蔗糖苏打饼干",price:19,icon:"🍘",note:"仍含淀粉，留意总碳水、钠和每次份量"},
 {id:"oats",name:"原味纯燕麦片",price:32,icon:"🥣",note:"无额外糖浆，可替换部分精制主食"},
 {id:"low-salt",name:"轻盐低钠盐",price:12,icon:"🧂",note:"含钾配方；适用性确认后仍需控制总量"},
 {id:"salt-spoon",name:"日常控盐量勺",price:15,icon:"🥄",note:"备餐时看清用量，不改变个人饮食安排"},
 {id:"kettle",name:"暖禾养生壶",price:129,icon:"🫖",note:"清晰容量标识，按个人饮水安排使用"},
 {id:"food-scale",name:"厨房食物电子秤",price:49,icon:"⚖️",note:"主食分份更直观，方便记录餐食"},
 {id:"milk",name:"牧禾无添加糖低脂牛奶",price:39,icon:"🥛",note:"日常乳品选择；乳品过敏者不适用"},
 {id:"vitamin-d",name:"康禾维生素D营养补充剂",price:59,icon:"☀️",note:"按已有补充方案选择，先核对是否需要"},
];
export const products:readonly Product[] = [...legacyProducts,...healthProducts];
export type ShopContext = {conditions?:readonly string[];allergies?:readonly string[];medicationNames?:readonly string[];verified?:boolean};
export function recommendProducts(context:ShopContext) {
 const conditions=(context.conditions||[]).join(" "),allergies=(context.allergies||[]).join(" "),medicines=(context.medicationNames||[]).join(" ");
 const kidney=/肾|高钾/.test(conditions),diabetes=/糖尿病/.test(conditions),bp=/高血压/.test(conditions),lipids=/血脂|冠心病|卒中/.test(conditions);
 const avoidPotassium=kidney || !context.verified || /普利|沙坦|螺内酯|依普利酮|阿米洛利|氨苯蝶啶|氯化钾|枸橼酸钾|演示药品|既定药|降压药/.test(medicines);
 let ids:string[],reason:string;
 if(!context.verified){ids=["kettle","salt-spoon","food-scale"];reason="先为家人挑选便于备餐和日常照护的用品。";}
 else if(kidney){ids=["salt-spoon","food-scale","kettle"];reason="考虑到已有肾脏健康资料，先选择控量和备餐用品，饮食与补充剂按个人方案核对。";}
 else if(diabetes){ids=["whole-toast","soda","oats","food-scale","kettle"];reason="结合已登记的糖尿病背景，优先挑选无添加糖、便于分份的主食。无添加糖也要留意总碳水和份量。";}
 else if(bp||lipids){ids=["oats","whole-toast","salt-spoon","kettle"];reason="结合已登记的心血管健康背景，优先考虑清淡备餐和全谷主食。";}
 else {ids=["oats","whole-toast","kettle","food-scale"];reason="从日常备餐和生活习惯出发，挑选容易搭配的小心意。";}
 if(context.verified && !kidney && !/乳|奶/.test(allergies))ids.push("milk");
 if(bp && !avoidPotassium)ids.push("low-salt");
 const items=ids.map(id=>healthProducts.find(p=>p.id===id)!).filter(p=>!(/小麦|麸质/.test(allergies)&&["whole-toast","soda","oats"].includes(p.id)));
 return {items,reason,bundle:items.slice(0,3),extra:healthProducts.filter(p=>p.id==="vitamin-d"),avoidPotassium};
}
export type DemoOrder = {
  id: string;
  elderId: string;
  elderName: string;
  createdAt: string;
  items: { id: string; quantity: number }[];
  total: number;
  status: "演示订单" | "待确认";
};
export function makeOrder(
  elderId: string,
  elderName: string,
  cart: Record<string, number>,
  allowedIds?:readonly string[],
): DemoOrder {
  const items = products
    .filter(
      (p) => (!allowedIds || allowedIds.includes(p.id)) && Number.isInteger(cart[p.id]) && cart[p.id] > 0 && cart[p.id] <= 9,
    )
    .map((p) => ({ id: p.id, quantity: cart[p.id] }));
  if (!elderId || !items.length) throw new Error("请先选择家人和商品。");
  return {
    id: uid("demo-order"),
    elderId,
    elderName,
    createdAt: new Date().toISOString(),
    items,
    total: items.reduce(
      (sum, i) => sum + products.find((p) => p.id === i.id)!.price * i.quantity,
      0,
    ),
    status: "待确认",
  };
}
