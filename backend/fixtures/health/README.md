# Health demo reminder audio

Four fixed, genuine Chinese speech WAVs. `templates.json` is the exact text shown
to the user; `audio_manifest.json` records the text, SHA-256, producer and is_mock.
The spoken content includes “模拟”. No tones or unrelated speech stand in for text.

Reproduce on Windows with Microsoft Huihui Desktop installed:

```powershell
powershell.exe -NoProfile -File backend/fixtures/health/generate_audio.ps1
```

This script runs only during fixture preparation. The server uses the checked-in
bytes and does not require SAPI, a provider key, or a network connection. All audio
reads happen outside the database write transaction. The authenticated write uses
A's MediaPort to persist a voice message scoped to the intended elder.

NOTI04 prioritizes an explicitly supplied, uploader-owned recording, copying the
controlled media bytes to the target household through A's port. Otherwise it uses
an exact-text preset when available. Arbitrary unmatched text is preserved as a
text-only reminder (`audio_asset_id=null`); it never receives unrelated audio.

These fixtures do not narrate medication/profile change proposals. A owns that
announcement preparation and must narrate the actual change before auto-apply can
be enabled. This is why NOTI03 is still held out of B's production declarations.
