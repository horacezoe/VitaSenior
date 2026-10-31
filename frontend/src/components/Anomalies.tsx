import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useSession } from "../state/session";
import { useData } from "../state/data";
import { elderPath, localDay, query, type Schemas } from "../api/client";
import { Button, useResource } from "./ui";
type Anomaly = Schemas["HealthAnomaly"];
export function AnomalyBanner({ anomalies }: { anomalies: Anomaly[] }) {
  if (!anomalies.length) return null;
  return (
    <section className="anomaly-banner" aria-label="当日异常核对记录">
      <h2>异常核对提醒</h2>
      {anomalies.map((a) => (
        <article key={a.anomaly_id}>
          <strong>{a.title}</strong>
          <p>
            {a.status === "resolved"
              ? "后续核对已不再提示此项，此处保留当日历史。"
              : a.detail}
          </p>
          <small>
            {a.status === "resolved"
              ? "后续核对已更新"
              : "大模型提示的潜在问题，尚需专业核验"}{" "}
            · {a.basis === "planned" ? "基于既定计划" : "基于已确认记录"} ·
            AI核对线索
          </small>
        </article>
      ))}
    </section>
  );
}
export function alertKey(
  base: string,
  child: string,
  elder: string,
  a: Anomaly,
) {
  return `vitasenior.alert.${base}.${child}.${elder}.${a.anomaly_id}.${a.revision}`;
}
export function ChildAnomalyNotice() {
  const { api, role, session, elderId } = useSession(),
    { dailyReport, calendarAnomalies, revision } = useData(),
    location = useLocation();
  const selected = /^\/daily\/(\d{4}-\d{2}-\d{2})(?:\/|$)/.exec(
      location.pathname,
    )?.[1],
    today = localDay(api.now());
  const historical = useResource(
    `alert-day:${api.base}:${role}:${elderId}:${selected}`,
    async () =>
      role === "child" && session && elderId && selected && selected !== today
        ? api.get<Schemas["DailyReport"]>(
            elderPath(elderId, "reports/daily") + query({ date: selected }),
          )
        : null,
    revision,
  );
  const [ack, setAck] = useState(0),
    dialog = useRef<HTMLDialogElement>(null);
  const all = [
    ...(dailyReport?.anomalies || []),
    ...(calendarAnomalies || []),
    ...(historical.data?.anomalies || []),
  ];
  const pending =
    role === "child" && session && elderId
      ? unseenAnomalies(
          all,
          (a) =>
            !!sessionStorage.getItem(
              alertKey(api.base, session.user.user_id, elderId, a),
            ),
        )
      : [];
  const signature = pending
    .map((a) => a.anomaly_id + ":" + a.revision)
    .sort()
    .join(",");
  const dismiss = () => {
    if (session && elderId)
      for (const a of pending)
        sessionStorage.setItem(
          alertKey(api.base, session.user.user_id, elderId, a),
          "seen",
        );
    dialog.current?.close();
    setAck((x) => x + 1);
  };
  useEffect(() => {
    const show = () => {
      if (
        signature &&
        document.visibilityState === "visible" &&
        !dialog.current?.open
      )
        dialog.current?.showModal();
    };
    show();
    document.addEventListener("visibilitychange", show);
    return () => document.removeEventListener("visibilitychange", show);
  }, [signature, ack]);
  if (!pending.length) return null;
  return (
    <dialog
      ref={dialog}
      className="anomaly-dialog"
      role="alertdialog"
      aria-labelledby="anomaly-title"
      onCancel={dismiss}
    >
      <h2 id="anomaly-title">请关注长辈的潜在冲突记录</h2>
      <p>以下为记录中发现的核对线索，不代表已发生不良反应。</p>
      {pending.map((a) => (
        <section key={a.anomaly_id}>
          <strong>
            {a.date} · {a.title}
          </strong>
          <p>{a.detail}</p>
          <Link
            className="button button-primary"
            to={`/daily/${a.date}`}
            onClick={dismiss}
          >
            查看对应健康日报
          </Link>
        </section>
      ))}
      <Button variant="secondary" onClick={dismiss}>
        已看到，稍后核对
      </Button>
    </dialog>
  );
}

export function unseenAnomalies(
  items: Anomaly[],
  seen: (a: Anomaly) => boolean,
) {
  const latest = new Map<string, Anomaly>();
  for (const a of items)
    if (
      !latest.has(a.anomaly_id) ||
      latest.get(a.anomaly_id)!.revision <= a.revision
    )
      latest.set(a.anomaly_id, a);
  return Array.from(latest.values()).filter(
    (a) => a.status === "active" && !seen(a),
  );
}
