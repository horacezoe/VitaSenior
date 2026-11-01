import {it,expect} from "vitest";
import {renderToStaticMarkup} from "react-dom/server";
import {MemoryRouter} from "react-router-dom";
import {CoreDataCards} from "../src/components/CoreDataCards";
import {coreVisual,percentageHue} from "../src/state/core-visual";
import type {Schemas} from "../src/api/client";
const p=(expected:number,completed:number)=>({expected,completed,applicable:expected>0});
it("uses amber for incomplete meals without diagnosing poor nutrition",()=>{
 const value=coreVisual("diet",p(3,1),1);expect(value.tone).toBe("caution");expect(value.label).toBe("待完善");
 expect(coreVisual("diet",p(3,3),3).tone).toBe("good");
});
it("exercise is green with any recorded activity, amber while awaiting a record",()=>{
 expect(coreVisual("exercise",p(1,1),1).tone).toBe("good");
 expect(coreVisual("exercise",p(1,0),0).tone).toBe("caution");
 expect(coreVisual("exercise",p(0,0),1).tone).toBe("good");
});
it.each([[0,"low"],[50,"caution"],[100,"good"]] as const)("medicine %i percent has corresponding tone",(percent,tone)=>{
 const value=coreVisual("medication",p(100,percent));expect(value.percent).toBe(percent);expect(value.tone).toBe(tone);
});
it("no medication plan stays neutral rather than zero adherence",()=>{
 expect(coreVisual("medication",p(0,0))).toMatchObject({tone:"neutral",percent:null,label:"未设计划"});
 expect(coreVisual("medication",p(2,3)).percent).toBe(100);
 expect(percentageHue(0)).toBeLessThan(percentageHue(50));expect(percentageHue(50)).toBeLessThan(percentageHue(100));
});
it("shared cards show only active record counts and clear detail links",()=>{
 const report={records:{diet:[{payload:{food_groups:[]}},{cancelled:true}],exercise:[],medication:[]},completion:{progress:{diet:p(3,1),exercise:p(1,0),medication:p(2,1)}}} as unknown as Schemas["DailyReport"];
 const html=renderToStaticMarkup(<MemoryRouter><CoreDataCards report={report} day="2026-11-01" /></MemoryRouter>);
 expect(html).toContain('aria-label="膳食：1条记录，查看详情"');
 expect(html).toContain('aria-label="运动：0条记录，查看详情"');
 expect(html).toContain('aria-label="用药：0条记录，查看详情"');
 expect(html.match(/record-detail-arrow/g)).toHaveLength(3);
 for(const kind of ["diet","exercise","medication"]) expect(html).toContain(`/daily/2026-11-01/${kind}`);
 expect(html).not.toMatch(/暂无记录|尚无膳食记录|待完善|progressbar|已记录/);
});
