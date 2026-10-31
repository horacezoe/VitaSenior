import { afterEach, expect, it, vi } from "vitest";
import { PcmRecorder } from "../src/media/pcm";

class ContextSubstitute {
  state: "running" | "suspended" | "closed" = "suspended";
  sampleRate = 16000;
  destination = {};
  audioWorklet: { addModule(): Promise<void> } | undefined;
  source = { connect: vi.fn(), disconnect: vi.fn() };
  processor = {
    connect: vi.fn(),
    disconnect: vi.fn(),
    onaudioprocess: null as ((event: AudioProcessingEvent) => void) | null,
  };
  gain = { connect: vi.fn(), disconnect: vi.fn(), gain: { value: 1 } };
  resume = vi.fn(async () => {
    this.state = "running";
  });
  close = vi.fn(async () => {
    this.state = "closed";
  });
  createMediaStreamSource = vi.fn(() => this.source);
  createScriptProcessor = vi.fn(() => this.processor);
  createGain = vi.fn(() => this.gain);
}
function setup() {
  const context = new ContextSubstitute();
  vi.stubGlobal("AudioContext", function () {
    return context;
  });
  return context;
}
afterEach(() => vi.unstubAllGlobals());
it("never claims to listen while the browser audio context is suspended", async () => {
  const context = setup(),
    recorder = new PcmRecorder(),
    heard = vi.fn();
  context.resume.mockImplementation(async () => {});
  await recorder.start({} as MediaStream, heard);
  expect(recorder.listen()).toBe(false);
  expect(recorder.running).toBe(false);
  context.resume.mockImplementation(async () => {
    context.state = "running";
  });
  await recorder.resume();
  expect(recorder.listen()).toBe(true);
  await recorder.stop();
});
it("pauses audio processing during replies and discards unfinished speech on hangup", async () => {
  const context = setup(),
    recorder = new PcmRecorder(),
    heard = vi.fn();
  await recorder.start({} as MediaStream, heard);
  const push = (value: number, count: number) => {
    for (let i = 0; i < count; i++)
      context.processor.onaudioprocess?.({
        inputBuffer: {
          getChannelData: () => new Float32Array(160).fill(value),
        },
      } as unknown as AudioProcessingEvent);
  };
  recorder.listen();
  push(0.1, 18);
  recorder.pause();
  push(0, 110);
  expect(heard).not.toHaveBeenCalled();
  recorder.listen();
  push(0.1, 18);
  push(0, 110);
  expect(heard).toHaveBeenCalledOnce();
  expect(heard.mock.calls[0][0]).toBeInstanceOf(Blob);
  await recorder.stop();
  expect(context.processor.onaudioprocess).toBeNull();
  expect(context.close).toHaveBeenCalledOnce();
  expect(context.source.disconnect).toHaveBeenCalled();
  expect(recorder.listen()).toBe(false);
});
it("does not reconnect a delayed worklet after hangup", async () => {
  const context = setup(),
    recorder = new PcmRecorder();
  let release!: () => void;
  context.audioWorklet = {
    addModule: () =>
      new Promise<void>((resolve) => {
        release = resolve;
      }),
  };
  const pending = recorder.start({} as MediaStream, vi.fn()),
    rejected = expect(pending).rejects.toMatchObject({ name: "AbortError" });
  await recorder.stop();
  release();
  await rejected;
  expect(context.source.connect).not.toHaveBeenCalled();
  expect(context.createGain).not.toHaveBeenCalled();
});
it("retains an explicit audio-unlock failure for recovery instead of pretending to record", async () => {
  const context = setup(),
    recorder = new PcmRecorder();
  const blocked = new DOMException("gesture needed", "NotAllowedError");
  context.resume.mockRejectedValue(blocked);
  await recorder.start({} as MediaStream, vi.fn());
  expect(recorder.listen()).toBe(false);
  expect(recorder.startError).toBe(blocked);
  await recorder.stop();
});
