import { afterEach, expect, it, vi } from "vitest";
import { WavMessageRecorder } from "../src/media/message";

function setup() {
  const track = { stop: vi.fn() },
    stream = { getTracks: () => [track] } as unknown as MediaStream;
  const media = vi.fn().mockResolvedValue(stream);
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia: media } });
  const node = { connect: vi.fn(), disconnect: vi.fn() };
  const context = {
    state: "running",
    sampleRate: 16000,
    destination: {},
    resume: vi.fn().mockResolvedValue(undefined),
    close: vi.fn(async () => {
      context.state = "closed";
    }),
    audioWorklet: { addModule: vi.fn().mockResolvedValue(undefined) },
    createMediaStreamSource: vi.fn(() => node),
    createGain: vi.fn(() => ({ ...node, gain: { value: 1 } })),
  };
  const port = {
    onmessage: null as ((event: { data: unknown }) => void) | null,
    close: vi.fn(),
    postMessage: vi.fn(() => {
      port.onmessage?.({ data: { flushed: true } });
    }),
  };
  vi.stubGlobal("AudioContext", function () {
    return context;
  });
  vi.stubGlobal("AudioWorkletNode", function () {
    return { ...node, port };
  });
  return { track, stream, media, node, context, port };
}
afterEach(() => vi.unstubAllGlobals());
it("stops a late permission result instead of reconnecting the microphone after leaving", async () => {
  const mock = setup(),
    recorder = new WavMessageRecorder();
  let release!: (value: MediaStream) => void;
  mock.media.mockImplementation(
    () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  );
  const pending = recorder.start(),
    rejected = expect(pending).rejects.toMatchObject({ name: "AbortError" });
  await vi.waitFor(() => expect(mock.media).toHaveBeenCalledOnce());
  await recorder.stop();
  release(mock.stream);
  await rejected;
  expect(mock.track.stop).toHaveBeenCalledOnce();
  expect(mock.context.createMediaStreamSource).not.toHaveBeenCalled();
});
it("flushes the real PCM tail before encoding and releases every recording resource", async () => {
  const mock = setup(),
    recorder = new WavMessageRecorder();
  await recorder.start();
  mock.port.onmessage!({ data: new Float32Array(32000).fill(0.1).buffer });
  const wav = await recorder.finish(),
    bytes = await wav.arrayBuffer();
  expect(wav.type).toBe("audio/wav");
  expect(bytes.byteLength).toBe(44 + 32000 * 2);
  expect(new DataView(bytes).getUint32(24, true)).toBe(16000);
  expect(mock.context.close).toHaveBeenCalledOnce();
  expect(mock.track.stop).toHaveBeenCalledOnce();
  expect(mock.port.onmessage).toBeNull();
});
it("cancels an outstanding flush immediately when recording is stopped", async () => {
  const mock = setup(),
    recorder = new WavMessageRecorder();
  await recorder.start();
  mock.port.postMessage.mockImplementation(() => {});
  const pending = recorder.finish(),
    rejected = expect(pending).rejects.toMatchObject({ name: "AbortError" });
  await recorder.stop();
  await rejected;
  expect(mock.port.close).toHaveBeenCalledOnce();
});
it("bounds message output to sixty seconds even when a timer is delayed", async () => {
  const mock = setup(),
    recorder = new WavMessageRecorder();
  await recorder.start();
  mock.port.onmessage!({ data: new Float32Array(16000 * 61).buffer });
  const wav = await recorder.finish();
  expect(wav.size).toBe(44 + 16000 * 60 * 2);
});
