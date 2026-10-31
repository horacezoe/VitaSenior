import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type InputHTMLAttributes,
} from "react";
import { Plus, Trash2 } from "lucide-react";
import { Field, Button } from "./ui";
import { uid, type Schemas } from "../api/client";

export type ProfileInput = Schemas["ProfileFields"];
export type PlanInput = Schemas["MedicationPlanWrite-Input"];
export const splitList = (value: string) =>
  value
    .split(/[,，、\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
function ListInput({
  values,
  update,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & {
  values: string[];
  update(values: string[]): void;
}) {
  const normalized = values.join("，"),
    previous = useRef(normalized),
    [raw, setRaw] = useState(normalized);
  useEffect(() => {
    if (normalized !== previous.current) {
      setRaw(normalized);
      previous.current = normalized;
    }
  }, [normalized]);
  return (
    <input
      {...props}
      value={raw}
      onChange={(e) => {
        setRaw(e.target.value);
        const items = splitList(e.target.value);
        previous.current = items.join("，");
        update(items);
      }}
    />
  );
}
export function ProfileFields({
  value,
  onChange,
}: {
  value: ProfileInput;
  onChange(value: ProfileInput): void;
}) {
  const update = (patch: Partial<ProfileInput>) =>
    onChange({ ...value, ...patch });
  return (
    <>
      <Field label="怎么称呼您">
        <input
          value={value.display_name}
          required
          maxLength={60}
          onChange={(e) => update({ display_name: e.target.value })}
        />
      </Field>
      <div className="form-grid">
        <Field label="出生日期">
          <input
            type="date"
            value={value.birth_date || ""}
            onChange={(e) => update({ birth_date: e.target.value || null })}
          />
        </Field>
        <Field label="性别">
          <select
            value={value.sex || "unknown"}
            onChange={(e) =>
              update({ sex: e.target.value as ProfileInput["sex"] })
            }
          >
            <option value="unknown">暂不填写</option>
            <option value="female">女</option>
            <option value="male">男</option>
            <option value="other">其他</option>
          </select>
        </Field>
      </div>
      <Field
        label="已确认的疾病"
        hint="仅填写已由本人或医生确认的信息，多项用逗号分开。"
      >
        <ListInput
          values={value.conditions || []}
          update={(conditions) => update({ conditions })}
        />
      </Field>
      <Field label="过敏信息" hint="不确定的内容请先核对，多项用逗号分开。">
        <ListInput
          values={value.allergies || []}
          update={(allergies) => update({ allergies })}
        />
      </Field>
      <Field label="健康备注">
        <textarea
          value={value.medical_notes || ""}
          onChange={(e) => update({ medical_notes: e.target.value })}
        />
      </Field>
    </>
  );
}
export function PlanFields({
  value,
  onChange,
}: {
  value: PlanInput;
  onChange(value: PlanInput): void;
}) {
  const patch = (fields: Partial<PlanInput>) =>
    onChange({ ...value, ...fields });
  const schedule = value.schedule;
  return (
    <>
      <Field label="药品名称">
        <input
          value={value.name}
          required
          onChange={(e) => patch({ name: e.target.value })}
        />
      </Field>
      <Field label="既定用量" hint="按照已核对的计划填写，不自行调整。">
        <input
          value={value.dose_display}
          required
          placeholder="例如：按已确认计划填写"
          onChange={(e) => patch({ dose_display: e.target.value })}
        />
      </Field>
      <div className="form-grid">
        <Field label="开始日期">
          <input
            type="date"
            required
            value={value.start_date}
            onChange={(e) => patch({ start_date: e.target.value })}
          />
        </Field>
        <Field label="结束日期">
          <input
            type="date"
            min={value.start_date}
            value={value.end_date || ""}
            onChange={(e) => patch({ end_date: e.target.value || null })}
          />
        </Field>
      </div>
      <Field label="服药安排">
        <select
          value={schedule.mode}
          onChange={(e) =>
            patch({
              schedule:
                e.target.value === "fixed"
                  ? {
                      mode: "fixed",
                      slots: [{ slot_id: uid("slot"), local_time: "08:00" }],
                    }
                  : {
                      mode: "after_meal",
                      slots: [
                        {
                          slot_id: uid("slot"),
                          meal_slot: "breakfast",
                          delay_minutes: 30,
                        },
                      ],
                    },
            })
          }
        >
          <option value="fixed">固定时间</option>
          <option value="after_meal">餐后安排</option>
        </select>
      </Field>
      {schedule.slots.map((slot, index) => (
        <div key={slot.slot_id} className="plan-slot">
          <div className="form-grid">
            {schedule.mode === "fixed" && "local_time" in slot ? (
              <Field label={`第 ${index + 1} 个时间`}>
                <input
                  type="time"
                  value={slot.local_time}
                  required
                  onChange={(e) =>
                    patch({
                      schedule: {
                        mode: "fixed",
                        slots: schedule.slots.map((item, i) =>
                          i === index
                            ? { ...item, local_time: e.target.value }
                            : item,
                        ),
                      },
                    })
                  }
                />
              </Field>
            ) : (
              "meal_slot" in slot && (
                <>
                  <Field label="餐次">
                    <select
                      value={slot.meal_slot}
                      onChange={(e) => {
                        if (schedule.mode === "after_meal")
                          patch({
                            schedule: {
                              ...schedule,
                              slots: schedule.slots.map((item, i) =>
                                i === index
                                  ? {
                                      ...item,
                                      meal_slot: e.target.value as
                                        "breakfast" | "lunch" | "dinner",
                                    }
                                  : item,
                              ),
                            },
                          });
                      }}
                    >
                      <option value="breakfast">早餐后</option>
                      <option value="lunch">午餐后</option>
                      <option value="dinner">晚餐后</option>
                    </select>
                  </Field>
                  <Field label="间隔分钟">
                    <input
                      type="number"
                      min="0"
                      max="240"
                      required
                      value={slot.delay_minutes}
                      onChange={(e) => {
                        if (schedule.mode === "after_meal")
                          patch({
                            schedule: {
                              ...schedule,
                              slots: schedule.slots.map((item, i) =>
                                i === index
                                  ? {
                                      ...item,
                                      delay_minutes: Number(e.target.value),
                                    }
                                  : item,
                              ),
                            },
                          });
                      }}
                    />
                  </Field>
                </>
              )
            )}
          </div>
          {schedule.slots.length > 1 && (
            <button
              type="button"
              className="text-button"
              onClick={() =>
                patch({
                  schedule: {
                    ...schedule,
                    slots: schedule.slots.filter((_, i) => i !== index),
                  } as PlanInput["schedule"],
                })
              }
            >
              <Trash2 size={14} />
              移除此时段
            </button>
          )}
        </div>
      ))}
      <Button
        type="button"
        variant="secondary"
        icon={Plus}
        onClick={() =>
          patch({
            schedule:
              schedule.mode === "fixed"
                ? {
                    ...schedule,
                    slots: [
                      ...schedule.slots,
                      { slot_id: uid("slot"), local_time: "18:00" },
                    ],
                  }
                : {
                    ...schedule,
                    slots: [
                      ...schedule.slots,
                      {
                        slot_id: uid("slot"),
                        meal_slot: "dinner",
                        delay_minutes: 30,
                      },
                    ],
                  },
          })
        }
      >
        添加时段
      </Button>
      <Field label="计划备注">
        <textarea
          value={value.notes || ""}
          onChange={(e) => patch({ notes: e.target.value })}
        />
      </Field>
    </>
  );
}
export function ReminderFields({
  value,
  onChange,
}: {
  value: Schemas["ReminderSettings"];
  onChange(value: Schemas["ReminderSettings"]): void;
}) {
  const names = {
    breakfast: "早餐提醒",
    lunch: "午餐提醒",
    dinner: "晚餐提醒",
  };
  return (
    <>
      <div className="toggle-row">
        <span>语音提醒</span>
        <input
          type="checkbox"
          aria-label="语音提醒"
          checked={value.voice_enabled}
          onChange={(e) =>
            onChange({ ...value, voice_enabled: e.target.checked })
          }
        />
      </div>
      {value.meals.map((meal, index) => (
        <div className="toggle-row" key={meal.slot}>
          <span>{names[meal.slot]}</span>
          <input
            type="time"
            aria-label={`${names[meal.slot]}时间`}
            value={meal.local_time}
            onChange={(e) =>
              onChange({
                ...value,
                meals: value.meals.map((m, i) =>
                  i === index ? { ...m, local_time: e.target.value } : m,
                ),
              })
            }
          />
          <input
            type="checkbox"
            aria-label={names[meal.slot]}
            checked={meal.enabled}
            onChange={(e) =>
              onChange({
                ...value,
                meals: value.meals.map((m, i) =>
                  i === index ? { ...m, enabled: e.target.checked } : m,
                ),
              })
            }
          />
        </div>
      ))}
      {(["exercise", "daily_summary"] as const).map((key) => (
        <div className="toggle-row" key={key}>
          <span>{key === "exercise" ? "运动提醒" : "每日小结"}</span>
          <input
            aria-label={key === "exercise" ? "运动提醒时间" : "每日小结时间"}
            type="time"
            value={value[key].local_time}
            onChange={(e) =>
              onChange({
                ...value,
                [key]: { ...value[key], local_time: e.target.value },
              })
            }
          />
          <input
            type="checkbox"
            aria-label={key === "exercise" ? "运动提醒" : "每日小结"}
            checked={value[key].enabled}
            onChange={(e) =>
              onChange({
                ...value,
                [key]: { ...value[key], enabled: e.target.checked },
              })
            }
          />
        </div>
      ))}
    </>
  );
}
export function ConfirmDialog({
  open,
  title,
  children,
  confirm,
  close,
  busy,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  confirm(): void;
  close(): void;
  busy?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (open) ref.current?.showModal();
    else ref.current?.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      className="confirm-dialog"
      aria-labelledby="confirm-title"
      onCancel={(e) => {
        e.preventDefault();
        close();
      }}
    >
      <h2 id="confirm-title">{title}</h2>
      <div>{children}</div>
      <div className="form-actions">
        <Button type="button" variant="secondary" onClick={close}>
          再想一想
        </Button>
        <Button type="button" loading={busy} onClick={confirm}>
          确认
        </Button>
      </div>
    </dialog>
  );
}
