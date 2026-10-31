import { afterEach, expect, it, vi } from "vitest";
import { SpeechPlayer } from "../src/media/player";
import type { Api } from "../src/api/client";

class AudioSubstitute {
  src = "";
  muted = false;
  volume = 1;
  duration = 2;
  currentTime = 0;
  preload = "";
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  play = vi.fn().mockResolvedValue(undefined);
  pause = vi.fn();
  load = vi.fn();
  removeAttribute(name: string) {
    if (name === "src") this.src = "";
  }
}
const api = () =>
  ({
    media: vi
      .fn()
      .mockResolvedValue("/api/v1/media/test/content?ticket=test-only"),
  }) as unknown as Api;
afterEach(() => vi.useRealTimers());
it("only resolves on an actual complete ended event", async () => {
  const audio = new AudioSubstitute(),
    player = new SpeechPlayer(audio as unknown as HTMLAudioElement);
  let ended = false;
  const promise = player.play(api(), "test").then(() => {
    ended = true;
  });
  await vi.waitFor(() => expect(audio.onended).not.toBeNull());
  expect(ended).toBe(false);
  audio.currentTime = 2;
  audio.onended!();
  await promise;
  expect(ended).toBe(true);
});
it.each(["early", "muted", "zero-volume"])(
  "does not attest complete playback for %s",
  async (mode) => {
    const audio = new AudioSubstitute(),
      player = new SpeechPlayer(audio as unknown as HTMLAudioElement);
    const promise = player.play(api(), "test");
    const rejected = expect(promise).rejects.toThrow("没有完整播放");
    await vi.waitFor(() => expect(audio.onended).not.toBeNull());
    audio.currentTime = mode === "early" ? 0.2 : 2;
    audio.muted = mode === "muted";
    audio.volume = mode === "zero-volume" ? 0 : 1;
    audio.onended!();
    await rejected;
  },
);
it("hangup rejects playback, clears handlers and cannot produce an ended receipt later", async () => {
  const audio = new AudioSubstitute(),
    player = new SpeechPlayer(audio as unknown as HTMLAudioElement);
  const promise = player.play(api(), "test");
  const rejected = expect(promise).rejects.toMatchObject({
    name: "AbortError",
  });
  await vi.waitFor(() => expect(audio.onended).not.toBeNull());
  player.stop();
  await rejected;
  expect(audio.onended).toBeNull();
  expect(audio.src).toBe("");
  expect(audio.pause).toHaveBeenCalled();
});
it("a resolved media lookup cannot restart audio after hangup", async () => {
  let release!: (value: string) => void;
  const transport = {
    media: () =>
      new Promise<string>((resolve) => {
        release = resolve;
      }),
  } as unknown as Api;
  const audio = new AudioSubstitute(),
    player = new SpeechPlayer(audio as unknown as HTMLAudioElement);
  const pending = player.play(transport, "test"),
    rejected = expect(pending).rejects.toMatchObject({ name: "AbortError" });
  player.stop();
  release("/media");
  await rejected;
  expect(audio.play).not.toHaveBeenCalled();
});
it("a preloaded source starts within the answer gesture without another lookup", async () => {
  const transport = api(),
    audio = new AudioSubstitute(),
    player = new SpeechPlayer(audio as unknown as HTMLAudioElement);
  await player.preload(transport, "test");
  const pending = player.play(transport, "test");
  expect(audio.play).toHaveBeenCalledOnce();
  expect(transport.media).toHaveBeenCalledOnce();
  audio.currentTime = 2;
  audio.onended!();
  await pending;
});
it("a late rejection from an interrupted native play cannot erase the next playback handlers", async () => {
  const transport = api(),
    audio = new AudioSubstitute(),
    player = new SpeechPlayer(audio as unknown as HTMLAudioElement);
  let rejectOld!: (error: Error) => void;
  audio.play.mockImplementationOnce(
    () =>
      new Promise((_resolve, reject) => {
        rejectOld = reject;
      }),
  );
  await player.preload(transport, "test");
  const first = player.play(transport, "test"),
    cancelled = expect(first).rejects.toMatchObject({ name: "AbortError" });
  player.stop();
  await cancelled;
  const second = player.play(transport, "test");
  rejectOld(new DOMException("old source removed", "AbortError"));
  await Promise.resolve();
  expect(audio.onended).not.toBeNull();
  audio.currentTime = 2;
  audio.onended!();
  await second;
});
