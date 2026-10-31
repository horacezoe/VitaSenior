import { it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import {
  AnomalyBanner,
  unseenAnomalies,
  alertKey,
} from "../src/components/Anomalies";
import type { Schemas } from "../src/api/client";
const alert = (
  id: string,
  revision = 1,
  status: "active" | "resolved" = "active",
) =>
  ({
    anomaly_id: id,
    date: "2026-11-01",
    kind: "food_drug",
    title: "潜在食药冲突",
    detail: "请家人协助联系药师核对",
    basis: "planned",
    assessment_model: "env-model",
    revision,
    status,
    evidence: [],
    detected_at: "2026-11-01T00:00:00Z",
  }) as Schemas["HealthAnomaly"];
it("renders nothing when there are no model findings", () =>
  expect(renderToStaticMarkup(<AnomalyBanner anomalies={[]} />)).toBe(""));
it("puts model provenance and potential/planned status on a real finding", () => {
  const text = renderToStaticMarkup(<AnomalyBanner anomalies={[alert("a")]} />);
  expect(text).toContain("潜在食药冲突");
  expect(text).toContain("AI核对");
  expect(text).toContain("基于既定计划");
});
it("deduplicates polls, retains newer resolutions and allows changed findings to notify again", () => {
  expect(unseenAnomalies([alert("a"), alert("a")], () => false)).toHaveLength(
    1,
  );
  expect(
    unseenAnomalies([alert("a"), alert("a", 2, "resolved")], () => false),
  ).toHaveLength(0);
  expect(
    unseenAnomalies([alert("a", 2)], (a) => a.revision === 1),
  ).toHaveLength(1);
  expect(unseenAnomalies([alert("a")], () => true)).toHaveLength(0);
  expect(alertKey("base", "child1", "elder", alert("a"))).not.toBe(
    alertKey("base", "child2", "elder", alert("a")),
  );
});

it("resolved findings stay auditable without a red active warning",()=>{
 const text=renderToStaticMarkup(<AnomalyBanner anomalies={[alert("a",2,"resolved")]} />);
 expect(text).toContain("已更新的核对记录");expect(text).toContain("<details");
 expect(text).not.toContain('class="anomaly-banner"');expect(text).not.toContain("异常核对提醒");
});
