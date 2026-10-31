import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import {
  Card,
  Empty,
  ErrorNotice,
  Loading,
  Page,
  useResource,
} from "../components/ui";
import { ProgressTiles, RecordRow } from "../components/records";
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
    { revision } = useData();
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
  const report = useResource(
    `report:${api.base}:${role}:${elderId}:${day}`,
    () =>
      api.get<Schemas["DailyReport"]>(
        elderPath(elderId!, "reports/daily") + query({ date: day }),
      ),
    revision,
  );
  const previous = (offset: number) => {
    const date = new Date(month + "-01T12:00:00+08:00");
    date.setUTCMonth(date.getUTCMonth() + offset);
    const value = localDay(date.getTime()).slice(0, 7);
    setMonth(value);
    setDay(value + "-01");
  };
  const weekday = (new Date(month + "-01T12:00:00+08:00").getUTCDay() + 6) % 7;
  const records = report.data
    ? [
        ...report.data.records.diet,
        ...report.data.records.exercise,
        ...report.data.records.medication,
      ]
    : [];
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
              aria-label={`${item.date}${item.state === "complete" ? "，适用记录已完成" : item.state === "partial" ? "，部分记录" : item.state === "future" ? "，未来日期" : "，暂无记录"}`}
              aria-pressed={day === item.date}
              className={`state-${item.state} ${day === item.date ? "selected" : ""}`}
              onClick={() => setDay(item.date)}
            >
              {Number(item.date.slice(-2))}
              {item.state !== "future" && <i className="day-dot" />}
            </button>
          ))}
        </div>
        <div className="calendar-legend">
          <span>适用记录完成</span>
          <span>部分记录</span>
          <span>暂无记录</span>
        </div>
      </Card>
      <ErrorNotice
        error={calendar.error}
        retry={() => {
          void calendar.refresh();
        }}
      />
      <section className="section">
        <div className="section-title">
          <h2>{displayDay(day)}</h2>
          <span>当天小结</span>
        </div>
        <ErrorNotice
          error={report.error}
          retry={() => {
            void report.refresh();
          }}
        />
        {report.loading && !report.data ? (
          <Loading />
        ) : (
          report.data && (
            <>
              <ProgressTiles progress={report.data.completion.progress} />
              <p className="note-card">{report.data.summary_text}</p>
              <Card>
                {records.length ? (
                  records.map((record) => (
                    <RecordRow
                      key={record.checkin_id}
                      record={record}
                      edit={role === "elder"}
                    />
                  ))
                ) : (
                  <Empty
                    title="这一天还没有记录"
                    text="记录的是日常进度，不判断身体好坏。"
                  />
                )}
              </Card>
            </>
          )
        )}
      </section>
    </>
  );
  return embedded ? (
    <section aria-label="健康日报">{content}</section>
  ) : (
    <Page title="健康日报">{content}</Page>
  );
}
