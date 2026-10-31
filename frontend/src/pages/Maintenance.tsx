import { MedicationRiskNotice } from "../components/MedicationRiskNotice";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Bell, Check, Plus, Pill, ShieldCheck } from "lucide-react";
import {
  Button,
  Card,
  Empty,
  ErrorNotice,
  Field,
  Loading,
  MenuLink,
  Page,
  Success,
  useAction,
  useResource,
} from "../components/ui";
import {
  ProfileFields,
  PlanFields,
  ReminderFields,
  type ProfileInput,
  type PlanInput,
  ConfirmDialog,
} from "../components/forms";
import { elderPath, localDay, query, uid, type Schemas } from "../api/client";
import { useSession } from "../state/session";
import { useData } from "../state/data";

export function Profile() {
  const { api, elderId, role } = useSession(),
    { revision, refresh } = useData(),
    action = useAction();
  const resource = useResource(
    `profile:${api.base}:${role}:${elderId}`,
    () => api.get<Schemas["Profile"]>(elderPath(elderId!, "profile")),
    revision,
  );
  const [editing, setEditing] = useState(false),
    [value, setValue] = useState<ProfileInput | null>(null),
    [saved, setSaved] = useState(false);
  const [editVersion, setEditVersion] = useState(0);
  const [beforeEdit, setBeforeEdit] = useState<ProfileInput | null>(null);
  const save = () =>
    action.run(async (keys) => {
      if (!resource.data || !value || !beforeEdit) return;
      const patch = Object.fromEntries(
        Object.entries(value).filter(
          ([field, next]) =>
            JSON.stringify(next) !==
            JSON.stringify(beforeEdit[field as keyof ProfileInput]),
        ),
      );
      if (!Object.keys(patch).length)
        throw new Error("还没有修改内容，可以选择暂不修改。");
      const body =
        role === "elder"
          ? { expected_version: editVersion, patch }
          : {
              target_type: "profile",
              target_id: elderId,
              operation: "update",
              base_version: editVersion,
              patch,
            };
      const path = elderPath(
        elderId!,
        role === "elder" ? "profile" : "change-proposals",
      );
      if (role === "elder") await api.put(path, body, keys.for(path, body));
      else await api.post(path, body, keys.for(path, body));
      setEditing(false);
      setSaved(true);
      refresh();
    });
  const data = resource.data;
  return (
    <Page
      title={role === "elder" ? "我的个人档案" : "家人的个人档案"}
      subtitle={
        role === "elder" ? "只保存已经核对的信息" : "协助修改将先交由家人核对"
      }
    >
      <ErrorNotice
        error={resource.error || action.error}
        retry={() => {
          setEditing(false);
          setValue(null);
          action.clearError();
          void resource.refresh();
        }}
      />
      {saved && (
        <Success>
          {role === "elder"
            ? "档案已保存"
            : "修改申请已送出，原档案暂时保持原值"}
        </Success>
      )}
      {!data ? (
        <Loading />
      ) : editing && value ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <Card>
            <ProfileFields value={value} onChange={setValue} />
            <div className="form-actions">
              <Button
                variant="secondary"
                onClick={() => setEditing(false)}
                type="button"
              >
                暂不修改
              </Button>
              <Button type="submit" loading={action.busy} icon={Check}>
                {role === "elder" ? "核对并保存" : "提交修改申请"}
              </Button>
            </div>
          </Card>
        </form>
      ) : (
        <>
          <Card>
            <dl className="details-list">
              <div>
                <dt>称呼</dt>
                <dd>{data.display_name}</dd>
              </div>
              <div>
                <dt>出生日期</dt>
                <dd>{data.birth_date || "暂未填写"}</dd>
              </div>
              <div>
                <dt>性别</dt>
                <dd>
                  {
                    {
                      male: "男",
                      female: "女",
                      other: "其他",
                      unknown: "暂未填写",
                    }[data.sex || "unknown"]
                  }
                </dd>
              </div>
              <div>
                <dt>已确认疾病</dt>
                <dd>{data.conditions?.join("、") || "暂未填写"}</dd>
              </div>
              <div>
                <dt>过敏信息</dt>
                <dd>{data.allergies?.join("、") || "暂未填写"}</dd>
              </div>
              <div>
                <dt>健康备注</dt>
                <dd>{data.medical_notes || "暂无备注"}</dd>
              </div>
            </dl>
            <p className="source-tag">
              {data.source === "community_mock" || data.source === "demo_seed"
                ? "社区资料"
                : "已核对档案"}{" "}
              · 最近核对{" "}
              {new Date(data.updated_at).toLocaleDateString("zh-CN", {
                timeZone: "Asia/Hong_Kong",
              })}
            </p>
          </Card>
          <Button
            className="full section"
            variant="secondary"
            onClick={() => {
              setValue({
                display_name: data.display_name,
                birth_date: data.birth_date,
                sex: data.sex,
                conditions: data.conditions,
                allergies: data.allergies,
                medical_notes: data.medical_notes,
              });
              setBeforeEdit({
                display_name: data.display_name,
                birth_date: data.birth_date,
                sex: data.sex,
                conditions: data.conditions,
                allergies: data.allergies,
                medical_notes: data.medical_notes,
              });
              setEditVersion(data.version);
              setEditing(true);
              setSaved(false);
            }}
          >
            {role === "elder" ? "核对或修改档案" : "协助家人修改"}
          </Button>
          <div className="menu-card">
            <MenuLink
              to="/plans"
              icon={Pill}
              title="用药计划"
              text="核对既定的药品和时段"
            />
            <MenuLink
              to="/reminders"
              icon={Bell}
              title="提醒设置"
              text="设置日常提醒"
            />
            {
              <MenuLink
                to="/proposals"
                icon={ShieldCheck}
                title="修改申请进展"
                text="送达、决定与生效状态"
              />
            }
          </div>
        </>
      )}
    </Page>
  );
}

export function Plans() {
  const { api, elderId, role } = useSession(),
    { revision } = useData(),
    [inactive, setInactive] = useState(false);
  const resource = useResource(
    `plans:${api.base}:${role}:${elderId}:${inactive}`,
    () =>
      api.get<Schemas["PlanList"]>(
        elderPath(elderId!, "medication-plans") +
          query({ active: inactive ? undefined : true }),
      ),
    revision,
  );
  return (
    <Page
      title="既定用药计划"
      subtitle="不改变药物建议，只核对已确认的安排"
      action={
        <Link className="icon-button" to="/plans/new" aria-label="添加用药计划">
          <Plus size={20} />
        </Link>
      }
    >
      <label className="toggle-row">
        <span>同时查看已停用计划</span>
        <input
          type="checkbox"
          checked={inactive}
          onChange={(e) => setInactive(e.target.checked)}
        />
      </label>
      <ErrorNotice
        error={resource.error}
        retry={() => {
          void resource.refresh();
        }}
      />
      {resource.loading && !resource.data ? (
        <Loading />
      ) : resource.data?.items.length ? (
        resource.data.items.map((plan) => (
          <Link
            to={`/plans/${plan.plan_id}`}
            className="notification-card"
            style={{ display: "block" }}
            key={plan.plan_id}
          >
            <span className="tag">{plan.active ? "当前计划" : "已停用"}</span>
            <h3>{plan.name}</h3>
            <p>{plan.dose_display}</p>
            <p>
              {plan.schedule.mode === "fixed"
                ? plan.schedule.slots.map((slot) => slot.local_time).join("、")
                : plan.schedule.slots
                    .map(
                      (slot) =>
                        `${{ breakfast: "早餐", lunch: "午餐", dinner: "晚餐" }[slot.meal_slot]}后 ${slot.delay_minutes} 分钟`,
                    )
                    .join("、")}
            </p>
            <small className="muted">
              {plan.start_date} 起{plan.end_date ? `，至 ${plan.end_date}` : ""}
            </small>
          </Link>
        ))
      ) : (
        <Empty
          title="暂未设置用药计划"
          text="没有计划时，不会把用药计为缺少记录。"
        >
          <Link className="button button-secondary" to="/plans/new">
            核对并添加计划
          </Link>
        </Empty>
      )}
      {role === "child" && (
        <p className="note-card">
          新增、修改或停用均先提交申请，家人核对后再按服务端状态生效。
        </p>
      )}
    </Page>
  );
}

export function PlanEditorPage() {
  const { id } = useParams(),
    { api, elderId, role } = useSession();
  const resource = useResource(
    `plan-edit:${api.base}:${role}:${elderId}:${id}`,
    async () => {
      if (id === "new") return null;
      const plans = await api.get<Schemas["PlanList"]>(
        elderPath(elderId!, "medication-plans"),
      );
      const plan = plans.items.find((item) => item.plan_id === id);
      if (!plan) throw new Error("该计划已不可用，请返回重新选择。");
      return plan;
    },
  );
  return (
    <Page
      title={id === "new" ? "核对新的用药计划" : "核对用药计划"}
      subtitle={
        role === "child" ? "提交申请后，由家人核对决定" : "按照已确认的计划填写"
      }
      back="/plans"
    >
      <ErrorNotice error={resource.error} />
      {resource.loading ? (
        <Loading />
      ) : (
        !resource.error && (
          <PlanEditor key={id} original={resource.data || undefined} />
        )
      )}
    </Page>
  );
}
function PlanEditor({ original }: { original?: Schemas["MedicationPlan"] }) {
  const { api, elderId, role } = useSession(),
    { refresh } = useData(),
    navigate = useNavigate(),
    action = useAction();
  const [value, setValue] = useState<PlanInput>(
    original
      ? {
          name: original.name,
          dose_display: original.dose_display,
          schedule: original.schedule,
          start_date: original.start_date,
          end_date: original.end_date,
          medicine_asset_id: original.medicine_asset_id,
          notes: original.notes,
        }
      : {
          name: "",
          dose_display: "",
          schedule: {
            mode: "fixed",
            slots: [{ slot_id: uid("slot"), local_time: "08:00" }],
          },
          start_date: localDay(api.now()),
          notes: "",
        },
  );
  const [file, setFile] = useState<File | null>(null),
    [uploaded, setUploaded] = useState<string | null>(null),
    [deactivating, setDeactivating] = useState(false);
  const [risk, setRisk] = useState<{key:string; result:Schemas["MedicationRiskCheckResult"]} | null>(null);
  const riskKey = JSON.stringify({base:api.base,elderId,value,id:original?.plan_id,version:original?.version});
  const checkedRisk = risk?.key === riskKey ? risk.result : null;
  const checkRisk = async () => {
    const result = await api.post<Schemas["MedicationRiskCheckResult"]>(elderPath(elderId!, "medication-plan-risk"), {
      plan:value, ...(original ? {replace_plan_id:original.plan_id,expected_version:original.version} : {}),
    });
    setRisk({key:riskKey,result});
  };

  const save = () =>
    action.run(async (keys) => {
      if (!checkedRisk) { await checkRisk(); return; }
      const bodyValue = { ...value };
      if (file) {
        const media =
          uploaded || (await api.upload(elderId!, file, "medicine")).asset_id;
        setUploaded(media);
        bodyValue.medicine_asset_id = media;
      }
      const path =
        role === "child"
          ? elderPath(elderId!, "change-proposals")
          : original
            ? `/api/v1/medication-plans/${original.plan_id}`
            : elderPath(elderId!, "medication-plans");
      const body =
        role === "child"
          ? {
              target_type: "medication_plan",
              target_id: original?.plan_id || null,
              operation: original ? "update" : "create",
              base_version: original?.version || null,
              patch: bodyValue,
            }
          : original
            ? { expected_version: original.version, patch: bodyValue }
            : bodyValue;
      if (role === "elder" && original)
        await api.put(path, body, keys.for(path, body));
      else await api.post(path, body, keys.for(path, body));
      refresh();
      navigate(role === "child" ? "/proposals" : "/plans", { replace: true });
    });
  const deactivate = () =>
    action.run(async (keys) => {
      if (!original || role !== "child") return;
      const path = elderPath(elderId!, "change-proposals"),
        body = {
          target_type: "medication_plan",
          target_id: original.plan_id,
          operation: "deactivate",
          base_version: original.version,
          patch: {},
        };
      await api.post(path, body, keys.for(path, body));
      refresh();
      navigate("/proposals", { replace: true });
    });
  return (
    <>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <Card>
          <PlanFields value={value} onChange={setValue} />
          <Field label="药品照片（可选）">
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              capture="environment"
              onChange={(e) => {
                setFile(e.target.files?.[0] || null);
                setUploaded(null);
              }}
            />
          </Field>
          {checkedRisk && <MedicationRiskNotice result={checkedRisk} />}
          {!checkedRisk && <p className="muted">提交前先用大模型核对新药与现有用药、已确认疾病和过敏资料。检查完成后再由您决定保存。</p>}
          <Button type="submit" className="full" loading={action.busy}>
            {!checkedRisk ? "先检查用药风险" : role === "child" ? "已核对，提交修改申请" : "已核对，保存计划"}
          </Button>
          {checkedRisk && <Button type="button" variant="secondary" loading={action.busy} onClick={() => void action.run(checkRisk)}>重新检查风险</Button>}
        </Card>
      </form>
      <ErrorNotice error={action.error} />
      {original?.active && role === "child" && (
        <Button
          className="full"
          variant="text"
          onClick={() => setDeactivating(true)}
        >
          申请停用这项计划
        </Button>
      )}
      <ConfirmDialog
        open={deactivating}
        title="申请停用这项计划？"
        close={() => setDeactivating(false)}
        busy={action.busy}
        confirm={() => {
          void deactivate();
        }}
      >
        <p>这不会立即改变计划，将先通知家人核对。</p>
      </ConfirmDialog>
    </>
  );
}

export function Reminders() {
  const { api, elderId, role } = useSession(),
    { revision, refresh } = useData(),
    navigate = useNavigate(),
    action = useAction();
  const resource = useResource(
    `reminders:${api.base}:${role}:${elderId}`,
    () =>
      api.get<Schemas["ReminderSettings"]>(
        elderPath(elderId!, "reminder-settings"),
      ),
    revision,
  );
  const [edited, setEdited] = useState<Schemas["ReminderSettings"] | null>(
      null,
    ),
    [saved, setSaved] = useState(false);
  const value = edited || resource.data;
  const save = () =>
    action.run(async (keys) => {
      if (!value || !resource.data) return;
      const patch = {
        meals: value.meals,
        exercise: value.exercise,
        daily_summary: value.daily_summary,
        voice_enabled: value.voice_enabled,
      };
      const path = elderPath(
        elderId!,
        role === "elder" ? "reminder-settings" : "change-proposals",
      );
      const body =
        role === "elder"
          ? { expected_version: value.version, patch }
          : {
              target_type: "reminder_settings",
              target_id: elderId,
              operation: "update",
              base_version: value.version,
              patch,
            };
      if (role === "elder") await api.put(path, body, keys.for(path, body));
      else await api.post(path, body, keys.for(path, body));
      refresh();
      setEdited(null);
      setSaved(true);
      if (role === "child") navigate("/proposals");
    });
  return (
    <Page
      title="安排日常的节奏"
      subtitle={
        role === "elder"
          ? "按自己的习惯，设置温柔的提醒"
          : "家人核对后，才会改变提醒安排"
      }
    >
      <ErrorNotice
        error={resource.error || action.error}
        retry={() => {
          setEdited(null);
          void resource.refresh();
        }}
      />
      {saved && <Success>提醒设置已保存</Success>}
      {value ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <Card>
            <ReminderFields value={value} onChange={setEdited} />
            <Button
              className="full section"
              type="submit"
              loading={action.busy}
            >
              {role === "elder" ? "确认保存提醒" : "向家人提交申请"}
            </Button>
          </Card>
        </form>
      ) : (
        <Loading />
      )}
    </Page>
  );
}
