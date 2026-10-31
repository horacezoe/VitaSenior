import { useEffect, useRef, useState, useMemo } from "react";
import { Button, ErrorNotice } from "./ui";
import { SpeechPlayer } from "../media/player";
import { useSession } from "../state/session";
import { uid, type Schemas } from "../api/client";
export default function ReportSpeech({ text }: { text: string }) {
  const { api, elderId } = useSession(),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  const player = useRef(new SpeechPlayer()),
    abort = useRef(new AbortController()),
    key = useMemo(() => uid("report-speech"), [text, elderId]);
  useEffect(
    () => () => {
      abort.current.abort();
      player.current.stop();
    },
    [],
  );
  return (
    <>
      <Button
        disabled={busy}
        onClick={() => {
          setBusy(true);
          setError(null);
          void api
            .post<Schemas["TTSResult"]>(
              "/api/v1/ai/tts",
              { elder_id: elderId!, text },
              key,
              abort.current.signal,
            )
            .then((r) =>
              player.current.play(
                api,
                r.audio_asset.asset_id,
                abort.current.signal,
              ),
            )
            .catch(setError)
            .finally(() => setBusy(false));
        }}
      >
        {busy ? "正在播报…" : "听小银龄读一读"}
      </Button>
      <ErrorNotice error={error} />
    </>
  );
}
