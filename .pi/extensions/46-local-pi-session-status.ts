import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const DEFAULT_JARVIS_ROOT = resolve(process.env.JARVIS_ROOT || process.cwd());
const HEARTBEAT_MS = 2_000;
const PRUNE_INTERVAL_MS = 60_000;
const MAX_STATUS_AGE_MS = 30 * 24 * 60 * 60 * 1000;

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
  let active = false;
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
      // Best-effort dashboard telemetry cleanup only.
    }
  }

  function writeStatus(reason: string) {
    const now = new Date().toISOString();
    pruneStatusDir();
    try {
      mkdirSync(statusDir, { recursive: true });
      const payload = {
        version: 1,
        id: `local:${process.pid}`,
        pid: process.pid,
        active,
        source: "pi-extension-local-session-status",
        reason,
        cwd,
        sessionFile,
        updatedAt: now,
      };
      writeFileSync(statusPath, JSON.stringify(payload, null, 2), "utf8");
    } catch {
      // Best-effort dashboard telemetry only.
    }
  }

  function removeStatus() {
    try {
      rmSync(statusPath, { force: true });
    } catch {
      // Best-effort dashboard telemetry only.
    }
  }

  function ensureHeartbeat() {
    if (heartbeat) return;
    heartbeat = setInterval(() => writeStatus(active ? "heartbeat-active" : "heartbeat-idle"), HEARTBEAT_MS);
    heartbeat.unref?.();
  }

  pi.on("session_start", async (_event, ctx) => {
    cwd = ctx.cwd || process.cwd();
    root = findProjectRoot(cwd);
    statusDir = join(root, ".pi", "runtime", "local-pi-sessions");
    sessionFile = ctx.sessionManager.getSessionFile() || "";
    const suffix = sessionFile ? safeFileName(sessionFile) : "ephemeral";
    statusPath = join(statusDir, `${process.pid}-${suffix}.json`);
    pruneStatusDir(true);
    active = !ctx.isIdle();
    writeStatus("session-start");
    ensureHeartbeat();
  });

  pi.on("agent_start", async (_event, ctx) => {
    cwd = ctx.cwd || cwd;
    sessionFile = ctx.sessionManager.getSessionFile() || sessionFile;
    active = true;
    writeStatus("agent-start");
    ensureHeartbeat();
  });

  pi.on("agent_end", async (_event, ctx) => {
    cwd = ctx.cwd || cwd;
    sessionFile = ctx.sessionManager.getSessionFile() || sessionFile;
    active = false;
    writeStatus("agent-end");
  });

  pi.on("session_shutdown", async () => {
    if (heartbeat) clearInterval(heartbeat);
    heartbeat = undefined;
    removeStatus();
  });

  process.once("exit", removeStatus);
}
