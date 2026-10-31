import { useNavigate } from "react-router-dom";
import { useState, useEffect } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import {
  Card,
  Empty,
  ErrorNotice,
  Loading,
  Page,
  useResource,
} from "../components/ui";

import {
  displayDay,
  elderPath,
  localDay,
  query,
  type Schemas,
} from "../api/client";
import { useSession } from "../state/session";
import { useData } from "../state/data";

export default function Calendar({ embedded = false }: { embedded?: boolean }) {
  const { api, elderId, role } = useSession(),
    { revision, observeCalendar } = useData();
  const navigate = useNavigate();
  const today = localDay(api.now()),
    [month, setMonth] = useState(today.slice(0, 7)),
    [day, setDay] = useState(today);
  const calendar = useResource(
    `calendar:${api.base}:${role}:${elderId}:${month}`,
    () =>
      api.get<Schemas["Calendar"]>(
        elderPath(elderId!, "calendar") + query({ month }),
      ),
    revision,
  );
  useEffect(() => {
    if (calendar.data && elderId && role === "child")
      observeCalendar?.(
        elderId,
        calendar.data.days.flatMap((d) => d.anomalies || []),
      );
  }, [calendar.data, elderId, role, observeCalendar]);
  const previous = (offset: number) => {
    const date = new Date(month + "-01T12:00:00+08:00");
    date.setUTCMonth(date.getUTCMonth() + offset);
    const value = localDay(date.getTime()).slice(0, 7);
    setMonth(value);
    setDay(value + "-01");
  };
  const weekday = (new Date(month + "-01T12:00:00+08:00").getUTCDay() + 6) % 7;
  const content = (
    <>
      <Card>
        <div className="calendar-heading">
          <button
            className="icon-button"
            type="button"
            onClick={() => previous(-1)}
            aria-label="上一个月"
          >
            <ChevronLeft size={20} />
          </button>
          <h2>{month.replace("-", " 年 ")} 月</h2>
          <button
            className="icon-button"
            type="button"
            onClick={() => previous(1)}
            aria-label="下一个月"
          >
            <ChevronRight size={20} />
          </button>
        </div>
        <div className="calendar-weekdays">
          {["一", "二", "三", "四", "五", "六", "日"].map((value) => (
            <span key={value}>{value}</span>
          ))}
        </div>
        <div className="calendar-grid">
          {Array.from({ length: weekday }, (_, i) => (
            <span key={`blank-${i}`} />
          ))}
          {calendar.data?.days.map((item) => (
            <button
              type="button"
              key={item.date}
              aria-label={`${item.date}${item.anomalies?.length ? `，有${item.anomalies.length}项异常核对记录` : ""}${item.state === "complete" ? "，适用记录已完成" : item.state === "partial" ? "，部分记录" : item.state === "future" ? "，未来日期" : "，暂无记录"}`}
              aria-pressed={day === item.date}
              className={`state-${item.state} ${item.anomalies?.length ? "has-anomaly" : ""} ${day === item.date ? "selected" : ""}`}
              disabled={item.state === "future"}
              onClick={() => {
                setDay(item.date);
                navigate(`/daily/${item.date}`);
              }}
            >
              {Number(item.date.slice(-2))}
              {!!item.anomalies?.length && (
                <b className="anomaly-day-mark" aria-hidden>
                  !
                </b>
              )}
              {["complete", "partial"].includes(item.state) && (
                <i className="day-dot" />
              )}
            </button>
          ))}
        </div>
        <div className="calendar-legend">
          <span>适用记录完成</span>
          <span>部分记录</span>
          <span>暂无记录</span>
          {calendar.data?.days.some((d) => d.anomalies?.length) && (
            <span className="anomaly-legend">! 异常核对记录</span>
          )}
        </div>
      </Card>
      <ErrorNotice
        error={calendar.error}
        retry={() => {
          void calendar.refresh();
        }}
      />
      <p className="form-hint">
        选择日期查看当天健康日报。圆点表示已有打卡记录，未来日期不可查看。
      </p>
    </>
  );
  return embedded ? (
    <section aria-label="健康日报">{content}</section>
  ) : (
    <Page title="健康日报">{content}</Page>
  );
}
