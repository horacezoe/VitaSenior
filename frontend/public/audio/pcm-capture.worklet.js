class VitaSeniorPcm extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(2048);
    this.offset = 0;
    this.port.onmessage = (event) => {
      if (event.data === "flush") {
        if (this.offset) {
          const remaining = this.buffer.slice(0, this.offset);
          this.port.postMessage(remaining.buffer, [remaining.buffer]);
          this.offset = 0;
        }
        this.port.postMessage({ flushed: true });
      }
    };
  }
  process(inputs, outputs) {
    for (const channel of outputs[0] || []) channel.fill(0);
    const input = inputs[0]?.[0];
    if (!input) return true;
    for (const value of input) {
      this.buffer[this.offset++] = value;
      if (this.offset === this.buffer.length) {
        this.port.postMessage(this.buffer.buffer, [this.buffer.buffer]);
        this.buffer = new Float32Array(2048);
        this.offset = 0;
      }
    }
    return true;
  }
}
registerProcessor("vitasenior-pcm", VitaSeniorPcm);
