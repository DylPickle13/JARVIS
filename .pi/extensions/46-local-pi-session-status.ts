import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const DEFAULT_JARVIS_ROOT = resolve(process.env.JARVIS_ROOT || process.cwd());
const HEARTBEAT_MS = 2_000;
const PRUNE_INTERVAL_MS = 60_000;
const MAX_STATUS_AGE_MS = 30 * 24 * 60 * 60 * 1000;

type LocalPiSessionLifecycle = "idle" | "running" | "waiting" | "compacting";

function findProjectRoot(cwd: string): string {
  let current = resolve(cwd || process.cwd());
  while (true) {
    if (existsSync(join(current, ".pi")) && existsSync(join(current, "projects"))) return current;
    const parent = dirname(current);
    if (parent === current) break;
    current = parent;
  }
  return DEFAULT_JARVIS_ROOT;
}

function safeFileName(value: string): string {
  return value.replace(/[^a-zA-Z0-9._-]+/g, "-").slice(0, 180) || "session";
}

function pidIsAlive(value: unknown): boolean {
  const pid = typeof value === "number" ? value : Number(value);
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error: any) {
    return error?.code === "EPERM";
  }
}

export default function registerLocalPiSessionStatus(pi: ExtensionAPI) {
  let root = findProjectRoot(process.cwd());
  let statusDir = join(root, ".pi", "runtime", "local-pi-sessions");
  let statusPath = join(statusDir, `${process.pid}.json`);
  let sessionFile = "";
  let cwd = process.cwd();
  let lifecycle: LocalPiSessionLifecycle = "idle";
  let agentRunning = false;
  let waitingForPrompt = false;
  let compacting = false;
  let idleProbe: (() => boolean) | undefined;
  let completionID: string | undefined;
  let completionEligible = false;

  function notifySuccessfulCompletion() {
    if (lifecycle !== "idle" || !completionID || !completionEligible) return;
    const eventID = completionID;
    completionID = undefined; // consume before I/O; heartbeat/settled coalesce
    completionEligible = false;
    const pane = process.env.TMUX_PANE || "";
    if (!/^%[0-9]+$/.test(pane)) return;
    if (!existsSync(join(root, ".pi", "runtime", "session-notifications", "enabled"))) return;
    // No prompt, output, path, or credentials in arguments. The fixed helper
    // independently checks this PID belongs to one of the nine approved panes.
    try {
      const child = spawn("/opt/homebrew/bin/python3", [
        join(root, ".pi", "scheduler", "session_completion.py"),
        pane, String(process.pid), eventID,
      ], { stdio: "ignore", detached: true });
      child.on("error", () => {});
      child.unref();
    } catch { /* completion notifications are best-effort and content-free */ }
  }
  let heartbeat: ReturnType<typeof setInterval> | undefined;
  let lastPruneMs = 0;

  function shouldPruneStatusFile(filePath: string, now: number): boolean {
    if (filePath === statusPath) return false;
    let ageMs = 0;
    try {
      ageMs = Math.max(0, now - statSync(filePath).mtimeMs);
    } catch {
      return true;
    }
    if (ageMs > MAX_STATUS_AGE_MS) return true;

    try {
      const payload = JSON.parse(readFileSync(filePath, "utf8"));
      return !pidIsAlive(payload?.pid);
    } catch {
      return false;
    }
  }

  function pruneStatusDir(force = false) {
    const now = Date.now();
    if (!force && now - lastPruneMs < PRUNE_INTERVAL_MS) return;
    lastPruneMs = now;
    try {
      mkdirSync(statusDir, { recursive: true });
      for (const name of readdirSync(statusDir)) {
        if (!name.endsWith(".json")) continue;
        const filePath = join(statusDir, name);
        if (shouldPruneStatusFile(filePath, now)) rmSync(filePath, { force: true });
      }
    } catch {
      // Best-effort local Pi session telemetry cleanup only.
    }
  }

  function resolvedLifecycle(isIdle?: boolean): LocalPiSessionLifecycle {
    if (compacting) return "compacting";
    if (waitingForPrompt) return "waiting";
    if (agentRunning || isIdle === false) return "running";
    return "idle";
  }

  function writeStatus(reason: string) {
    const now = new Date().toISOString();
    pruneStatusDir();
    try {
      mkdirSync(statusDir, { recursive: true });
      const payload = {
        version: 2,
        id: `local:${process.pid}`,
        pid: process.pid,
        lifecycle,
        source: "pi-extension-local-session-status",
        reason,
        cwd,
        sessionFile,
        updatedAt: now,
      };
      writeFileSync(statusPath, JSON.stringify(payload, null, 2), "utf8");
    } catch {
      // Best-effort local Pi session telemetry only.
    }
  }

  function updateLifecycle(reason: string, isIdle?: boolean) {
    lifecycle = resolvedLifecycle(isIdle);
    writeStatus(reason);
  }

  function removeStatus() {
    try {
      rmSync(statusPath, { force: true });
    } catch {
      // Best-effort local Pi session telemetry only.
    }
  }

  function ensureHeartbeat() {
    if (heartbeat) return;
    heartbeat = setInterval(() => {
      // A compaction callback can run before Pi clears its internal busy flag.
      // Reconcile from the current documented isIdle() contract rather than
      // refreshing a latched Running state indefinitely. Queued continuation
      // and automatic retries keep isIdle() false, so no false idle is emitted.
      if (!compacting && idleProbe) {
        agentRunning = !idleProbe();
        lifecycle = resolvedLifecycle(!agentRunning);
      }
      writeStatus(`heartbeat-${lifecycle}`);
      notifySuccessfulCompletion();
    }, HEARTBEAT_MS);
    heartbeat.unref?.();
  }

  pi.on("session_start", async (_event, ctx) => {
    cwd = ctx.cwd || process.cwd();
    root = findProjectRoot(cwd);
    statusDir = join(root, ".pi", "runtime", "local-pi-sessions");
    sessionFile = ctx.sessionManager.getSessionFile() || "";
    const suffix = sessionFile ? safeFileName(sessionFile) : "ephemeral";
    statusPath = join(statusDir, `${process.pid}-${suffix}.json`);
    completionID = undefined;
    completionEligible = false; // session changes never replay the previous turn
    idleProbe = () => ctx.isIdle();
    agentRunning = !ctx.isIdle();
    waitingForPrompt = false;
    compacting = false;
    lifecycle = resolvedLifecycle(ctx.isIdle());
    pruneStatusDir(true);
    writeStatus("session-start");
    ensureHeartbeat();
  });

  pi.on("agent_start", async (_event, ctx) => {
    cwd = ctx.cwd || cwd;
    sessionFile = ctx.sessionManager.getSessionFile() || sessionFile;
    completionID = randomUUID();
    completionEligible = false;
    agentRunning = true;
    updateLifecycle("agent-start", false);
    ensureHeartbeat();
  });

  // agent_end is not idle: Pi may still retry, compact, or continue. Only
  // agent_settled authoritatively marks the end of automatic agent activity.
  pi.on("agent_end", async (event, ctx) => {
    const lastAssistant = [...event.messages].reverse().find((message) => message.role === "assistant");
    completionEligible = lastAssistant?.stopReason === "stop";
    cwd = ctx.cwd || cwd;
    sessionFile = ctx.sessionManager.getSessionFile() || sessionFile;
    updateLifecycle("agent-end-awaiting-settle", false);
  });

  pi.on("agent_settled", async (_event, ctx) => {
    cwd = ctx.cwd || cwd;
    sessionFile = ctx.sessionManager.getSessionFile() || sessionFile;
    agentRunning = !ctx.isIdle();
    updateLifecycle("agent-settled", ctx.isIdle());
    notifySuccessfulCompletion();
  });

  pi.on("ui_prompt_start", async () => {
    waitingForPrompt = true;
    updateLifecycle("ui-prompt-start");
  });

  pi.on("ui_prompt_end", async (_event, ctx) => {
    waitingForPrompt = false;
    updateLifecycle("ui-prompt-end", ctx.isIdle());
  });

  pi.on("session_before_compact", async () => {
    compacting = true;
    updateLifecycle("session-before-compact");
  });

  pi.on("session_compact", async (_event, ctx) => {
    compacting = false;
    agentRunning = !ctx.isIdle();
    updateLifecycle("session-compact", ctx.isIdle());
  });

  pi.on("session_compact_failed", async (_event, ctx) => {
    compacting = false;
    agentRunning = !ctx.isIdle();
    updateLifecycle("session-compact-failed", ctx.isIdle());
  });

  pi.on("session_shutdown", async () => {
    completionID = undefined;
    completionEligible = false;
    if (heartbeat) clearInterval(heartbeat);
    heartbeat = undefined;
    removeStatus();
  });

  process.once("exit", removeStatus);
}
