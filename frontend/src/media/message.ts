import { encodeWav, resample } from "./pcm";

/** Explicit start/stop family voice message, recorded as PCM WAV. */
export class WavMessageRecorder {
  private context: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private processor: AudioWorkletNode | null = null;
  private chunks: Float32Array[] = [];
  private flushed: (() => void) | null = null;
  private cancelFlush: (() => void) | null = null;
  private gain: GainNode | null = null;
  private totalSamples = 0;
  private ensureActive(context: AudioContext) {
    if (context !== this.context || context.state === "closed")
      throw new DOMException("录音已停止", "AbortError");
  }
  async start() {
    if (
      !navigator.mediaDevices?.getUserMedia ||
      typeof AudioContext === "undefined"
    )
      throw new Error("录音留言需要安全连接和麦克风，也可以先用文字关怀。");
    const context = new AudioContext();
    this.context = context;
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        context.resume(),
        new Promise<never>((_, reject) => {
          timer = setTimeout(
            () => reject(new Error("录音尚未开始，请再点一次开始录音。")),
            2000,
          );
        }),
      ]);
    } finally {
      if (timer) clearTimeout(timer);
    }
    this.ensureActive(context);
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
      },
    });
    if (context !== this.context || context.state === "closed") {
      stream.getTracks().forEach((track) => track.stop());
      throw new DOMException("录音已停止", "AbortError");
    }
    this.stream = stream;
    if (!context.audioWorklet || typeof AudioWorkletNode === "undefined")
      throw new Error("当前浏览器无法录制完整语音留言，请改用文字关怀。");
    await context.audioWorklet.addModule("/audio/pcm-capture.worklet.js");
    this.ensureActive(context);
    this.source = context.createMediaStreamSource(stream);
    this.processor = new AudioWorkletNode(context, "vitasenior-pcm");
    this.processor.port.onmessage = (event) => {
      if (this.context !== context) return;
      if (event.data?.flushed) this.flushed?.();
      else {
        const chunk = new Float32Array(event.data),
          remaining = Math.max(0, context.sampleRate * 60 - this.totalSamples);
        if (remaining) {
          const bounded =
            chunk.length > remaining ? chunk.slice(0, remaining) : chunk;
          this.chunks.push(bounded);
          this.totalSamples += bounded.length;
        }
      }
    };
    const gain = context.createGain();
    this.gain = gain;
    gain.gain.value = 0;
    this.source.connect(this.processor);
    this.processor.connect(gain);
    gain.connect(context.destination);
  }
  async finish() {
    const context = this.context;
    if (!context || !this.processor) throw new Error("请先录制一段留言。");
    try {
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(
          () => reject(new Error("录音未能完整结束，请重新录制。")),
          2000,
        );
        this.flushed = () => {
          clearTimeout(timer);
          this.flushed = this.cancelFlush = null;
          resolve();
        };
        this.cancelFlush = () => {
          clearTimeout(timer);
          this.flushed = this.cancelFlush = null;
          reject(new DOMException("录音已停止", "AbortError"));
        };
        this.processor!.port.postMessage("flush");
      });
      this.ensureActive(context);
      const all = new Float32Array(
        this.chunks.reduce((sum, chunk) => sum + chunk.length, 0),
      );
      let offset = 0;
      this.chunks.forEach((chunk) => {
        all.set(chunk, offset);
        offset += chunk.length;
      });
      if (!all.length) throw new Error("没有录到有效音频，请重新录制。");
      return encodeWav(resample(all, context.sampleRate), 16000);
    } finally {
      await this.stop();
    }
  }
  async stop() {
    this.cancelFlush?.();
    this.stream?.getTracks().forEach((track) => track.stop());
    this.source?.disconnect();
    this.processor?.disconnect();
    this.gain?.disconnect();
    if (this.processor) {
      this.processor.port.onmessage = null;
      this.processor.port.close();
    }
    const context = this.context;
    this.context = null;
    this.stream = null;
    this.source = null;
    this.processor = null;
    this.gain = null;
    this.chunks = [];
    this.totalSamples = 0;
    if (context && context.state !== "closed") await context.close();
  }
}
