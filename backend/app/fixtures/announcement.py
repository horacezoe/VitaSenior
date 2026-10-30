"""Deterministic demo announcement audio (a local cue, not a TTS provider call).

The flow renders this OUTSIDE the write transaction and only registers the bytes
in-tx, so no provider work ever sits inside BEGIN IMMEDIATE. It exists so the F1
proposal window can be exercised end to end (playback receipt -> mark_played):
the content is a short synthetic cue rather than speech. Real speech comes from
C's TTS provider, which replaces this call site without touching the transaction
shape.
"""
import io
import math
import struct
import wave

from app.contracts.media import GeneratedAudio

SAMPLE_RATE = 8000
CUE_SECONDS = 0.8
ANNOUNCEMENT_TEXT = "请听取本次修改，如不同意可以拒绝。"

def render_announcement(text: str) -> GeneratedAudio:
    """Return an 8 kHz mono PCM WAV cue; identical input gives identical bytes."""
    frames = int(SAMPLE_RATE * CUE_SECONDS)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        samples = bytearray()
        for index in range(frames):
            # Two short tones separated by a pause: unmistakably a demo cue.
            phase = index / SAMPLE_RATE
            active = 0.08 <= phase < 0.32 or 0.42 <= phase < 0.72
            frequency = 660 if phase < 0.32 else 880
            amplitude = 6000 if active else 0
            value = int(amplitude * math.sin(2 * math.pi * frequency * phase)) if active else 0
            samples += struct.pack("<h", value)
        out.writeframes(bytes(samples))
    return GeneratedAudio(content=buffer.getvalue(), mime_type="audio/wav",
                          duration_ms=int(CUE_SECONDS * 1000))
