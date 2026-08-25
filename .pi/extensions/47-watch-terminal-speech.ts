import { createHash } from "node:crypto";
import { chmodSync, mkdirSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const MAX_SPEECH_TEXT_BYTES = 32 * 1024;
const PUBLISHER_STARTED_AT = Date.now();
const TMUX_PANE_ID = process.env.TMUX_PANE || "";
const TMUX_SERVER_PID = Number((process.env.TMUX || "").split(",")[1] || 0);

type SpeechSelection = {
  responseID: string;
  text: string;
};

type SpeechMarkerStatus = "empty" | "generating" | "ready" | "unavailable";

/**
 * Select only the final assistant text for the latest user turn on the active
 * Pi branch. Thinking, tool calls, tool results, and intermediate tool-use
 * messages are never copied into Watch speech state.
 */
export function selectWatchTerminalSpeech(entries: readonly any[], sessionID: string): SpeechSelection | undefined {
  let latestUserIndex = -1;
  for (let index = entries.length - 1; index >= 0; index -= 1) {
    const entry = entries[index];
    if (entry?.type === "message" && entry?.message?.role === "user") {
      latestUserIndex = index;
      break;
    }
  }
  if (latestUserIndex < 0) return undefined;

  for (let index = entries.length - 1; index > latestUserIndex; index -= 1) {
    const entry = entries[index];
    const message = entry?.type === "message" ? entry.message : undefined;
    if (message?.role !== "assistant") continue;
    if (message.stopReason !== "stop" && message.stopReason !== "length") continue;
    if (!Array.isArray(message.content)) continue;

    const text = message.content
      .filter((part: any) => part?.type === "text" && typeof part.text === "string")
      .map((part: any) => part.text)
      .join("")
      .trim();
    if (!text) return undefined;

    const entryID = typeof entry.id === "string" ? entry.id : "";
    const responseID = createHash("sha256")
      .update(`${sessionID}\0${entryID}\0${message.timestamp ?? ""}`)
      .digest("hex");
    return { responseID, text };
  }
  return undefined;
}

export default function registerWatchTerminalSpeech(pi: ExtensionAPI) {
  const speechDirectory = join(homedir(), "Library", "Application Support", "JARVIS", "terminald", "speech");
  const markerPath = join(speechDirectory, `${process.pid}.json`);

  function publish(status: SpeechMarkerStatus, selection?: SpeechSelection) {
    try {
      mkdirSync(speechDirectory, { recursive: true, mode: 0o700 });
      chmodSync(speechDirectory, 0o700);
      const textBytes = selection ? Buffer.byteLength(selection.text, "utf8") : 0;
      const safeSelection = selection && textBytes <= MAX_SPEECH_TEXT_BYTES ? selection : undefined;
      const effectiveStatus: SpeechMarkerStatus = selection && !safeSelection ? "unavailable" : status;
      const payload = {
        version: 1,
        pid: process.pid,
        paneID: TMUX_PANE_ID,
        tmuxServerPID: Number.isInteger(TMUX_SERVER_PID) ? TMUX_SERVER_PID : 0,
        publisherStartedAt: PUBLISHER_STARTED_AT,
        updatedAt: Date.now(),
        status: effectiveStatus,
        responseID: safeSelection?.responseID ?? "",
        textByteCount: safeSelection ? textBytes : 0,
        text: safeSelection?.text ?? "",
      };
      const temporaryPath = `${markerPath}.${process.pid}.${Date.now()}.tmp`;
      writeFileSync(temporaryPath, `${JSON.stringify(payload)}\n`, { encoding: "utf8", mode: 0o600 });
      chmodSync(temporaryPath, 0o600);
      renameSync(temporaryPath, markerPath);
    } catch {
      // Speech publication is best effort and must never interfere with Pi.
    }
  }

  function publishCurrentResponse(ctx: any) {
    const sessionID = String(ctx.sessionManager.getSessionId() || "");
    const selection = selectWatchTerminalSpeech(ctx.sessionManager.getBranch(), sessionID);
    publish(selection ? "ready" : "empty", selection);
  }

  function removeMarker() {
    try {
      rmSync(markerPath, { force: true });
    } catch {
      // Best-effort private runtime cleanup only.
    }
  }

  pi.on("session_start", async (_event, ctx) => {
    publishCurrentResponse(ctx);
  });

  pi.on("agent_start", async () => {
    publish("generating");
  });

  pi.on("agent_settled", async (_event, ctx) => {
    publishCurrentResponse(ctx);
  });

  pi.on("session_shutdown", async () => {
    process.off("exit", removeMarker);
    removeMarker();
  });

  process.once("exit", removeMarker);
}
