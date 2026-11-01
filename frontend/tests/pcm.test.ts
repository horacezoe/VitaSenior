import { describe, expect, it, vi } from "vitest";
import {
  cameraFrame,
  encodeWav,
  resample,
  VoiceSegmenter,
} from "../src/media/pcm";

describe("actual PCM WAV encoding", () => {
  it("writes a complete mono 16-bit RIFF container with correct byte length", async () => {
    const blob = encodeWav(new Float32Array([-2, -1, 0, 1, 2, NaN]), 16000);
    const view = new DataView(await blob.arrayBuffer());
    expect(blob.type).toBe("audio/wav");
    expect(blob.size).toBe(56);
    expect(new TextDecoder().decode(new Uint8Array(view.buffer, 0, 4))).toBe(
      "RIFF",
    );
    expect(new TextDecoder().decode(new Uint8Array(view.buffer, 8, 4))).toBe(
      "WAVE",
    );
    expect(view.getUint32(4, true) + 8).toBe(blob.size);
    expect(view.getUint16(20, true)).toBe(1);
    expect(view.getUint16(22, true)).toBe(1);
    expect(view.getUint32(24, true)).toBe(16000);
    expect(view.getUint16(34, true)).toBe(16);
    expect(view.getUint32(40, true)).toBe(12);
    expect(
      [0, 1, 2, 3, 4, 5].map((i) => view.getInt16(44 + i * 2, true)),
    ).toEqual([-32768, -32768, 0, 32767, 32767, 0]);
  });
  it("resamples 48kHz capture to exactly one second at 16kHz", () => {
    const output = resample(new Float32Array(48000).fill(0.4), 48000);
    expect(output.length).toBe(16000);
    expect(output[300]).toBeCloseTo(0.4);
    expect(encodeWav(output, 16000).size).toBe(32044);
  });
  it("rejects invalid sampling metadata and does not invent a missing camera frame", async () => {
    expect(() => encodeWav(new Float32Array(), 1)).toThrow();
    expect(await cameraFrame(null)).toBeNull();
  });
  it("uploads the complete camera frame with the original aspect ratio", async () => {
    const drawImage = vi.fn();
    const canvas = { width: 0, height: 0, getContext: () => ({ drawImage }),
      toBlob: (resolve: (value: Blob) => void) => resolve(new Blob(["frame"])) };
    vi.stubGlobal("document", { createElement: () => canvas });
    try {
      const camera = { videoWidth: 1920, videoHeight: 1080, readyState: 2 } as HTMLVideoElement;
      expect(await cameraFrame(camera)).toBeInstanceOf(Blob);
      expect(canvas.width).toBe(800);
      expect(canvas.height).toBe(450);
      expect(drawImage).toHaveBeenCalledWith(camera, 0, 0, 800, 450);
    } finally { vi.unstubAllGlobals(); }
  });
});

describe("hands-free sentence boundaries", () => {
  const frame = (volume: number) => new Float32Array(1600).fill(volume);
  it("does not submit silence or a short click", () => {
    const turns: Float32Array[] = [],
      vad = new VoiceSegmenter(16000, (samples) => turns.push(samples));
    for (let i = 0; i < 15; i++) vad.push(frame(0));
    vad.push(frame(0.5));
    for (let i = 0; i < 15; i++) vad.push(frame(0));
    expect(turns).toHaveLength(0);
  });
  it("produces one complete utterance after speech and the trailing silence", () => {
    const turns: Float32Array[] = [],
      vad = new VoiceSegmenter(16000, (samples) => turns.push(samples));
    for (let i = 0; i < 12; i++) vad.push(frame(0.2));
    for (let i = 0; i < 9; i++) vad.push(frame(0));
    expect(turns).toHaveLength(0);
    vad.push(frame(0));
    expect(turns).toHaveLength(1);
    expect(turns[0].some((value) => value > 0.1)).toBe(true);
    for (let i = 0; i < 30; i++) vad.push(frame(0));
    expect(turns).toHaveLength(1);
  });
  it("reset discards an unfinished utterance so paused playback cannot complete it", () => {
    const turns: Float32Array[] = [],
      vad = new VoiceSegmenter(16000, (samples) => turns.push(samples));
    for (let i = 0; i < 8; i++) vad.push(frame(0.2));
    vad.reset();
    for (let i = 0; i < 12; i++) vad.push(frame(0));
    expect(turns).toHaveLength(0);
  });
  it("bounds a continuously speaking turn without losing the PCM payload", () => {
    const turns: Float32Array[] = [],
      vad = new VoiceSegmenter(16000, (samples) => turns.push(samples));
    for (let i = 0; i < 225; i++) vad.push(frame(0.2));
    expect(turns).toHaveLength(1);
    expect(turns[0].length / 16000).toBeLessThanOrEqual(22.2);
  });
});
