import type { Schemas } from "../api/client";
import type { Dimension } from "./report";
export function coreVisual(kind: Dimension, progress: Schemas["ProgressCount"], records = progress.completed) {
  const expected = progress.expected;
  const percent = expected > 0 ? Math.max(0, Math.min(100, Math.round(100 * progress.completed / expected))) : null;
  if (kind === "medication") {
    if (percent === null) return { tone:"neutral",label:"未设计划",detail:"暂无适用用药计划",percent:null } as const;
    return { tone:percent === 100 ? "good" : percent >= 50 ? "caution" : "low", label:percent === 100 ? "记录齐全" : "待核对",detail:`服药记录率 ${percent}%`,percent } as const;
  }
  if (kind === "exercise") {
    if (records > 0) return {tone:"good",label:"已记录运动",detail:"今日运动已打卡",percent:null} as const;
    return {tone:expected > 0 ? "caution" : "neutral",label:expected > 0 ? "待记录" : "暂无记录",detail:"尚无运动打卡，不代表没有运动",percent:null} as const;
  }
  if (expected > 0 && progress.completed >= expected) return {tone:"good",label:"记录齐全",detail:"餐次记录齐全",percent:null} as const;
  return {tone:expected > 0 || records > 0 ? "caution" : "neutral",label:records > 0 ? "待完善" : "暂无记录",detail:records > 0 ? "还有餐次待核对" : "尚无膳食记录",percent:null} as const;
}
export function percentageHue(percent:number) {
  const n=Math.max(0,Math.min(100,percent));
  return n <= 50 ? n * .85 : 42.5 + (n-50) * 1.65;
}
