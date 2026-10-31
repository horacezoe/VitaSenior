import { useEffect, useState } from "react";
import {
  Link,
  Navigate,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { Plus, Check } from "lucide-react";
import {
  Button,
  Card,
  Empty,
  ErrorNotice,
  Field,
  Loading,
  Page,
  useAction,
  useResource,
} from "../components/ui";
import { ConfirmDialog, splitList } from "../components/forms";
import { categoryNames, RecordRow, recordTitle } from "../components/records";
import {
  elderPath,
  localDay,
  query,
  type Checkin,
  type Page as ApiPage,
  type Schemas,
} from "../api/client";
import { useSession } from "../state/session";
import { useData } from "../state/data";

export function Records() {
  const { api, elderId, role } = useSession(),
    { revision, observe } = useData();
  const [params, setParams] = useSearchParams(),
    day = params.get("date") || localDay(api.now());
  const [category, setCategory] = useState(""),
    [more, setMore] = useState<Checkin[]>([]),
    [cursor, setCursor] = useState<string | null>(null);
  const action = useAction();
  const path = elderPath(elderId!, "checkins");
  const resource = useResource(
    `records:${api.base}:${role}:${elderId}:${day}:${category}`,
    () =>
      api.get<ApiPage<Checkin>>(
        path + query({ date: day, type: category || undefined, limit: 30 }),
      ),
    revision,
  );
  useEffect(() => {
    setMore([]);
    setCursor(resource.data?.next_cursor || null);
    if (resource.data) observe(resource.data.items, false);
  }, [resource.data, observe]);
  const loadMore = () =>
    action.run(async () => {
      if (!cursor) return;
      const page = await api.get<ApiPage<Checkin>>(
        path +
          query({ date: day, type: category || undefined, limit: 30, cursor }),
      );
      setMore((old) => [...old, ...page.items]);
      setCursor(page.next_cursor);
      observe(page.items, false);
    });
  const records = [...(resource.data?.items || []), ...more];
  return (
    <Page
      title="健康记录"
      subtitle={
        role === "elder" ? "记下真实的日常，也能随时核对" : "和家人一起了解日常"
      }
      action={
        role === "elder" && (
          <Link
            className="icon-button"
            to={`/records/new?date=${day}`}
            aria-label="补充记录"
          >
            <Plus size={21} />
          </Link>
        )
      }
    >
      <Field label="查看日期">
        <input
          type="date"
          value={day}
          onChange={(e) => {
            if (e.target.value) setParams({ date: e.target.value });
          }}
        />
      </Field>
      <div className="record-filter" role="group" aria-label="记录类别">
        {[
          ["", "全部"],
          ["diet", "饮食"],
          ["exercise", "运动"],
          ["medication", "用药"],
        ].map(([value, name]) => (
          <button
            type="button"
            key={value}
            className={category === value ? "active" : ""}
            onClick={() => setCategory(value)}
          >
            {name}
          </button>
        ))}
      </div>
      <ErrorNotice
        error={resource.error || action.error}
        retry={() => {
          void resource.refresh();
        }}
      />
      {resource.loading && !resource.data ? (
        <Loading />
      ) : records.length ? (
        <Card>
          {records.map((record) => (
            <RecordRow
              record={record}
              key={record.checkin_id}
              edit={role === "elder"}
            />
          ))}
        </Card>
      ) : (
        <Empty
          title="这一天还没有这类记录"
          text="未记录，不代表实际没有完成。"
        />
      )}
      {cursor && (
        <Button
          className="full"
          variant="text"
          loading={action.busy}
          onClick={() => {
            void loadMore();
          }}
        >
          再看一些
        </Button>
      )}
    </Page>
  );
}

type Payload =
  | Schemas["DietPayload"]
  | Schemas["ExercisePayload"]
  | Schemas["MedicationPayload"];
export function RecordEditorPage() {
  const { role, api, elderId } = useSession(),
    { id } = useParams(),
    [search] = useSearchParams();
  const date = search.get("date") || localDay(api.now());
  const resource = useResource(
    `edit-record:${api.base}:${role}:${elderId}:${id}:${date}`,
    async () => {
      if (!id || id === "new") return null;
      let cursor: string | undefined;
      do {
        const page = await api.get<ApiPage<Checkin>>(
          elderPath(elderId!, "checkins") + query({ date, limit: 100, cursor }),
        );
        const found = page.items.find((record) => record.checkin_id === id);
        if (found) return found;
        cursor = page.next_cursor || undefined;
      } while (cursor);
      throw new Error("未找到这条记录，请返回列表重新选择。");
    },
  );
  if (role !== "elder") return <Navigate to="/records" replace />;
  return (
    <Page
      title={id === "new" ? "补充一条真实记录" : "核对这条记录"}
      subtitle="本人核对后，才会保存"
      back={`/records?date=${date}`}
    >
      <ErrorNotice error={resource.error} />
      {resource.loading ? (
        <Loading />
      ) : (
        !resource.error && (
          <RecordEditor
            key={id || "new"}
            original={resource.data || undefined}
            date={date}
          />
        )
      )}
    </Page>
  );
}
function RecordEditor({
  original,
  date,
}: {
  original?: Checkin;
  date: string;
}) {
  const { api, elderId } = useSession(),
    { refresh, observe } = useData(),
    navigate = useNavigate(),
    action = useAction();
  const [selection] = useSearchParams();
  const chosen = selection.get("type");
  const [category, setCategory] = useState<Checkin["type"]>(
    original?.type ||
      (chosen === "exercise" || chosen === "medication" ? chosen : "diet"),
  );
  const [meal, setMeal] = useState<"breakfast" | "lunch" | "dinner">(
    original && "meal_slot" in original.payload
      ? original.payload.meal_slot
      : "lunch",
  );
  const [foods, setFoods] = useState(
    original && "foods" in original.payload
      ? original.payload.foods.join("，")
      : "",
  );
  const [activity, setActivity] = useState(
    original && "activity" in original.payload ? original.payload.activity : "",
  );
  const [minutes, setMinutes] = useState(
    original && "duration_minutes" in original.payload
      ? String(original.payload.duration_minutes)
      : "",
  );
  const [notes, setNotes] = useState(original?.payload.notes || ""),
    [taskId, setTaskId] = useState(original?.task_id || "");
  const [intake, setIntake] = useState<"taken" | "not_taken">(
    original && "intake_status" in original.payload
      ? original.payload.intake_status
      : "taken",
  );
  const [photo, setPhoto] = useState<File | null>(null),
    [imageId, setImageId] = useState<string | null>(null),
    [cancelling, setCancelling] = useState(false);
  const actualTime = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Hong_Kong",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
    .format(new Date(original?.occurred_at || api.now()))
    .replace(" ", "T");
  const initialTime =
    original || date === localDay(api.now()) ? actualTime : `${date}T12:00`;
  const [occurred, setOccurred] = useState(initialTime);
  const medical = useResource(
    `record-task:${api.base}:${elderId}:${category}`,
    async () =>
      category === "medication" && !original
        ? {
            tasks: await api.get<Schemas["TaskList"]>(
              elderPath(elderId!, "tasks") +
                query({ date: localDay(api.now()) }),
            ),
            plans: await api.get<Schemas["PlanList"]>(
              elderPath(elderId!, "medication-plans"),
            ),
          }
        : null,
  );
  const save = () =>
    action.run(async (keys) => {
      let payload: Payload;
      if (category === "diet") {
        const uploaded = photo
          ? imageId || (await api.upload(elderId!, photo, "meal")).asset_id
          : null;
        if (uploaded && uploaded !== imageId) setImageId(uploaded);
        payload = {
          meal_slot: meal,
          foods: splitList(foods),
          notes,
          image_asset_ids: uploaded
            ? [uploaded]
            : original && "image_asset_ids" in original.payload
              ? original.payload.image_asset_ids
              : [],
          food_groups:
            original &&
            "foods" in original.payload &&
            JSON.stringify(splitList(foods)) ===
              JSON.stringify(original.payload.foods)
              ? original.payload.food_groups
              : [],
        };
        if (!payload.foods.length)
          throw new Error("请至少填写一种实际吃过的食物。");
      } else if (category === "exercise")
        payload = { activity, duration_minutes: Number(minutes), notes };
      else {
        if (original && "plan_id" in original.payload)
          payload = { ...original.payload, intake_status: intake, notes };
        else {
          const task = medical.data?.tasks.items.find(
            (item) => item.task_id === taskId,
          );
          const plan = medical.data?.plans.items.find(
            (item) => item.plan_id === task?.plan_id,
          );
          const slot = plan?.schedule.slots.find(
            (item) => `${plan.plan_id}:${item.slot_id}` === task?.slot_key,
          );
          if (!task || !plan || !slot)
            throw new Error("请先选择实际的用药任务，并核对计划。");
          payload = {
            plan_id: plan.plan_id,
            slot_id: slot.slot_id,
            intake_status: intake,
            notes,
          };
        }
      }
      const occurred_at = new Date(occurred + ":00+08:00").toISOString();
      const body = original
        ? { expected_version: original.version, occurred_at, payload }
        : {
            type: category,
            occurred_at,
            payload,
            ...(category === "medication" ? { task_id: taskId } : {}),
          };
      const path = original
        ? `/api/v1/checkins/${original.checkin_id}`
        : elderPath(elderId!, "checkins");
      const saved = original
        ? await api.put<Checkin>(path, body, keys.for(path, body))
        : await api.post<Checkin>(path, body, keys.for(path, body));
      observe([saved], !original);
      refresh();
      navigate(-1);
    });
  const cancel = () =>
    action.run(async (keys) => {
      if (!original) return;
      const path = `/api/v1/checkins/${original.checkin_id}?expected_version=${original.version}`;
      await api.delete<Schemas["CancelledCheckin"]>(
        path,
        keys.for(path, original.version),
      );
      refresh();
      navigate(-1);
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
          {!original && (
            <Field label="记录类别">
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value as Checkin["type"])}
              >
                {Object.entries(categoryNames).map(([key, title]) => (
                  <option value={key} key={key}>
                    {title}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <Field label="实际发生时间">
            <input
              type="datetime-local"
              required
              value={occurred}
              onChange={(e) => setOccurred(e.target.value)}
            />
          </Field>
          {category === "diet" ? (
            <>
              <Field label="餐次">
                <select
                  value={meal}
                  onChange={(e) => setMeal(e.target.value as typeof meal)}
                >
                  <option value="breakfast">早餐</option>
                  <option value="lunch">午餐</option>
                  <option value="dinner">晚餐</option>
                </select>
              </Field>
              <Field
                label="实际吃过的食物"
                hint="多种食物用逗号分开，不需要估算热量。"
              >
                <textarea
                  required
                  value={foods}
                  onChange={(e) => setFoods(e.target.value)}
                />
              </Field>
              <Field label="餐食照片（可选）">
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  capture="environment"
                  onChange={(e) => {
                    setPhoto(e.target.files?.[0] || null);
                    setImageId(null);
                  }}
                />
              </Field>
            </>
          ) : category === "exercise" ? (
            <>
              <Field label="实际完成的运动">
                <input
                  value={activity}
                  required
                  onChange={(e) => setActivity(e.target.value)}
                />
              </Field>
              <Field label="持续时长（分钟）">
                <input
                  type="number"
                  min="1"
                  max="1440"
                  required
                  value={minutes}
                  onChange={(e) => setMinutes(e.target.value)}
                />
              </Field>
            </>
          ) : (
            <>
              {!original && (
                <Field label="对应的实际用药任务">
                  <select
                    required
                    value={taskId}
                    onChange={(e) => setTaskId(e.target.value)}
                  >
                    <option value="">请选择药品及具体时段</option>
                    {medical.data?.tasks.items
                      .filter(
                        (task) =>
                          task.category === "medication" && !task.cancelled,
                      )
                      .map((task) => (
                        <option value={task.task_id} key={task.task_id}>
                          {task.title}
                          {task.due_at
                            ? ` · ${new Date(task.due_at).toLocaleTimeString("zh-CN", { timeZone: "Asia/Hong_Kong", hour: "2-digit", minute: "2-digit" })}`
                            : " · 等待餐后安排"}
                        </option>
                      ))}
                  </select>
                </Field>
              )}
              {original && (
                <p className="note-card">
                  {recordTitle(original)}
                  。药品与时段保持原任务，不能通过纠正更换目标。
                </p>
              )}
              <Field label="本人明确的实际情况">
                <select
                  value={intake}
                  onChange={(e) => setIntake(e.target.value as typeof intake)}
                >
                  <option value="taken">已按既定计划服用</option>
                  <option value="not_taken">明确未服用</option>
                </select>
              </Field>
              <ErrorNotice error={medical.error} />
            </>
          )}
          <Field label="备注">
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </Field>
          <Button
            icon={Check}
            loading={action.busy}
            className="full"
            type="submit"
          >
            本人已核对，确认保存
          </Button>
        </Card>
      </form>
      <ErrorNotice error={action.error} />
      {original && (
        <Button
          variant="text"
          className="full"
          onClick={() => setCancelling(true)}
        >
          取消这条记录
        </Button>
      )}
      <ConfirmDialog
        open={cancelling}
        title="取消这条记录？"
        close={() => setCancelling(false)}
        busy={action.busy}
        confirm={() => {
          void cancel();
        }}
      >
        <p>
          取消后将不计入当天进度，原始信息会保留。已获得的鸡蛋暂不自动扣回。
        </p>
      </ConfirmDialog>
    </>
  );
}
