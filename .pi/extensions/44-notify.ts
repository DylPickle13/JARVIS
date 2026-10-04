import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const MAX_NOTIFY_TITLE_CHARACTERS = 24;
const MAX_NOTIFY_MESSAGE_CHARACTERS = 60;
const OUTCOMES = ["accepted", "partial", "disabled", "unavailable", "failed", "ambiguous", "invalid", "retired"] as const;
const DEVICE_OUTCOMES = ["accepted", "failed", "ambiguous", "suppressed"] as const;
type NotifyOutcome = typeof OUTCOMES[number];
type NotifyResult = {
  ok: boolean;
  outcome: NotifyOutcome;
  sessionID?: number;
  textAdjusted?: boolean;
  devices: { platform: "iphone" | "watch"; outcome: typeof DEVICE_OUTCOMES[number]; deduplicated?: boolean }[];
};
export type NotifyRequest = {
  version: 1; pane: string; pid: number; eventID: string; title: string; message: string;
};
type Dispatch = (request: NotifyRequest, signal?: AbortSignal) => Promise<NotifyResult>;
const failure = (outcome: NotifyOutcome): NotifyResult => ({ ok: false, outcome, devices: [] });

// Stable for one tool invocation, distinct across processes/sessions/calls. A
// repeated execution cannot manufacture a fresh receipt and replay a push.
export function notificationEventID(session: string, toolCallID: string, pid: number): string {
  const bytes = createHash("sha256").update(JSON.stringify([session, toolCallID, pid])).digest().subarray(0, 16);
  bytes[6] = (bytes[6] & 0x0f) | 0x50;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

// Never forward arbitrary helper output or stderr into the conversation.
export function parseNotifyResult(raw: string): NotifyResult {
  const value = JSON.parse(raw);
  if (typeof value?.ok !== "boolean" || !OUTCOMES.includes(value.outcome) || !Array.isArray(value.devices)
      || value.devices.length > 2 || value.ok !== (value.outcome === "accepted")) throw new Error("Invalid notification receipt");
  const result: NotifyResult = { ok: value.ok, outcome: value.outcome, devices: [] };
  if (value.sessionID !== undefined) {
    if (!Number.isInteger(value.sessionID) || value.sessionID < 1 || value.sessionID > 9) throw new Error("Invalid notification session");
    result.sessionID = value.sessionID;
  }
  if (value.textAdjusted !== undefined) {
    if (typeof value.textAdjusted !== "boolean") throw new Error("Invalid notification preview status");
    result.textAdjusted = value.textAdjusted;
  }
  for (const device of value.devices) {
    if (!["iphone", "watch"].includes(device?.platform) || !DEVICE_OUTCOMES.includes(device?.outcome)
        || (device.deduplicated !== undefined && typeof device.deduplicated !== "boolean")
        || result.devices.some(previous => previous.platform === device.platform)) throw new Error("Invalid notification device receipt");
    result.devices.push({ platform: device.platform, outcome: device.outcome,
      ...(device.deduplicated !== undefined ? { deduplicated: device.deduplicated } : {}) });
  }
  if (result.outcome === "accepted" && (!result.sessionID || !result.devices.length
      || result.devices.some(device => device.outcome !== "accepted"))) throw new Error("Invalid acceptance receipt");
  if (result.outcome === "partial" && (!result.devices.some(device => device.outcome === "accepted")
      || !result.devices.some(device => device.outcome !== "accepted"))) throw new Error("Invalid partial receipt");
  return result;
}

export function createNotificationDispatcher(spawnProcess: typeof spawn = spawn, timeoutMs = 310_000): Dispatch {
  return async (request, signal) => {
    if (signal?.aborted) return failure("unavailable");
    return new Promise(resolveResult => {
      let completed = false;
      let spawned = false;
      let stdout = "";
      // Text and identity travel only over stdin, never shell interpolation/argv.
      const child = spawnProcess("/opt/homebrew/bin/python3", [
        join(ROOT, "projects", "operation-jarvis", "jarvisd", "jarvisd_core", "scheduler", "session_completion.py"),
        "--notify",
      ], { cwd: ROOT, stdio: ["pipe", "pipe", "ignore"] });
      const finish = (result: NotifyResult) => {
        if (completed) return;
        completed = true;
        clearTimeout(timeout);
        signal?.removeEventListener("abort", abort);
        resolveResult(result);
      };
      const abort = () => {
        child.kill("SIGTERM");
        finish(failure(spawned ? "ambiguous" : "unavailable"));
      };
      // Backend retry/expiry is bounded to five minutes. Cancellation is unknown,
      // never success and never permission to replay the notification.
      const timeout = setTimeout(abort, timeoutMs);
      timeout.unref();
      signal?.addEventListener("abort", abort, { once: true });
      child.once("spawn", () => { spawned = true; });
      child.once("error", () => finish(failure(spawned ? "ambiguous" : "unavailable")));
      child.stdin.on("error", () => { /* close/result is authoritative; never expose EPIPE details */ });
      child.stdout.setEncoding("utf8");
      child.stdout.on("data", (chunk: string) => {
        stdout += chunk;
        if (Buffer.byteLength(stdout, "utf8") > 8192) abort();
      });
      child.once("close", code => {
        if (completed) return;
        if (code !== 0) return finish(failure("ambiguous"));
        try { finish(parseNotifyResult(stdout)); }
        catch { finish(failure("ambiguous")); }
      });
      if (signal?.aborted) abort();
      else child.stdin.end(JSON.stringify(request));
    });
  };
}

export const dispatchNotification = createNotificationDispatcher();

export function createNotifyTool(dispatch: Dispatch = dispatchNotification) {
  return {
    name: "notify",
    label: "Notify",
    description: "Send sir a custom JARVIS iPhone/Watch push from this approved mobile Pi session; tap opens this session. Apple acceptance isn't delivery. No monitoring/scheduling; never retry partial/ambiguous sends.",
    promptSnippet: "Send sir a JARVIS push.",
    promptGuidelines: [
      "Notify for meaningful completions, blockers needing sir's input, or important updates—not every turn. Honour explicit completion-alert requests after verification.",
      "Lock Screen: short, non-sensitive text; no credentials, private paths, raw prompts or conversation excerpts. Sanitization/truncation may use a generic preview.",
      "accepted=Apple acceptance, not confirmed delivery/read; disabled/unavailable=no confirmed send; partial/ambiguous=stop, never auto-resend. No watchers, reminders or scheduling.",
    ],
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true },
    executionMode: "sequential" as const,
    parameters: Type.Object({
      title: Type.String({ minLength: 1, maxLength: MAX_NOTIFY_TITLE_CHARACTERS, description: "Short, non-sensitive notification title; at most 24 characters." }),
      message: Type.String({ minLength: 1, maxLength: MAX_NOTIFY_MESSAGE_CHARACTERS, description: "One complete sentence, at most 60 characters. Put the result first; details stay in this session." }),
    }, { additionalProperties: false }),
    async execute(toolCallID: string, params: { title: string; message: string }, signal: AbortSignal | undefined,
                  _onUpdate: unknown, ctx: ExtensionContext) {
      let result: NotifyResult;
      const pane = process.env.TMUX_PANE || "";
      if (![params.title, params.message].every(value => typeof value === "string" && value.trim())
          || [...params.title].length > MAX_NOTIFY_TITLE_CHARACTERS
          || [...params.message].length > MAX_NOTIFY_MESSAGE_CHARACTERS) result = failure("invalid");
      else if (signal?.aborted || !/^%[0-9]+$/.test(pane)) result = failure("unavailable");
      else {
        const session = ctx.sessionManager.getSessionId();
        const request: NotifyRequest = {
          version: 1, pane, pid: process.pid,
          eventID: notificationEventID(session, toolCallID, process.pid),
          title: params.title, message: params.message,
        };
        try { result = await dispatch(request, signal); }
        catch { result = failure("ambiguous"); }
      }
      const notes: Record<NotifyOutcome, string> = {
        accepted: "Apple accepted the push. Screen delivery and whether sir saw it are unverified.",
        partial: "Some devices accepted the push; others did not. Do not resend automatically.",
        disabled: "Notification dispatch is disabled. No push was sent by this call.",
        unavailable: "No eligible mobile Pi session/device or helper is available. No confirmed send.",
        failed: "Apple did not accept the notification. Do not claim delivery.",
        ambiguous: "Transmission may have occurred. Do not resend automatically.",
        invalid: "Notification request is invalid. No push was sent.",
        retired: "Automatic session-finish notifications are retired. No push was sent.",
      };
      return {
        content: [{ type: "text" as const, text: JSON.stringify({ ...result, note: notes[result.outcome] }) }],
        details: result,
        isError: !result.ok,
      };
    },
  };
}

export default function registerNotify(pi: ExtensionAPI) {
  pi.registerTool(createNotifyTool());
}
