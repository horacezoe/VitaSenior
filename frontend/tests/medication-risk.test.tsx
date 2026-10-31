import { describe,it,expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MedicationRiskNotice } from "../src/components/MedicationRiskNotice";
import type { Schemas } from "../src/api/client";
const base={checked_at:"2026-11-01T00:00:00Z",model:"test"};
describe("medication draft model review",()=>{
  it.each(["insufficient_data","unavailable","not_configured"] as const)("%s cannot be presented as no risk",status=>{
    const html=renderToStaticMarkup(<MedicationRiskNotice result={{...base,status,findings:[]}} />);
    expect(html).toContain("本次尚未得出检查结论");expect(html).not.toContain("本次初步核对未提示风险");
  });
  it("renders planned profile risks immediately",()=>{
    const finding:Schemas["SafetyFinding"]={kind:"drug_profile",title:"潜在档案风险",detail:"请药师核验",basis:"planned",evidence:[{type:"profile",id:"e",version:1},{type:"proposed_plan",id:"draft",version:1}]};
    const html=renderToStaticMarkup(<MedicationRiskNotice result={{...base,status:"reviewed",findings:[finding]}} />);
    expect(html).toContain('role="alert"');expect(html).toContain("潜在档案风险");expect(html).toContain("核对依据");
  });
});
