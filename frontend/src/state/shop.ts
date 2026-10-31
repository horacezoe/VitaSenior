import { uid } from "../api/client";
export const products = [
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
export type DemoOrder = {
  id: string;
  elderId: string;
  elderName: string;
  createdAt: string;
  items: { id: string; quantity: number }[];
  total: number;
  status: "演示订单";
};
export function makeOrder(
  elderId: string,
  elderName: string,
  cart: Record<string, number>,
): DemoOrder {
  const items = products
    .filter(
      (p) => Number.isInteger(cart[p.id]) && cart[p.id] > 0 && cart[p.id] <= 9,
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
    status: "演示订单",
  };
}
