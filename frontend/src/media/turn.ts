import { retryNode, logNode } from "./diagnostics";
import type { Api, Schemas } from "../api/client";

export type VoiceJob = {
  id: string;
  audio: Blob;
  frame: Blob | null;
  audioId?: string;
  imageId?: string;
  body?: Schemas["AgentTurnWrite"];
  result?: Schemas["AgentTurn"];
  ttsId?: string;
};
type Transport = Pick<Api, "upload" | "post">;
/** A retry keeps the already uploaded assets, body and both idempotency IDs. */
export async function sendVoiceTurn(
  api: Transport,
  elderId: string,
  job: VoiceJob,
  context: {
    conversationId?: string;
    pendingActionId?: string;
    notificationId?: string;
  },
  signal: AbortSignal,
  ensureActive: () => void,
): Promise<Schemas["AgentTurn"]> {
  ensureActive();
  if (job.result) return job.result;
  logNode(job.id, "upload", 1, "started");
  try {
    if (!job.audioId)
      job.audioId = (
        await api.upload(elderId, job.audio, "voice_message", signal)
      ).asset_id;
    ensureActive();
    if (job.frame && !job.imageId)
      job.imageId = (
        await api.upload(elderId, job.frame, "meal", signal)
      ).asset_id;
    ensureActive();
  } catch (error) {
    logNode(job.id, "upload", 1, "failed", error);
    throw error;
  }
  job.body ||= {
    elder_id: elderId,
    client_turn_id: job.id,
    conversation_id: context.conversationId,
    audio_asset_id: job.audioId,
    image_asset_ids: job.imageId ? [job.imageId] : [],
    context: {
      ...(context.pendingActionId
        ? { pending_action_id: context.pendingActionId }
        : {}),
      ...(context.notificationId
        ? { notification_id: context.notificationId }
        : {}),
    },
  };
  logNode(job.id, "upload", 1, "succeeded");
  job.result = await retryNode(job.id, "agent", signal, () =>
    api.post<Schemas["AgentTurn"]>(
      "/api/v1/agent/turns",
      job.body,
      job.id,
      signal,
    ),
  );
  return job.result;
}
