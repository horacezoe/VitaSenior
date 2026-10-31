import { expect, it, vi } from "vitest";
import { sendVoiceTurn, type VoiceJob } from "../src/media/turn";
import type { Api, Schemas } from "../src/api/client";

const asset = (id: string) => ({
  asset_id: id,
  purpose: "voice_message",
  mime_type: "audio/wav",
  size_bytes: 100,
  duration_ms: 1000,
  content_url:
    "http://local/api/v1/media/test/content?ticket=explicit-test-ticket",
  expires_at: "2026-10-31T05:00:00Z",
});
const result: Schemas["AgentTurn"] = {
  turn_id: "turn",
  conversation_id: "conversation",
  transcript: "确认。",
  reply: { text: "已确认" },
  scene: "clarify",
  avatar_state: "idle",
  actions: [],
  memory: { version: 1, changed: false },
  providers: { chat: "not_used", asr: "real", tts: "not_used" },
  degraded: ["tts_unavailable"],
};
const job = (): VoiceJob => ({
  id: "stable-client-turn",
  audio: new Blob(["test-only-audio"]),
  frame: new Blob(["test-only-image"]),
});
it("serially uploads PCM and one frame, preserving explicit control context", async () => {
  const upload = vi
    .fn()
    .mockResolvedValueOnce(asset("voice"))
    .mockResolvedValueOnce(asset("frame"));
  const post = vi.fn().mockResolvedValue(result),
    current = job();
  await sendVoiceTurn(
    { upload, post } as unknown as Api,
    "elder",
    current,
    {
      conversationId: "existing",
      pendingActionId: "owned-action",
      notificationId: "owned-notice",
    },
    new AbortController().signal,
    () => {},
  );
  expect(upload).toHaveBeenCalledTimes(2);
  expect(post.mock.calls[0][1]).toEqual({
    elder_id: "elder",
    client_turn_id: "stable-client-turn",
    conversation_id: "existing",
    audio_asset_id: "voice",
    image_asset_ids: ["frame"],
    context: {
      pending_action_id: "owned-action",
      notification_id: "owned-notice",
    },
  });
  expect(post.mock.calls[0][2]).toBe("stable-client-turn");
});
it("a network retry reuses assets, exact body, client turn ID and idempotency key", async () => {
  const upload = vi
    .fn()
    .mockResolvedValueOnce(asset("voice"))
    .mockResolvedValueOnce(asset("frame"));
  const post = vi
    .fn()
    .mockRejectedValueOnce(new Error("uncertain network result"))
    .mockResolvedValue(result);
  const transport = { upload, post } as unknown as Api,
    current = job(),
    signal = new AbortController().signal;
  await expect(
    sendVoiceTurn(
      transport,
      "elder",
      current,
      { conversationId: "original" },
      signal,
      () => {},
    ),
  ).rejects.toThrow();
  await sendVoiceTurn(
    transport,
    "elder",
    current,
    { conversationId: "changed-by-later-render" },
    signal,
    () => {},
  );
  expect(upload).toHaveBeenCalledTimes(2);
  expect(post.mock.calls[1][1]).toEqual(post.mock.calls[0][1]);
  expect(post.mock.calls[1][2]).toBe(post.mock.calls[0][2]);
  await sendVoiceTurn(transport, "elder", current, {}, signal, () => {});
  expect(post).toHaveBeenCalledTimes(2);
});
it("hangup during an upload prevents later frame uploads and turn submissions", async () => {
  let active = true;
  const upload = vi.fn().mockImplementation(async () => {
      active = false;
      return asset("voice");
    }),
    post = vi.fn();
  const guard = () => {
    if (!active) throw new DOMException("hung up", "AbortError");
  };
  await expect(
    sendVoiceTurn(
      { upload, post } as unknown as Api,
      "elder",
      job(),
      {},
      new AbortController().signal,
      guard,
    ),
  ).rejects.toMatchObject({ name: "AbortError" });
  expect(upload).toHaveBeenCalledTimes(1);
  expect(post).not.toHaveBeenCalled();
});
it("hangup after the frame upload still prevents a business turn", async () => {
  let active = true,
    count = 0;
  const upload = vi.fn().mockImplementation(async () => {
      if (++count === 2) active = false;
      return asset(String(count));
    }),
    post = vi.fn();
  await expect(
    sendVoiceTurn(
      { upload, post } as unknown as Api,
      "elder",
      job(),
      {},
      new AbortController().signal,
      () => {
        if (!active) throw new DOMException("hung up", "AbortError");
      },
    ),
  ).rejects.toMatchObject({ name: "AbortError" });
  expect(post).not.toHaveBeenCalled();
});
it("audio-only fallback sends an empty image list rather than inventing a frame", async () => {
  const upload = vi.fn().mockResolvedValue(asset("voice")),
    post = vi.fn().mockResolvedValue(result);
  await sendVoiceTurn(
    { upload, post } as unknown as Api,
    "elder",
    { ...job(), frame: null },
    {},
    new AbortController().signal,
    () => {},
  );
  expect(upload).toHaveBeenCalledTimes(1);
  expect(post.mock.calls[0][1].image_asset_ids).toEqual([]);
});
