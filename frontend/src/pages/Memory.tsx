import { useState } from "react";
import { Pencil, Trash2 } from "lucide-react";
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
import { ConfirmDialog } from "../components/forms";
import { elderPath, type Schemas } from "../api/client";
import { useSession } from "../state/session";
import { useData } from "../state/data";

const sourceNames = {
  explicit_statement: "本人明确表达",
  observed_pattern: "多日记录归纳",
  user_correction: "本人纠正",
  demo_seed: "历史资料",
};
export default function Memory() {
  const { api, elderId, role } = useSession(),
    { revision, refresh } = useData(),
    action = useAction();
  const resource = useResource(
    `memory:${api.base}:${role}:${elderId}`,
    () => api.get<Schemas["MemoryDocument"]>(elderPath(elderId!, "memory")),
    revision,
  );
  const [editing, setEditing] = useState<string | null>(null),
    [editVersion, setEditVersion] = useState(0),
    [text, setText] = useState(""),
    [removing, setRemoving] = useState<{ id: string; version: number } | null>(
      null,
    );
  const save = () =>
    action.run(async (keys) => {
      if (!resource.data || !editing) return;
      const path = elderPath(elderId!, `memory/entries/${editing}`),
        body = { expected_version: editVersion, text };
      await api.put(path, body, keys.for(path, body));
      setEditing(null);
      refresh();
    });
  const remove = () =>
    action.run(async (keys) => {
      if (!resource.data || !removing) return;
      const path =
        elderPath(elderId!, `memory/entries/${removing.id}`) +
        `?expected_version=${removing.version}`;
      await api.delete(path, keys.for(path, removing.version));
      setRemoving(null);
      refresh();
    });
  return (
    <Page title="小银龄记得的事" subtitle="每一条记忆，都有来源，也可以更正">
      <ErrorNotice
        error={resource.error || action.error}
        retry={() => {
          void resource.refresh();
        }}
      />
      {resource.loading && !resource.data ? (
        <Loading />
      ) : resource.data?.entries.length ? (
        resource.data.entries.map((entry) => (
          <Card key={entry.entry_id} className="section">
            <span className="tag">{sourceNames[entry.source_type]}</span>
            {editing === entry.entry_id ? (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void save();
                }}
              >
                <Field label="希望记住的内容">
                  <textarea
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    required
                    maxLength={1000}
                  />
                </Field>
                <div className="form-actions">
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => setEditing(null)}
                  >
                    暂不更改
                  </Button>
                  <Button loading={action.busy} type="submit">
                    确认纠正
                  </Button>
                </div>
              </form>
            ) : (
              <>
                <p
                  className="note-card"
                  style={{ color: "var(--text)", fontSize: 16 }}
                >
                  {entry.text}
                </p>
                <small className="muted">
                  更新于{" "}
                  {new Date(entry.updated_at).toLocaleDateString("zh-CN", {
                    timeZone: "Asia/Hong_Kong",
                  })}
                  {entry.source_ids.length
                    ? ` · ${entry.source_ids.length} 条来源`
                    : ""}
                </small>
                {role === "elder" && (
                  <div className="inline-actions">
                    <Button
                      variant="text"
                      icon={Pencil}
                      onClick={() => {
                        setEditing(entry.entry_id);
                        setEditVersion(resource.data!.version);
                        setText(entry.text);
                      }}
                    >
                      纠正
                    </Button>
                    <Button
                      variant="text"
                      icon={Trash2}
                      onClick={() =>
                        setRemoving({
                          id: entry.entry_id,
                          version: resource.data!.version,
                        })
                      }
                    >
                      不再记住
                    </Button>
                  </div>
                )}
              </>
            )}
          </Card>
        ))
      ) : (
        <Empty
          title="慢慢了解，不急着下结论"
          text="您可以在通话中明确告诉小银龄自己的偏好。一次吃饭，不会被当作长期习惯。"
        />
      )}
      <ConfirmDialog
        open={!!removing}
        title="不再记住这条内容？"
        close={() => setRemoving(null)}
        busy={action.busy}
        confirm={() => {
          void remove();
        }}
      >
        <p>之后的交流将不再使用这条记忆，原始健康记录保持不变。</p>
      </ConfirmDialog>
    </Page>
  );
}
