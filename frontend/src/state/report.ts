import type { Schemas } from "../api/client";
export type Dimension = "diet" | "exercise" | "medication";
export const dimensionNames = {
  diet: "膳食",
  exercise: "运动",
  medication: "用药",
};
export function reportMetrics(report: Schemas["DailyReport"]) {
  const records = Object.values(report.records)
    .flat()
    .filter((r) => !r.cancelled);
  const eggs = new Set(
    records.filter((r) => r.source !== "demo_seed").map((r) => r.checkin_id),
  ).size;
  const progress = report.completion.progress;
  const expected = Object.values(progress).reduce(
    (sum, p) => sum + p.expected,
    0,
  );
  const groups: Record<string, number> = {
    vegetable: 0,
    protein: 0,
    staple: 0,
    fruit: 0,
    dairy: 0,
    fat: 0,
    other: 0,
  };
  for (const r of report.records.diet)
    if ("food_groups" in r.payload)
      for (const g of new Set(r.payload.food_groups))
        groups[g] = (groups[g] || 0) + 1;
  const minutes = report.records.exercise.reduce(
    (sum, r) =>
      sum + ("duration_minutes" in r.payload ? r.payload.duration_minutes : 0),
    0,
  );
  return {
    eggs,
    expected,
    groups,
    minutes,
    adherence: progress.medication.expected
      ? Math.round(
          (progress.medication.completed / progress.medication.expected) * 100,
        )
      : null,
  };
}

export function familyReportTip(report: Schemas["DailyReport"]) {
  if(Object.values(report.completion.progress).every(p=>p.expected===0))return "这一天没有设定适用打卡目标，您可以与长辈了解当天情况，查看已记录的日常。";
  const missing = (Object.keys(dimensionNames) as Dimension[])
    .filter(
      (k) =>
        report.completion.progress[k].expected > 0 &&
        report.completion.progress[k].completed <
          report.completion.progress[k].expected,
    )
    .map((k) => dimensionNames[k]);
  return missing.length
    ? `建议您与长辈核对${missing.join("、")}记录，了解是否需要协助。暂无记录不等于实际未完成，请以长辈本人确认和既定用药计划为准。`
    : "长辈当日的适用打卡已记录齐全，您可以送上一句问候，了解今天的感受。";
}

export function factualAdvice(report:Schemas["DailyReport"],kind:Dimension) {
  const active=report.records[kind].filter(r=>!r.cancelled);
  if(kind==="diet") return active.length ? `这一天已记录${active.length}餐，可以回看餐食内容；如还有实际吃过的餐次，也可以补记。` : "这一天暂无餐食记录，可以按实际情况补记。";
  if(kind==="exercise") return active.length ? `这一天记录了${reportMetrics(report).minutes}分钟运动，可以回顾活动情况和身体感受。` : "这一天暂无运动记录，可以按实际情况补记。";
  const p=report.completion.progress.medication;
  return p.expected>0 ? `这一天的${p.expected}次既定用药中，${p.completed}次已有明确服用记录。请按实际情况核对其他记录，不要重复服用。` : "这一天没有适用的用药计划；如有实际用药，可以先核对计划与记录。";
}
