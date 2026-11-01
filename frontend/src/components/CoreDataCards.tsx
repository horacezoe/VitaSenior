import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import type { Schemas } from "../api/client";
import { categoryIcons } from "./records";
import { dimensionNames,type Dimension } from "../state/report";
import { percentageHue } from "../state/core-visual";
export function visualStyle(percent:number|null):CSSProperties|undefined {
  return percent === null ? undefined : {"--core-accent":`hsl(${percentageHue(percent)} 70% 32%)`,"--core-tint":`hsl(${percentageHue(percent)} 75% 95%)`} as CSSProperties;
}
export function CoreMeter({percent,label}:{percent:number;label:string}) {
  return <div className="core-meter" style={visualStyle(percent)} role="progressbar" aria-label={label} aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}><span style={{width:`${percent}%`}} /></div>;
}
export function CoreDataCards({report,day}:{report:Schemas["DailyReport"];day:string}) {
  return <div className="report-dimensions">
    {(["diet","exercise","medication"] as Dimension[]).map(kind=>{
      const records=report.records[kind].filter(r=>!r.cancelled),Icon=categoryIcons[kind];
      return <Link key={kind} to={`/daily/${day}/${kind}`} className={`card report-dimension record-count-card record-count-${kind}`}
        aria-label={`${dimensionNames[kind]}：${records.length}条记录，查看详情`}>
        <Icon size={30} className="core-icon" aria-hidden="true" />
        <h3>{dimensionNames[kind]}</h3>
        <p className="record-count"><strong>{records.length}</strong><span>条记录</span></p>
        <span className="record-detail-arrow" aria-hidden="true"><ArrowRight size={22} /></span>
      </Link>;
    })}
  </div>;
}
