import { useSession } from "../state/session";
import type { Schemas } from "../api/client";
import { ErrorNotice, Field, useResource } from "./ui";

export default function DemoPersonaPicker({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange(value: string): void;
  disabled?: boolean;
}) {
  const { api } = useSession();
  const personas = useResource(`demo-personas:${api.base}`, () =>
    api.get<Schemas["DemoPersonas"]>("/api/v1/demo/personas"),
  );
  return (
    <>
      <Field
        label="选择演示人物"
        hint="人物和健康资料均为虚构。首次登录会自动查询对应社区档案，再由本人核对。"
      >
        <select
          value={value}
          disabled={disabled || !personas.data}
          onChange={(event) => onChange(event.target.value)}
        >
          {!personas.data && <option value={value}>{personas.loading ? "正在读取演示人物…" : "暂时无法读取演示人物"}</option>}
          {personas.data?.items.map((person) => (
            <option key={person.persona_id} value={person.persona_id}>
              {person.display_name} · {person.has_community_record
                ? person.conditions.map((condition) => condition.replace("（演示档案）", "")).join("、") || "无已登记基础慢病"
                : "体验未匹配与手工建档"}
            </option>
          ))}
        </select>
      </Field>
      <ErrorNotice error={personas.error} retry={() => void personas.refresh()} />
    </>
  );
}
