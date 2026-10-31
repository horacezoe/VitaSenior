import { coreVisual,percentageHue } from "../state/core-visual";
import type { CSSProperties } from "react";
import { Apple, Footprints, Pill, ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import type { Checkin, Schemas } from "../api/client";

export const categoryNames = {
  diet: "膳食",
  exercise: "运动",
  medication: "用药",
};
export const mealNames = { breakfast: "早餐", lunch: "午餐", dinner: "晚餐" };
export const categoryIcons = {
  diet: Apple,
  exercise: Footprints,
  medication: Pill,
};
export const reminderTitle = (title: string) =>
  title
    .replace(/记录breakfast/g, "早餐记录提醒")
    .replace(/记录lunch/g, "午餐记录提醒")
    .replace(/记录dinner/g, "晚餐记录提醒");
export function recordTitle(record: Checkin) {
  const p = record.payload;
  if ("foods" in p) return `${mealNames[p.meal_slot]} · ${p.foods.join("、")}`;
  if ("activity" in p) return `${p.activity} · ${p.duration_minutes} 分钟`;
  return p.intake_status === "taken" ? "按既定计划确认服药" : "明确记录未服用";
}
export function ProgressTiles({ progress }: { progress: Schemas["Progress"] }) {
  return (
    <div className="progress-tiles">
      {(["diet", "exercise", "medication"] as const).map((category) => {
        const item = progress[category],
          Icon = categoryIcons[category],
          visual = coreVisual(category,item);
        return (
          <div className={`progress-tile progress-${category} core-card core-${visual.tone}`} style={visual.percent === null ? undefined : {"--core-accent":`hsl(${percentageHue(visual.percent)} 70% 32%)`,"--core-tint":`hsl(${percentageHue(visual.percent)} 75% 95%)`} as CSSProperties} key={category}>
            <span className="progress-icon">
              <Icon size={23} strokeWidth={1.6} />
            </span>
            <strong>
              {item.applicable ? (
                <>
                  {item.completed}
                  <small> / {item.expected}</small>
                </>
              ) : (
                "—"
              )}
            </strong>
            <span>
              {categoryNames[category]}
              {item.applicable ? "记录" : "未设计划"}
            </span>
          </div>
        );
      })}
    </div>
  );
}
export function RecordRow({
  record,
  edit = false,
}: {
  record: Checkin;
  edit?: boolean;
}) {
  const Icon = categoryIcons[record.type];
  const content = (
    <>
      <span className={`record-icon record-${record.type}`}>
        <Icon size={21} strokeWidth={1.6} />
      </span>
      <span className="record-copy">
        <strong>{recordTitle(record)}</strong>
        <small>
          {new Intl.DateTimeFormat("zh-CN", {
            hour: "2-digit",
            minute: "2-digit",
            timeZone: "Asia/Hong_Kong",
          }).format(new Date(record.occurred_at))}{" "}
          ·{" "}
          {record.source === "demo_seed"
            ? "历史演示"
            : record.source === "agent_confirmed"
              ? "本人确认"
              : "本人记录"}
          {record.version > 1 ? " · 已纠正" : ""}
        </small>
      </span>
      {edit && <ChevronRight size={18} className="muted" />}
    </>
  );
  return edit ? (
    <Link
      className="record-row"
      to={`/records/${record.checkin_id}?date=${record.local_date}`}
    >
      {content}
    </Link>
  ) : (
    <div className="record-row">{content}</div>
  );
}
