import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Check, ShieldCheck } from "lucide-react";
import {
  Button,
  Card,
  ErrorNotice,
  Field,
  Page,
  useAction,
  useResource,
} from "../components/ui";
import {
  ProfileFields,
  type ProfileInput,
  PlanFields,
  type PlanInput,
} from "../components/forms";
import { elderPath, type Schemas } from "../api/client";
import { useSession } from "../state/session";
import { useData } from "../state/data";

export default function Onboarding() {
  const { api, elderId } = useSession(),
    { refresh } = useData(),
    navigate = useNavigate(),
    action = useAction();
  const [identity, setIdentity] = useState("manual"),
    [face, setFace] = useState<File | null>(null);
  const [draft, setDraft] = useState<Schemas["MatchResult"] | null>(null);
  const [profile, setProfile] = useState<ProfileInput>({ display_name: "" }),
    [plans, setPlans] = useState<PlanInput[]>([]);
  const current = useResource(`onboarding-profile:${elderId}`, () =>
    api.get<Schemas["Profile"]>(elderPath(elderId!, "profile")),
  );
  const match = () =>
    action.run(async (keys) => {
      const media = face ? await api.upload(elderId!, face, "face") : null;
      const body = {
          sample_identity_key:
            identity === "sample"
              ? "community_sample_001"
              : "manual-" + elderId,
          ...(media ? { face_asset_id: media.asset_id } : {}),
        },
        path = elderPath(elderId!, "onboarding/match");
      const result = await api.post<Schemas["MatchResult"]>(
        path,
        body,
        keys.for(path, body),
      );
      setDraft(result);
      setProfile(result.profile_draft);
      setPlans(result.medication_plan_drafts);
    });
  const confirm = () =>
    action.run(async (keys) => {
      if (!draft || !current.data) return;
      const body = {
          draft_id: draft.draft_id,
          profile,
          medication_plans: plans,
          expected_version: current.data.version,
        },
        path = elderPath(elderId!, "onboarding/confirm");
      await api.post<Schemas["Profile"]>(path, body, keys.for(path, body));
      refresh();
      navigate("/elder", { replace: true });
    });
  return (
    <Page
      title={draft ? "一起核对您的信息" : "很高兴，认识您"}
      subtitle={draft ? "确认后才会保存为正式档案" : "花一点时间，让陪伴更贴心"}
      back="/settings"
    >
      {!draft ? (
        <>
          <Card>
            <span className="eyebrow">
              <ShieldCheck size={15} />
              由您核对，才安心保存
            </span>
            <p className="note-card">
              先填写基本信息，您也可以体验预置的社区档案。演示匹配不会判断真实身份。
            </p>
            <Field label="建档方式">
              <select
                value={identity}
                onChange={(e) => setIdentity(e.target.value)}
              >
                <option value="manual">由我填写信息</option>
                <option value="sample">带出社区演示档案</option>
              </select>
            </Field>
            <Field
              label="身份照片（可选）"
              hint="仅用于本轮演示匹配，可直接跳过。"
            >
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp"
                capture="user"
                onChange={(e) => setFace(e.target.files?.[0] || null)}
              />
            </Field>
            <Button
              icon={ArrowRight}
              loading={action.busy}
              className="full"
              onClick={() => {
                void match();
              }}
            >
              下一步，核对信息
            </Button>
          </Card>
        </>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void confirm();
          }}
        >
          <Card>
            <ProfileFields value={profile} onChange={setProfile} />
          </Card>
          {plans.length > 0 && (
            <section className="form-section">
              <h2>一并核对既有用药计划</h2>
              <p className="form-hint">
                来自演示档案，请逐项核对，尚未确认的计划可以移除。
              </p>
              {plans.map((plan, index) => (
                <Card key={index}>
                  <PlanFields
                    value={plan}
                    onChange={(value) =>
                      setPlans((old) =>
                        old.map((item, i) => (i === index ? value : item)),
                      )
                    }
                  />
                  <Button
                    type="button"
                    variant="text"
                    onClick={() =>
                      setPlans((old) => old.filter((_, i) => i !== index))
                    }
                  >
                    不保存这项计划
                  </Button>
                </Card>
              ))}
            </section>
          )}
          <Button
            type="submit"
            icon={Check}
            loading={action.busy || !current.data}
            className="full"
          >
            本人已核对，确认保存
          </Button>
        </form>
      )}
      <ErrorNotice error={action.error || current.error} />
    </Page>
  );
}
