import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import type { Schemas } from "../api/client";
import { categoryIcons } from "./records";
import { dimensionNames,reportMetrics,type Dimension } from "../state/report";
import { coreVisual,percentageHue } from "../state/core-visual";
export function visualStyle(percent:number|null):CSSProperties|undefined {
  return percent === null ? undefined : {"--core-accent":`hsl(${percentageHue(percent)} 70% 32%)`,"--core-tint":`hsl(${percentageHue(percent)} 75% 95%)`} as CSSProperties;
}
export function CoreMeter({percent,label}:{percent:number;label:string}) {
  return <div className="core-meter" style={visualStyle(percent)} role="progressbar" aria-label={label} aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}><span style={{width:`${percent}%`}} /></div>;
}
export function CoreDataCards({report,day}:{report:Schemas["DailyReport"];day:string}) {
  const metrics=reportMetrics(report);
  return <div className="report-dimensions">
    {(["diet","exercise","medication"] as Dimension[]).map(kind=>{
      const records=report.records[kind].filter(r=>!r.cancelled),visual=coreVisual(kind,report.completion.progress[kind],records.length),Icon=categoryIcons[kind];
      return <Link key={kind} to={`/daily/${day}/${kind}`} className={`card report-dimension core-card core-${visual.tone}`} style={visualStyle(visual.percent)}>
        <Icon size={30} className="core-icon" aria-hidden="true" />
        <h3>{dimensionNames[kind]}</h3>
        <strong className="core-state">{visual.label}</strong>
        <p>{kind === "exercise" && records.length ? `运动${metrics.minutes}分钟` : visual.detail}</p>
        {visual.percent !== null && <CoreMeter percent={visual.percent} label="服药记录率" />}
        <small>已记录{records.length}条 · 查看详情 →</small>
      </Link>;
    })}
  </div>;
}
