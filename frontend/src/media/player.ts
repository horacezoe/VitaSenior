import type { Api } from "../api/client";

export class SpeechPlayer {
  readonly audio: HTMLAudioElement;
  private cancel: (() => void) | null = null;
  private generation = 0;
  private cached: { id: string; url: string; at: number } | null = null;
  constructor(audio = new Audio()) {
    this.audio = audio;
    this.audio.preload = "auto";
  }
  async preload(api: Api, id: string, signal?: AbortSignal) {
    this.cached = { id, url: await api.media(id, signal), at: Date.now() };
  }
  async play(api: Api, assetId: string, signal?: AbortSignal): Promise<void> {
    this.stop();
    const generation = this.generation;
    const url =
      this.cached?.id === assetId && Date.now() - this.cached.at < 120000
        ? this.cached.url
        : await api.media(assetId, signal);
    this.cached = { id: assetId, url, at: Date.now() };
    if (signal?.aborted || generation !== this.generation)
      throw new DOMException("已结束", "AbortError");
    const audio = this.audio;
    audio.src = url;
    audio.muted = false;
    audio.volume = 1;
    return new Promise<void>((resolve, reject) => {
      const cleanup = () => {
        if (this.cancel === aborted) {
          audio.onended = audio.onerror = null;
          this.cancel = null;
        }
        signal?.removeEventListener("abort", aborted);
        clearTimeout(timeout);
      };
      const aborted = () => {
        cleanup();
        audio.pause();
        reject(new DOMException("已结束", "AbortError"));
      };
      this.cancel = aborted;
      const timeout = setTimeout(() => {
        cleanup();
        audio.pause();
        reject(new Error("播放时间过长，请重新接听。"));
      }, 200000);
      signal?.addEventListener("abort", aborted, { once: true });
      audio.onended = () => {
        const complete =
          !audio.muted &&
          audio.volume > 0 &&
          Number.isFinite(audio.duration) &&
          audio.duration > 0 &&
          audio.currentTime >= audio.duration - 0.2;
        cleanup();
        complete
          ? resolve()
          : reject(new Error("语音没有完整播放，请重新接听。"));
      };
      audio.onerror = () => {
        cleanup();
        reject(new Error("语音暂时无法播放，请重新获取。"));
      };
      audio.play().catch((error) => {
        cleanup();
        reject(error);
      });
    });
  }
  stop() {
    this.generation++;
    this.cancel?.();
    this.cancel = null;
    this.audio.pause();
    this.audio.removeAttribute("src");
    this.audio.load();
  }
}
