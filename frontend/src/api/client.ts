import type { components } from "./schema";

export type Schemas = components["schemas"];
export type Role = "elder" | "child";
export type Checkin = Schemas["Checkin"];
export type Notification = Schemas["Notification"];
export type AgentAction = Schemas["AgentTurn"]["actions"][number];
export type Page<T> = { items: T[]; next_cursor: string | null };
export const uid = (prefix = "web") => {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return `${prefix}-${Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("")}`;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> | null = null,
    public retryable = false,
    public requestId?: string,
  ) {
    super(message);
  }
}

const messages: Record<string, string> = {
  UNAUTHENTICATED: "请重新登录后继续。",
  SESSION_EXPIRED: "登录已过期，请重新登录。",
  ELDER_ACCESS_DENIED: "当前账号无法查看这位家人的信息。",
  PROPOSAL_REQUIRED: "请通过修改申请协助家人维护。",
  NOT_FOUND: "这项内容已不可用，请刷新后重试。",
  VERSION_CONFLICT: "内容已有更新，请核对最新内容再操作。",
  IDEMPOTENCY_CONFLICT: "这次操作的信息已有变化，请刷新核对。",
  ACTION_EXPIRED: "这份待确认内容已过期，请重新说明。",
  ACTION_CANCELLED: "这份内容已取消，可以重新开始。",
  DRAFT_EXPIRED: "草稿已过期，请重新说明。",
  PROVIDER_TIMEOUT: "小银龄这次回复慢了一些，请稍后重试。",
  PROVIDER_ERROR: "这次没能处理成功，您的原有记录还在。",
  MEDIA_TOO_LARGE: "文件太大，请缩小图片或缩短录音。",
  MEDIA_UNSUPPORTED: "暂不支持这个文件格式。",
  ASR_FORMAT_UNSUPPORTED: "录音格式暂不可用，请改用文字辅助。",
  VALIDATION_ERROR: "请检查填写内容后再试。",
  MODULE_NOT_IMPLEMENTED: "这个功能暂时还不能使用。",
  RATE_LIMITED: "操作有些频繁，请稍等片刻。",
  NETWORK_ERROR: "暂时没有连上，请检查网络后重试。",
  BIND_CODE_EXPIRED: "绑定码已过期，请让家人重新生成。",
  BIND_CODE_INVALID: "绑定码不正确，请核对四位数字。",
  BIND_CODE_USED: "绑定码已使用，请重新生成。",
};
export function friendlyError(error: unknown): string {
  if (error instanceof ApiError)
    return (
      messages[error.code] ||
      (error.status === 403
        ? "当前账号无法进行这项操作，请核对身份与家庭连接。"
        : /[\u4e00-\u9fff]/.test(error.message || "")
          ? error.message
          : "操作未完成，请刷新核对后重试。")
    );
  if (error instanceof DOMException && error.name === "NotAllowedError")
    return "没有获得摄像头或麦克风权限，请在浏览器设置中允许后重试。";
  if (error instanceof DOMException && error.name === "NotFoundError")
    return "未找到可用的麦克风，请检查设备，或先用文字交流。";
  if (error instanceof DOMException && error.name === "NotReadableError")
    return "录音设备暂时被占用，请关闭其他通话后重试。";
  return error instanceof Error ? error.message : "操作未完成，请稍后重试。";
}

export class Api {
  private serverAnchor: { timestamp: number; received: number } | null = null;
  constructor(
    public base = "",
    public token: string | null = null,
    public unauthorized?: () => void,
  ) {}
  now() {
    return this.serverAnchor
      ? this.serverAnchor.timestamp +
          performance.now() -
          this.serverAnchor.received
      : Date.now();
  }
  async request<T>(
    method: string,
    path: string,
    body?: unknown,
    options: { key?: string; signal?: AbortSignal; timeout?: number } = {},
  ): Promise<T> {
    const controller = new AbortController();
    const abort = () => controller.abort(options.signal?.reason);
    if (options.signal?.aborted) abort();
    options.signal?.addEventListener("abort", abort, { once: true });
    const timer = setTimeout(
      () =>
        controller.abort(
          new DOMException("请求超时，请重试。", "TimeoutError"),
        ),
      options.timeout ?? 70000,
    );
    const headers = new Headers({ Accept: "application/json" });
    if (this.token) headers.set("Authorization", `Bearer ${this.token}`);
    if (options.key) headers.set("Idempotency-Key", options.key);
    const form = body instanceof FormData;
    if (body !== undefined && !form)
      headers.set("Content-Type", "application/json");
    try {
      const response = await fetch(this.base + path, {
        method,
        headers,
        body:
          body === undefined ? undefined : form ? body : JSON.stringify(body),
        signal: controller.signal,
      });
      const envelope = await response.json();
      if (envelope.meta?.server_time)
        this.serverAnchor = {
          timestamp: Date.parse(envelope.meta.server_time),
          received: performance.now(),
        };
      if (!response.ok) {
        if (response.status === 401) this.unauthorized?.();
        const e = envelope.error || {};
        throw new ApiError(
          response.status,
          e.code || "UNKNOWN_ERROR",
          e.message,
          e.details,
          e.retryable,
          envelope.meta?.request_id,
        );
      }
      return envelope.data as T;
    } catch (error) {
      if (error instanceof ApiError || options.signal?.aborted) throw error;
      if (controller.signal.aborted)
        throw new ApiError(
          0,
          "PROVIDER_TIMEOUT",
          "请求超时，请重试。",
          null,
          true,
        );
      throw new ApiError(
        0,
        "NETWORK_ERROR",
        "暂时没有连上，请检查网络后重试。",
        null,
        true,
      );
    } finally {
      clearTimeout(timer);
      options.signal?.removeEventListener("abort", abort);
    }
  }
  get<T>(path: string, signal?: AbortSignal) {
    return this.request<T>("GET", path, undefined, { signal });
  }
  post<T>(path: string, body?: unknown, key = uid(), signal?: AbortSignal) {
    return this.request<T>("POST", path, body, { key, signal });
  }
  put<T>(path: string, body: unknown, key = uid()) {
    return this.request<T>("PUT", path, body, { key });
  }
  delete<T>(path: string, key = uid()) {
    return this.request<T>("DELETE", path, undefined, { key });
  }
  upload(elder: string, file: Blob, purpose: string, signal?: AbortSignal) {
    const form = new FormData();
    form.set("elder_id", elder);
    form.set("purpose", purpose);
    form.set(
      "file",
      file,
      file instanceof File
        ? file.name
        : file.type.startsWith("audio/")
          ? "speech.wav"
          : "frame.jpg",
    );
    return this.post<Schemas["MediaAsset"]>(
      "/api/v1/media",
      form,
      uid("media"),
      signal,
    );
  }
  mediaURL(url: string) {
    const parsed = new URL(url, window.location.origin);
    if (
      !["http:", "https:"].includes(parsed.protocol) ||
      !/^\/api\/v1\/media\/[^/]+\/content$/.test(parsed.pathname)
    )
      throw new Error("媒体地址无效，请重新获取。");
    // Tickets are host-independent. Route through the same-origin proxy so a
    // phone never tries to contact the backend's 127.0.0.1 address.
    return this.base + parsed.pathname + parsed.search;
  }
  async media(id: string, signal?: AbortSignal) {
    const asset = await this.get<Schemas["MediaAsset"]>(
      `/api/v1/media/${encodeURIComponent(id)}`,
      signal,
    );
    return this.mediaURL(asset.content_url);
  }
}

export function query(
  values: Record<string, string | number | boolean | undefined>,
) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined) params.set(key, String(value));
  });
  return params.size ? `?${params}` : "";
}
export const elderPath = (id: string, suffix: string) =>
  `/api/v1/elders/${encodeURIComponent(id)}/${suffix}`;
export const localDay = (timestamp = Date.now()) =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Hong_Kong",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(timestamp);
export const displayDay = (day: string) =>
  new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "long",
    timeZone: "Asia/Hong_Kong",
  }).format(new Date(`${day}T12:00:00+08:00`));

/** Keep a write key for the SAME payload across transport retries. */
export class WriteKey {
  private value: { fingerprint: string; key: string } | null = null;
  for(path: string, body: unknown) {
    const fingerprint = path + JSON.stringify(body);
    if (this.value?.fingerprint !== fingerprint)
      this.value = { fingerprint, key: uid("write") };
    return this.value.key;
  }
  reset() {
    this.value = null;
  }
}
