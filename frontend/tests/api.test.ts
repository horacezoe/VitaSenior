import { afterEach, expect, it, vi } from "vitest";
import { Api, ApiError, friendlyError, localDay, query, WriteKey } from "../src/api/client";

afterEach(() => vi.unstubAllGlobals());
it("cancels the media-ticket lookup on hangup rather than leaving a background request", async () => {
  const fetcher = vi.fn(
    (_url: string, init: RequestInit) =>
      new Promise((_resolve, reject) => {
        init.signal!.addEventListener(
          "abort",
          () => reject(init.signal!.reason),
          { once: true },
        );
      }),
  );
  vi.stubGlobal("fetch", fetcher);
  const controller = new AbortController(),
    pending = new Api().media("test", controller.signal);
  const rejected = expect(pending).rejects.toMatchObject({
    name: "AbortError",
  });
  controller.abort();
  await rejected;
  expect(fetcher.mock.calls[0][1].signal!.aborted).toBe(true);
});
it("uses the real envelope and keeps auth out of URLs", async () => {
  const fetcher = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        data: { status: "ok" },
        meta: { server_time: "2026-10-31T04:00:00Z", request_id: "test" },
      }),
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  const api = new Api("", "explicit-test-token");
  expect(await api.get("/api/v1/health")).toEqual({ status: "ok" });
  expect(fetcher.mock.calls[0][0]).toBe("/api/v1/health");
  expect(fetcher.mock.calls[0][1].headers.get("Authorization")).toBe(
    "Bearer explicit-test-token",
  );
  expect(Math.abs(api.now() - Date.parse("2026-10-31T04:00:00Z"))).toBeLessThan(
    100,
  );
});
it("preserves real permission/version errors rather than returning fake data", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: "VERSION_CONFLICT",
            message: "changed",
            details: { current_version: 3 },
            retryable: false,
          },
          meta: { request_id: "request-3" },
        }),
        { status: 409 },
      ),
    ),
  );
  const error = await new Api()
    .put("/profile", { expected_version: 2 })
    .catch((value) => value);
  expect(error).toBeInstanceOf(ApiError);
  expect(error).toMatchObject({
    status: 409,
    code: "VERSION_CONFLICT",
    requestId: "request-3",
    details: { current_version: 3 },
  });
});
it("401 invokes the matching client session callback once", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({ error: { code: "SESSION_EXPIRED" }, meta: {} }),
          { status: 401 },
        ),
      ),
  );
  const expired = vi.fn();
  await expect(
    new Api("", "expired", expired).get("/me"),
  ).rejects.toBeInstanceOf(ApiError);
  expect(expired).toHaveBeenCalledOnce();
});
it("lets the browser create multipart boundaries for genuine uploads", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(
      new Response(
        JSON.stringify({ data: { asset_id: "actual-test-asset" }, meta: {} }),
      ),
    );
  vi.stubGlobal("fetch", fetcher);
  await new Api("", "test-token").upload(
    "elder",
    new Blob(["pcm"], { type: "audio/wav" }),
    "voice_message",
  );
  const init = fetcher.mock.calls[0][1];
  expect(init.headers.has("Content-Type")).toBe(false);
  expect(init.body).toBeInstanceOf(FormData);
  expect(init.body.get("elder_id")).toBe("elder");
  expect(init.body.get("file").name).toBe("speech.wav");
});
it("routes media through the phone-accessible origin and rejects non-media URLs", () => {
  vi.stubGlobal("window", { location: { origin: "https://phone.test" } });
  const api = new Api();
  expect(
    api.mediaURL(
      "http://127.0.0.1:8017/api/v1/media/asset/content?ticket=test-ticket",
    ),
  ).toBe("/api/v1/media/asset/content?ticket=test-ticket");
  expect(() => api.mediaURL("javascript:alert(1)")).toThrow();
  expect(() => api.mediaURL("https://unexpected.test/upload")).toThrow();
});
it("keeps write keys stable for retries and changes them for different payloads", () => {
  const keys = new WriteKey(),
    body = { expected_version: 1, patch: { display_name: "测试" } };
  const first = keys.for("/profile", body);
  expect(keys.for("/profile", structuredClone(body))).toBe(first);
  expect(keys.for("/profile", { ...body, expected_version: 2 })).not.toBe(
    first,
  );
  keys.reset();
  expect(keys.for("/profile", body)).not.toBe(first);
});
it("formats Hong Kong dates and preserves false values and zero in query parameters", () => {
  expect(localDay(Date.parse("2026-10-30T17:00:00Z"))).toBe("2026-10-31");
  expect(query({ active: false, limit: 0, cursor: undefined })).toBe(
    "?active=false&limit=0",
  );
});

it("explains invalid login and expired codes in user-facing language",()=>{
 expect(friendlyError(new ApiError(401,"LOGIN_CODE_INVALID","Only allocated demo accounts may log in"))).toContain("手机号码、身份或验证码不匹配");
 expect(friendlyError(new ApiError(401,"CHALLENGE_EXPIRED","Expired"))).toContain("重新获取");
});
