import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check, ShieldCheck } from "lucide-react";
import { Button, Card, ErrorNotice, Loading, Page, useAction, useResource } from "../components/ui";
import { ProfileFields, type ProfileInput, PlanFields, type PlanInput } from "../components/forms";
import { elderPath, WriteKey, type Schemas } from "../api/client";
import { useSession } from "../state/session";
import { useData } from "../state/data";

type Editor = {
  scope: string;
  current: Schemas["Profile"];
  draft: Schemas["MatchResult"];
  profile: ProfileInput;
  plans: PlanInput[];
};

export default function Onboarding() {
  const { api, elderId } = useSession();
  const { refresh } = useData();
  const navigate = useNavigate();
  const action = useAction();
  const keys = useRef(new WriteKey());
  const scope = `${api.base}:${api.token}:${elderId}`;
  const [editor, setEditor] = useState<Editor | null>(null);
  const active = editor?.scope === scope ? editor : null;
  const initial = useResource(`onboarding:${scope}`, async () => {
    const current = await api.get<Schemas["Profile"]>(elderPath(elderId!, "profile"));
    if (current.onboarding_status === "confirmed") return { current, draft: null };
    const path = elderPath(elderId!, "onboarding/match");
    const body = { mode: "auto" };
    const draft = await api.post<Schemas["MatchResult"]>(path, body, keys.current.for(path, body));
    return { current, draft };
  });
  useEffect(() => {
    if (!initial.data) return;
    const { current, draft } = initial.data;
    if (!draft) {
      navigate("/elder", { replace: true });
      return;
    }
    setEditor({ scope, current, draft, profile: draft.match_status === "not_found"
      ? { ...draft.profile_draft, display_name: "" } : draft.profile_draft,
      plans: draft.medication_plan_drafts });
  }, [initial.data, scope, navigate]);

  const manual = () => action.run(async (writeKeys) => {
    const current = active?.current || await api.get<Schemas["Profile"]>(elderPath(elderId!, "profile"));
    const path = elderPath(elderId!, "onboarding/match"), body = { mode: "manual" };
    const draft = await api.post<Schemas["MatchResult"]>(path, body, writeKeys.for(path, body));
    setEditor({ scope, current, draft, profile: { ...draft.profile_draft, display_name: "" }, plans: [] });
  });
  const confirm = () => action.run(async (writeKeys) => {
    if (!active) return;
    const body = {
      draft_id: active.draft.draft_id,
      profile: active.profile,
      medication_plans: active.plans,
      expected_version: active.current.version,
    };
    const path = elderPath(elderId!, "onboarding/confirm");
    await api.post<Schemas["Profile"]>(path, body, writeKeys.for(path, body));
    refresh();
    navigate("/elder", { replace: true });
  });
  const update = (change: Partial<Editor>) =>
    setEditor((value) => value?.scope === scope ? { ...value, ...change } : value);

  return (
    <Page title={active ? (active.draft.match_status === "not_found" ? "请填写您的档案" : "一起核对您的信息") : "正在查询社区档案"}
      subtitle="确认后才会保存为正式档案" backTo="/login" backLabel="返回登录">
      {!active ? (
        <Card>
          {initial.loading && <Loading />}
          <p className="note-card">正在查询与您关联的社区资料，请稍候。</p>
          <ErrorNotice error={initial.error} retry={() => void initial.refresh()} />
          {!initial.loading && initial.error != null && (
            <Button variant="secondary" loading={action.busy} onClick={() => void manual()}>改为手工填写</Button>
          )}
        </Card>
      ) : (
        <form onSubmit={(event) => { event.preventDefault(); void confirm(); }}>
          <Card>
            <span className="eyebrow"><ShieldCheck size={15} />由您核对，才安心保存</span>
            {active.draft.match_status === "matched" ? (
              <>
                <p className="note-card">
                  已匹配到{active.draft.community_name || "社区档案"}中的{active.draft.profile_draft.display_name}。
                  {active.draft.record_number && `档案编号：${active.draft.record_number}。`}
                  请核对基本信息、慢病史和既有用药计划。
                </p>
                <Button type="button" variant="text" loading={action.busy}
                  onClick={() => void manual()}>这不是我的信息，改为手工填写</Button>
              </>
            ) : (
              <p className="note-card">
                {active.draft.match_basis === "manual"
                  ? "由您填写并核对个人信息，确认后保存。"
                  : "没有找到对应的社区档案，请填写基本信息后确认保存。"}
              </p>
            )}
            <ProfileFields value={active.profile} onChange={(profile) => update({ profile })} />
          </Card>
          {active.plans.length > 0 && (
            <section className="form-section">
              <h2>一并核对既有用药计划</h2>
              <p className="form-hint">请逐项核对既有用药计划；不符合当前情况的项目可以移除。</p>
              {active.plans.map((plan, index) => (
                <Card key={index}>
                  <PlanFields value={plan} onChange={(value) =>
                    update({ plans: active.plans.map((item, i) => i === index ? value : item) })} />
                  <Button type="button" variant="text" onClick={() =>
                    update({ plans: active.plans.filter((_, i) => i !== index) })}>不保存这项计划</Button>
                </Card>
              ))}
            </section>
          )}
          <Button type="submit" icon={Check} loading={action.busy} className="full">本人已核对，确认保存</Button>
        </form>
      )}
      <ErrorNotice error={action.error} />
    </Page>
  );
}
