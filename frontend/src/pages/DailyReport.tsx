import { AnomalyBanner } from "../components/Anomalies";
import { familyReportTip } from "../state/report";
import { useEffect, useState } from "react";
import ReportSpeech from "../components/ReportSpeech";
import { Link, useParams } from "react-router-dom";
import {
  Avatar,
  Card,
  Page,
  Loading,
  ErrorNotice,
  Empty,
  useResource,
} from "../components/ui";
import { RecordRow, categoryIcons } from "../components/records";
import { useSession } from "../state/session";
import { useData } from "../state/data";
import {
  elderPath,
  localDay,
  displayDay,
  query,
  type Schemas,
} from "../api/client";
import { reportMetrics, dimensionNames, type Dimension } from "../state/report";

export default function DailyReport({
  embedded = false,
  view = "date",
}: {
  embedded?: boolean;
  view?: "date" | "health";
}) {
  const { date, dimension } = useParams(),
    { api, elderId, role } = useSession(),
    { revision } = useData();
  const day = date || localDay(api.now());
  const basic = useResource(
    `daily-facts:${api.base}:${role}:${elderId}:${day}`,
    () =>
      api.get<Schemas["DailyReport"]>(
        elderPath(elderId!, "reports/daily") + query({ date: day }),
      ),
    revision,
  );
  const report = useResource(
    `ai-report:${api.base}:${role}:${elderId}:${day}`,
    () =>
      api.get<Schemas["DailyReport"]>(
        elderPath(elderId!, "reports/daily") +
          query({ date: day, include_ai: true }),
      ),
    revision,
  );
  const snapshot = report.data || basic.data;
  const r = snapshot
      ? {
          ...snapshot,
          anomalies: basic.data?.anomalies ?? snapshot.anomalies,
          reward_summary: basic.data?.reward_summary ?? snapshot.reward_summary,
        }
      : undefined,
    kind =
      dimension && ["diet", "exercise", "medication"].includes(dimension)
        ? (dimension as Dimension)
        : null;
  const m = r ? reportMetrics(r) : null;
  const advice =
    r?.insights &&
    (kind === "diet"
      ? r.insights.diet_advice
      : kind === "exercise"
        ? r.insights.exercise_advice
        : r.insights.medication_advice);
  const content = (
    <>
      <AnomalyBanner anomalies={r?.anomalies || []} />
      <ErrorNotice
        error={report.error}
        retry={() => {
          void report.refresh();
        }}
      />
      {report.loading && !r && <Loading />}
      {r && m && (
        <>
          {r.ai_status !== "ready" && (
            <p className="note-card">
              {report.loading
                ? "正在综合档案、记忆和当日打卡记录生成建议…"
                : r.ai_status === "unavailable"
                  ? "AI日报暂时未能生成，可稍后重试；下方真实记录仍可查看。"
                  : "AI日报尚未配置，下方为实际打卡数据。"}{" "}
              <button
                type="button"
                className="button button-text"
                disabled={report.loading}
                onClick={() => {
                  void report.refresh();
                }}
              >
                重新生成
              </button>
            </p>
          )}
          {r.safety_review_status === "insufficient_data" && (
            <p className="form-hint">
              相互作用核对资料不足，请先核对药品名称或饮食记录；这不代表已确认没有相互作用。
            </p>
          )}
          {r.safety_review_status === "unavailable" && (
            <p className="form-hint">
              本次相互作用核对暂未完成，稍后可重试；已有核对记录仍保留。
            </p>
          )}
          {kind ? (
            <>
              <p className="note-card">
                {advice || "暂未生成本项AI建议，请先核对下方的真实记录。"}
              </p>
              <Card>
                <h2>{dimensionNames[kind]}指标与进度</h2>
                {kind === "diet" ? (
                  Object.entries(m.groups).map(([g, n]) => (
                    <div className="report-meter" key={g}>
                      <label>
                        {
                          (
                            {
                              vegetable: "蔬菜",
                              protein: "蛋白类",
                              staple: "主食",
                              fruit: "水果",
                              dairy: "奶类",
                              fat: "油脂类",
                              other: "其他",
                            } as Record<string, string>
                          )[g]
                        }{" "}
                        · {n}次
                      </label>
                      <progress value={n} max={Math.max(3, n)} />
                    </div>
                  ))
                ) : (
                  <div className="report-meter">
                    <label>
                      {kind === "exercise"
                        ? `已记录${m.minutes}分钟运动`
                        : `明确服用记录率：${m.adherence === null ? "未设计划" : m.adherence + "%"}`}
                    </label>
                    <progress
                      value={
                        kind === "exercise"
                          ? r.completion.progress.exercise.completed
                          : r.completion.progress.medication.completed
                      }
                      max={Math.max(1, r.completion.progress[kind].expected)}
                    />
                  </div>
                )}
                <p className="form-hint">
                  {kind === "diet"
                    ? "食物类别按餐去重计次；进度条展示记录次数，不代表营养达标。"
                    : "进度依据既定任务与本人确认记录；未记录不等于实际未完成。"}
                </p>
              </Card>
              {kind === "medication" && (
                <>
                  {r.records.medication.some(
                    (x) =>
                      "intake_status" in x.payload &&
                      x.payload.intake_status === "not_taken",
                  ) && (
                    <div className="notice notice-error" role="alert">
                      有明确未服用记录，请核对原因；不要自行补服、加量或更改处方。
                    </div>
                  )}
                </>
              )}
              <Card className="section">
                <h2>当日{dimensionNames[kind]}打卡记录</h2>
                {r.records[kind].length ? (
                  r.records[kind].map((x) => (
                    <div key={x.checkin_id}>
                      {kind === "medication" && "plan_id" in x.payload && (
                        <strong>
                          {r.medication_plans?.find(
                            (p) =>
                              "plan_id" in x.payload &&
                              p.plan_id === x.payload.plan_id,
                          )?.name || "既定用药计划"}
                        </strong>
                      )}
                      <RecordRow record={x} edit={role === "elder"} />
                    </div>
                  ))
                ) : (
                  <Empty
                    title="这一天尚无记录"
                    text="暂无记录不代表实际未完成。"
                  />
                )}
              </Card>
              {role === "elder" && (
                <Link
                  className="button button-primary"
                  to={`/records/new?type=${kind}&date=${day}`}
                >
                  补充{dimensionNames[kind]}记录
                </Link>
              )}
            </>
          ) : (
            <>
              {view === "health" ? (
                <Card className="section">
                  <h2>AI管家温情播报</h2>
                  <p>
                    {r.insights?.warm_message ||
                      (report.loading
                        ? "正在整理今天的日常，先看看下方真实打卡记录吧。"
                        : "AI播报暂不可用，请查看下方真实记录。")}
                  </p>
                  {r.insights && (
                    <ReportSpeech text={r.insights.warm_message} />
                  )}
                </Card>
              ) : role === "child" ? (
                <Card>
                  <span className="eyebrow">长辈基础信息</span>
                  <h2>{r.person?.display_name || "家人"}</h2>
                  <p>
                    {r.person?.birth_date
                      ? `出生日期 ${r.person.birth_date} · `
                      : ""}
                    {r.person?.conditions?.length
                      ? r.person.conditions.join("、")
                      : r.person
                        ? "未记录慢病信息"
                        : "档案信息加载中…"}
                  </p>
                  <p className="form-hint">健康风险评级：尚未进行专业评估</p>
                </Card>
              ) : (
                <section className="report-greeting">
                  <Avatar state="idle" />
                  <span className="eyebrow">小银龄陪您看今天</span>
                  <h2>
                    {r.insights?.elder_praise ||
                      (Object.values(r.records).some((xs) => xs.length)
                        ? "谢谢您认真记下今天的生活！"
                        : "今天也陪您慢慢来，每一份记录都值得鼓励。")}
                  </h2>
                </section>
              )}
              {(view === "health" || role === "child") && (
                <CumulativeEggs
                  today={m.eggs}
                  day={day}
                  summary={r.reward_summary}
                />
              )}
              <h2 className="section">三大打卡记录</h2>
              <div className="report-dimensions">
                {(["diet", "exercise", "medication"] as const).map((k) => {
                  const Icon = categoryIcons[k],
                    p = r.completion.progress[k];
                  return (
                    <Link
                      className="card report-dimension"
                      key={k}
                      to={`/daily/${day}/${k}`}
                    >
                      <Icon size={30} />
                      <h3>{dimensionNames[k]}</h3>
                      <strong>
                        {r.records[k].length ? "已打卡" : "未打卡"}
                      </strong>
                      <p>
                        {k === "diet"
                          ? `膳食信号：${p.completed >= p.expected && p.expected > 0 ? "绿灯 · 餐次记录齐全" : r.records.diet.length ? "黄灯 · 仍有待核对餐次" : "灰色 · 尚无记录"}`
                          : k === "exercise"
                            ? `运动${m.minutes}分钟`
                            : `明确服用记录率 ${m.adherence === null ? "未设计划" : m.adherence + "%"}`}
                      </p>
                      <small>已记录{r.records[k].length}条 · 查看详情 →</small>
                    </Link>
                  );
                })}
              </div>
              {role === "child" && (
                <p className="note-card">{familyReportTip(r)}</p>
              )}
            </>
          )}
        </>
      )}
    </>
  );
  return embedded ? (
    <section aria-label={view === "health" ? "我的健康概览" : "当日健康日报"}>
      {content}
    </section>
  ) : (
    <Page
      title={kind ? `${dimensionNames[kind]}打卡记录` : "健康日报"}
      subtitle={displayDay(day)}
    >
      {content}
    </Page>
  );
}

function CumulativeEggs({
  today,
  day,
  summary,
}: {
  today: number;
  day: string;
  summary?: Schemas["RewardSummary"] | null;
}) {
  const { ledger } = useData();
  const { api } = useSession();
  const [total, setTotal] = useState(0);
  useEffect(() => {
    const update = () =>
      setTotal(ledger?.read().filter((p) => p.played || !p.queued).length || 0);
    update();
    window.addEventListener("vitasenior:rewards", update);
    window.addEventListener("storage", update);
    return () => {
      window.removeEventListener("vitasenior:rewards", update);
      window.removeEventListener("storage", update);
    };
  }, [ledger]);
  return (
    <Card className="section">
      <h2>🥚 累计鸡蛋积分</h2>
      <strong className="report-eggs">{summary?.cumulative ?? total} 枚</strong>
      <p>
        {day === localDay(api.now()) ? "今日积累" : "当日积累"}：
        {summary?.on_date ?? today} 枚
      </p>
      <small>
        累计按服务端已确认的日常打卡核对；重复提交与更正不重复计分，取消暂不扣回。
      </small>
    </Card>
  );
}
