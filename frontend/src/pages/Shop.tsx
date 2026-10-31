import { elderPath,type Schemas } from "../api/client";
import { ChildNav } from "./Home";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ShoppingBag, Gift } from "lucide-react";
import {
  Page,
  Loading,
  Card,
  Button,
  Empty,
  Success,
  ErrorNotice,
  useResource,
} from "../components/ui";
import { ConfirmDialog } from "../components/forms";
import { useSession } from "../state/session";
import { products, recommendProducts, makeOrder, type DemoOrder } from "../state/shop";
export default function Shop() {
  const { api, elderId, me } = useSession();
  if (!me)
    return (
      <Page title="给家人的小心意">
        <Loading />
      </Page>
    );
  return <ShopContent key={`${api.base}.${me?.user.user_id}.${elderId}`} />;
}
function ShopContent() {
  const { api, elderId, me } = useSession(),
    elder = me?.bound_elders.find((e) => e.elder_id === elderId);
  const context=useResource(`shop-context:${api.base}:${elderId}`,async()=>{
    if(!elderId)return null;
    const [profile,plans]=await Promise.all([api.get<Schemas["Profile"]>(elderPath(elderId,"profile")),api.get<Schemas["PlanList"]>(elderPath(elderId,"medication-plans")+"?active=true")]);
    return {conditions:profile.conditions,allergies:profile.allergies,medicationNames:plans.items.map(p=>p.name),verified:profile.onboarding_status === "confirmed"};
  });
  const selection=recommendProducts(context.data || {verified:false});
  const bundleTotal=selection.bundle.reduce((sum,p)=>sum+p.price,0);
  const scope = `vitasenior.shop.${api.base}.${me?.user.user_id}.${elderId}`;
  const [cart, setCart] = useState<Record<string, number>>({}),
    [review, setReview] = useState(false),
    [error, setError] = useState<unknown>(null);
  const [orders, setOrders] = useState<DemoOrder[]>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(scope) || "[]");
      return Array.isArray(saved)
        ? saved.filter(
            (o) => o && o.elderId === elderId && Array.isArray(o.items),
          )
        : [];
    } catch {
      return [];
    }
  });
  const [placed, setPlaced] = useState<DemoOrder | null>(null);
  const total = selection.items.reduce(
    (sum, p) => sum + p.price * (cart[p.id] || 0),
    0,
  );
  const submit = () => {
    try {
      const order = makeOrder(elderId!, elder?.display_name || "家人", cart,selection.items.map(p=>p.id));
      const next = [order, ...orders].slice(0, 20);
      localStorage.setItem(scope, JSON.stringify(next));
      setOrders(next);
      setPlaced(order);
      setCart({});
      setReview(false);
    } catch (e) {
      setError(e);
    }
  };
  return (
    <Page title="给家人的小心意" subtitle="为家人挑选日常所需">
      <p className="note-card">
        当前订单仅供预览，不会付款或配送。
      </p>
      {!elder ? (
        <Empty title="先连接一位家人">
          <Link className="button button-primary" to="/binding">
            连接家人
          </Link>
        </Empty>
      ) : (
        <>
          <Card>
            <span className="eyebrow">为 {elder.display_name} 代买</span>
            <h2>小银龄为家人挑选</h2>
            <p>{selection.reason}</p>
            <small>{selection.bundle.map(p=>p.name).join(" · ")}</small>
            <Button
              icon={Gift}
              disabled={context.loading}
              onClick={() => {
                setCart(Object.fromEntries(selection.bundle.map(p=>[p.id,1])));
                setReview(true);
              }}
            >
              一键代买关怀包 · ¥{bundleTotal}
            </Button>
            <p className="form-hint">更换家人请到设置中的家庭连接。</p>
          </Card>
          {context.loading && <p className="form-hint">正在整理适合家人的选品…</p>}
          {context.error != null && <p className="form-hint">暂时未能读取完整档案，先展示日常备餐用品。</p>}
          <div className="shop-grid">
            {selection.items.map((p) => (
              <Card key={p.id}>
                <span className="shop-art" aria-hidden>
                  {p.icon}
                </span>
                <h3>{p.name}</h3>
                <p>{p.note}</p>
                <strong>¥{p.price}</strong>
                <div className="form-actions">
                  <button
                    type="button"
                    className="icon-button"
                    aria-label={`减少${p.name}`}
                    disabled={!cart[p.id]}
                    onClick={() =>
                      setCart({
                        ...cart,
                        [p.id]: Math.max(0, (cart[p.id] || 0) - 1),
                      })
                    }
                  >
                    −
                  </button>
                  <span aria-live="polite">{cart[p.id] || 0}</span>
                  <button
                    type="button"
                    className="icon-button"
                    aria-label={`增加${p.name}`}
                    disabled={cart[p.id] >= 9}
                    onClick={() =>
                      setCart({ ...cart, [p.id]: (cart[p.id] || 0) + 1 })
                    }
                  >
                    ＋
                  </button>
                </div>
              </Card>
            ))}
          </div>
          <section className="section">
            <h2>补充营养，先核对需要</h2>
            {selection.extra.map(p=><Card key={p.id}><h3>{p.icon} {p.name}</h3><p>{p.note}</p><small>如已有医生或药师确认的补充方案，可与家人核对品种后再选择。</small></Card>)}
          </section>
          <Button
            className="full"
            icon={ShoppingBag}
            disabled={!total}
            onClick={() => setReview(true)}
          >
            核对购物车 · ¥{total}
          </Button>
          {placed && (
            <Success>
              已创建给{placed.elderName}的预览订单，未扣款、未发货。
            </Success>
          )}
          <ErrorNotice error={error} />
          <section className="section">
            <h2>本设备的预览订单</h2>
            {orders.length ? (
              orders.map((o) => (
                <Card className="section" key={o.id}>
                  <span className="tag">{o.status === "演示订单" ? "待确认" : o.status} · 未付款 · 未配送</span>
                  <p>
                    {o.elderName} · ¥{o.total}
                  </p>
                  {o.items.map((i) => (
                    <p key={i.id}>
                      {products.find((p) => p.id === i.id)?.name} × {i.quantity}
                    </p>
                  ))}
                  <small>{new Date(o.createdAt).toLocaleString("zh-CN")}</small>
                </Card>
              ))
            ) : (
              <p className="form-hint">还没有订单记录。</p>
            )}
          </section>
          <ConfirmDialog
            open={review}
            title="核对代买清单"
            close={() => setReview(false)}
            confirm={submit}
          >
            <p>送给：{elder.display_name}</p>
            {selection.items
              .filter((p) => cart[p.id] > 0)
              .map((p) => (
                <p key={p.id}>
                  {p.name} × {cart[p.id]} · ¥{p.price * cart[p.id]}
                </p>
              ))}
            <strong>合计 ¥{total}</strong>
            <p>确认后仅保存在本设备，不进行真实交易。</p>
          </ConfirmDialog>
        </>
      )}
      <ChildNav />
    </Page>
  );
}
