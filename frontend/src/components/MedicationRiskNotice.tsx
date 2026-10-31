import type { Schemas } from "../api/client";
export function MedicationRiskNotice({ result }: { result: Schemas["MedicationRiskCheckResult"] }) {
  const findings = result.findings || [];
  const warning = findings.length > 0;
  const title = warning ? "发现需要核对的潜在风险" : ({reviewed:"本次初步核对未提示风险",insufficient_data:"请补充用药信息后再检查",unavailable:"风险检查暂时失败",not_configured:"暂时无法进行风险检查"})[result.status];
  return <section className={warning ? "anomaly-banner" : "note-card"} role={warning ? "alert" : "status"} aria-label="添加用药风险核对结果">
    <h3>{title}</h3>
    {findings.map((finding,index)=><article key={index}><strong>{finding.title}</strong><p>{finding.detail}</p></article>)}
    <p>{result.status === "reviewed" ? "核对依据是您提供的用药计划与健康资料；有疑问可请医生或药师确认。" : "请核对完整药名和已有健康资料后重试；本次尚未得出检查结论。"}</p>
    <small>请按已有医嘱核对计划。</small>
  </section>;
}
