import { ApiError } from "../api/client";
type Entry = {
  at: string;
  turn: string;
  node: string;
  attempt: number;
  state: string;
  code?: string;
  requestId?: string;
};
const entries: Entry[] = [];
export function logNode(
  turn: string,
  node: string,
  attempt: number,
  state: string,
  error?: unknown,
) {
  const e: Entry = {
    at: new Date().toISOString(),
    turn,
    node,
    attempt,
    state,
    ...(error instanceof ApiError
      ? { code: error.code, requestId: error.requestId }
      : {}),
  };
  entries.push(e);
  if (entries.length > 200) entries.shift();
  console.info("[YinLink workflow]", e);
}
export function exportDiagnostics() {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(entries, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = "yinlink-workflow.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export async function retryNode<T>(
  turn: string,
  node: string,
  signal: AbortSignal,
  action: () => Promise<T>,
): Promise<T> {
  for (let attempt = 1; ; attempt++) {
    if (signal.aborted) throw new DOMException("已停止", "AbortError");
    logNode(turn, node, attempt, "started");
    try {
      const result = await action();
      logNode(turn, node, attempt, "succeeded");
      return result;
    } catch (error) {
      logNode(turn, node, attempt, "failed", error);
      if (
        signal.aborted ||
        attempt >= 2 ||
        !(error instanceof ApiError) ||
        (!error.retryable && ![0, 429, 504].includes(error.status))
      )
        throw error;
      await new Promise<void>((resolve, reject) => {
        const cancel = () => {
          clearTimeout(timer);
          reject(new DOMException("已停止", "AbortError"));
        };
        const timer = setTimeout(() => {
          signal.removeEventListener("abort", cancel);
          resolve();
        }, 600);
        signal.addEventListener("abort", cancel, { once: true });
      });
    }
  }
}
