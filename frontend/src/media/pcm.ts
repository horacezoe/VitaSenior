export function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  if (!Number.isInteger(sampleRate) || sampleRate < 8000 || sampleRate > 96000)
    throw new Error("录音采样率不受支持。");
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const text = (offset: number, value: string) =>
    [...value].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  text(0, "RIFF");
  view.setUint32(4, buffer.byteLength - 8, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, samples.length * 2, true);
  samples.forEach((sample, i) => {
    const n = Number.isFinite(sample) ? Math.max(-1, Math.min(1, sample)) : 0;
    view.setInt16(44 + i * 2, Math.round(n < 0 ? n * 32768 : n * 32767), true);
  });
  return new Blob([buffer], { type: "audio/wav" });
}

export function resample(samples: Float32Array, from: number, to = 16000) {
  if (from === to) return samples;
  const ratio = from / to,
    result = new Float32Array(Math.floor(samples.length / ratio));
  for (let i = 0; i < result.length; i++) {
    const start = Math.floor(i * ratio),
      end = Math.max(start + 1, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < Math.min(end, samples.length); j++)
      sum += samples[j];
    result[i] = sum / (Math.min(end, samples.length) - start);
  }
  return result;
}

export class VoiceSegmenter {
  private pre: Float32Array[] = [];
  private frames: Float32Array[] = [];
  private preMs = 0;
  private voiceMs = 0;
  private silenceMs = 0;
  private totalMs = 0;
  private active = false;
  private noise = 0.002;
  constructor(
    private rate: number,
    private utterance: (samples: Float32Array) => void,
    private level?: (value: number) => void,
  ) {}
  reset() {
    this.pre = [];
    this.frames = [];
    this.preMs = this.voiceMs = this.silenceMs = this.totalMs = 0;
    this.active = false;
  }
  push(samples: Float32Array) {
    const ms = (samples.length / this.rate) * 1000;
    const rms = Math.sqrt(
      samples.reduce((sum, v) => sum + v * v, 0) / samples.length,
    );
    this.level?.(Math.min(1, rms * 10));
    const loud = rms > Math.max(0.009, this.noise * 2.8);
    if (!this.active) {
      this.pre.push(samples);
      this.preMs += ms;
      while (this.preMs > 350 && this.pre.length > 1)
        this.preMs -= (this.pre.shift()!.length / this.rate) * 1000;
      this.voiceMs = loud ? this.voiceMs + ms : 0;
      if (!loud) this.noise = 0.97 * this.noise + 0.03 * Math.min(rms, 0.02);
      if (this.voiceMs < 160) return;
      this.active = true;
      this.frames = [...this.pre];
      this.totalMs = this.preMs;
      this.pre = [];
      return;
    }
    this.frames.push(samples);
    this.totalMs += ms;
    this.silenceMs = loud ? 0 : this.silenceMs + ms;
    if (this.silenceMs >= 1000 || this.totalMs >= 22000) {
      const result = new Float32Array(
        this.frames.reduce((sum, frame) => sum + frame.length, 0),
      );
      let offset = 0;
      this.frames.forEach((frame) => {
        result.set(frame, offset);
        offset += frame.length;
      });
      this.reset();
      this.utterance(result);
    }
  }
}

export class PcmRecorder {
  private context: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private processor: AudioWorkletNode | ScriptProcessorNode | null = null;
  private gain: GainNode | null = null;
  private segmenter: VoiceSegmenter | null = null;
  private enabled = false;
  private unlockFailure: unknown = null;
  get startError() {
    return this.unlockFailure;
  }
  get configured() {
    return !!this.processor;
  }
  get running() {
    return this.context?.state === "running";
  }
  prepare() {
    this.context ||= new AudioContext();
    this.unlockFailure = null;
    void this.context.resume().catch((error) => {
      this.unlockFailure = error;
    });
  }
  async resume() {
    if (!this.context || !this.configured)
      throw new Error("录音尚未就绪，请重新进入通话。");
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        this.context.resume(),
        new Promise<never>((_, reject) => {
          timer = setTimeout(
            () => reject(new Error("麦克风尚未开始，请再点一下继续聆听。")),
            2000,
          );
        }),
      ]);
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
  async start(
    stream: MediaStream,
    utterance: (wav: Blob) => void,
    level?: (value: number) => void,
  ) {
    if (!this.context) this.prepare();
    const context = this.context!,
      rate = context.sampleRate;
    this.segmenter = new VoiceSegmenter(
      rate,
      (samples) => utterance(encodeWav(resample(samples, rate), 16000)),
      level,
    );
    this.source = context.createMediaStreamSource(stream);
    if (context.audioWorklet) {
      await context.audioWorklet.addModule("/audio/pcm-capture.worklet.js");
      if (this.context !== context || context.state === "closed")
        throw new DOMException("录音已停止", "AbortError");
      const node = new AudioWorkletNode(context, "vitasenior-pcm");
      node.port.onmessage = (event) => {
        if (this.enabled) this.segmenter?.push(new Float32Array(event.data));
      };
      this.processor = node;
    } else {
      const node = context.createScriptProcessor(2048, 1, 1);
      node.onaudioprocess = (event) => {
        if (this.enabled)
          this.segmenter?.push(
            new Float32Array(event.inputBuffer.getChannelData(0)),
          );
      };
      this.processor = node;
    }
    this.gain = context.createGain();
    this.gain.gain.value = 0;
    this.source.connect(this.processor);
    this.processor.connect(this.gain);
    this.gain.connect(context.destination);
  }
  listen() {
    if (!this.running || !this.configured) return false;
    this.segmenter?.reset();
    this.enabled = true;
    return true;
  }
  pause() {
    this.enabled = false;
    this.segmenter?.reset();
  }
  async stop() {
    this.pause();
    this.source?.disconnect();
    this.processor?.disconnect();
    this.gain?.disconnect();
    if (
      typeof AudioWorkletNode !== "undefined" &&
      this.processor instanceof AudioWorkletNode
    ) {
      this.processor.port.onmessage = null;
      this.processor.port.close();
    }
    if (this.processor && "onaudioprocess" in this.processor)
      this.processor.onaudioprocess = null;
    this.processor = null;
    this.source = null;
    this.gain = null;
    this.segmenter = null;
    const context = this.context;
    this.context = null;
    if (context && context.state !== "closed") await context.close();
  }
}

export async function cameraFrame(
  video: HTMLVideoElement | null,
): Promise<Blob | null> {
  if (!video || !video.videoWidth || video.readyState < 2) return null;
  const canvas = document.createElement("canvas"),
    ratio = Math.min(1, 800 / video.videoWidth);
  canvas.width = Math.round(video.videoWidth * ratio);
  canvas.height = Math.round(video.videoHeight * ratio);
  const context = canvas.getContext("2d");
  if (!context) return null;
  context.drawImage(video, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.72));
}
