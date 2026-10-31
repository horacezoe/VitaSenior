import { afterEach, expect, it, vi } from "vitest";
import { ApiError } from "../src/api/client";
import { retryNode } from "../src/media/diagnostics";
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});
it("retries a transient failure once and excludes payloads from diagnostic entries", async () => {
  vi.useFakeTimers();
  const log = vi.spyOn(console, "info").mockImplementation(() => {});
  const action = vi
    .fn()
    .mockRejectedValueOnce(
      new ApiError(
        502,
        "PROVIDER_ERROR",
        "private transcript",
        null,
        true,
        "req-test",
      ),
    )
    .mockResolvedValue("ok");
  const pending = retryNode(
    "turn",
    "agent",
    new AbortController().signal,
    action,
  );
  await vi.runAllTimersAsync();
  expect(await pending).toBe("ok");
  expect(action).toHaveBeenCalledTimes(2);
  const output = JSON.stringify(log.mock.calls);
  expect(output).toContain("req-test");
  expect(output).not.toContain("private transcript");
});
it("does not retry a permission or non-retryable validation failure", async () => {
  for (const status of [403, 422, 502]) {
    const error = new ApiError(status, "VALIDATION_ERROR", "failed"),
      action = vi.fn().mockRejectedValue(error);
    await expect(
      retryNode("turn", "agent", new AbortController().signal, action),
    ).rejects.toBe(error);
    expect(action).toHaveBeenCalledTimes(1);
  }
});
it("hangup during backoff prevents another call", async () => {
  vi.useFakeTimers();
  const abort = new AbortController(),
    action = vi
      .fn()
      .mockRejectedValue(new ApiError(0, "NETWORK_ERROR", "offline"));
  const pending = retryNode("turn", "tts", abort.signal, action);
  const rejected = expect(pending).rejects.toMatchObject({
    name: "AbortError",
  });
  await Promise.resolve();
  abort.abort();
  await rejected;
  await vi.runAllTimersAsync();
  expect(action).toHaveBeenCalledTimes(1);
});
it("caps repeated failures at two attempts", async () => {
  vi.useFakeTimers();
  const error = new ApiError(504, "PROVIDER_TIMEOUT", "slow"),
    action = vi.fn().mockRejectedValue(error);
  const pending = retryNode(
      "turn",
      "agent",
      new AbortController().signal,
      action,
    ),
    rejected = expect(pending).rejects.toBe(error);
  await vi.runAllTimersAsync();
  await rejected;
  expect(action).toHaveBeenCalledTimes(2);
});
