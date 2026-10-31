import type { Schemas } from "../api/client";
export function MedicationRiskNotice({ result }: { result: Schemas["MedicationRiskCheckResult"] }) {
  const findings = result.findings || [];
  const warning = findings.length > 0;
  const title = warning ? "发现需要核对的潜在风险" : ({reviewed:"本次初步核对未提示风险",insufficient_data:"资料不足，尚不能判断风险",unavailable:"风险检查暂时失败",not_configured:"风险检查尚未配置"})[result.status];
  return <section className={warning ? "anomaly-banner" : "note-card"} role={warning ? "alert" : "status"} aria-label="添加用药风险核对结果">
    <h3>{title}</h3>
    {findings.map((finding,index)=><article key={index}><strong>{finding.title}</strong><p>{finding.detail}</p></article>)}
    <p>{result.status === "reviewed" ? "这是基于检查时的用药计划、健康档案和记录作出的模型初筛，不能保证没有风险，也不代表已经服药。" : "这次检查没有得出可用结论，不能当作没有冲突。请核对完整药名、疾病和过敏资料，或重试检查。"}</p>
    <small>检查不会新增、停用或更改药物。请核对已有医嘱；有疑问请医生或药师确认。</small>
  </section>;
}
