import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { spawn } from "node:child_process";

const ACTIONS = ["status", "record_start", "record_stop", "stream_start", "stream_stop", "launch", "quit"] as const;
const REMOTE = "/Users/dylanrapanan/obs-control";

export function requestOBS(action: string, signal?: AbortSignal): Promise<Record<string, unknown>> {
  if (!(ACTIONS as readonly string[]).includes(action)) return Promise.reject(new Error("Unsupported OBS action"));
  if (signal?.aborted) return Promise.reject(new Error("Cancelled"));
  return new Promise((resolve, reject) => {
    const child = spawn("ssh", ["-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "mac-mini-16",
      `${REMOTE}/.venv/bin/python ${REMOTE}/obs_bridge.py`], { stdio: ["pipe", "pipe", "pipe"] });
    let stdout = "";
    let settled = false;
    const finish = (error?: Error, result?: Record<string, unknown>) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      if (error) { child.kill("SIGKILL"); reject(error); }
      else resolve(result!);
    };
    const uncertain = action === "status" ? "" : " Outcome may be uncertain; check status before another command.";
    const abort = () => finish(new Error("Cancelled." + uncertain));
    const timer = setTimeout(() => finish(new Error("OBS request timed out." + uncertain)), action === "launch" || action === "quit" ? 60_000 : 20_000);
    signal?.addEventListener("abort", abort, { once: true });
    child.on("error", () => finish(new Error("Unable to start SSH to mac-mini-16.")));
    child.stdin.on("error", () => finish(new Error("OBS SSH input failed." + uncertain)));
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      stdout += chunk;
      if (stdout.length > 32_768) finish(new Error("OBS response exceeded size limit." + uncertain));
    });
    // Drain stderr, but never expose remote diagnostic data or credentials.
    child.stderr.resume();
    child.on("close", (code) => {
      if (settled) return;
      try {
        const result = JSON.parse(stdout);
        if (!result || typeof result !== "object" || typeof result.ok !== "boolean") throw new Error();
        if (code !== 0 && result.ok) throw new Error();
        finish(undefined, result);
      } catch { finish(new Error(`OBS helper/SSH failed (exit ${code}). Check remote installation and OBS availability.` + uncertain)); }
    });
    child.stdin.end(JSON.stringify({ action }));
    if (signal?.aborted) abort();
  });
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "obs",
    label: "OBS",
    description: "Control OBS as a whole on mac-mini-16: status, main recording start/stop, configured stream start/stop, launch, and guarded graceful quit. No phone/source/scene controls or force-kill. Streaming and app launch/quit require explicit user intent. Quit refuses active or unverified outputs.",
    parameters: Type.Object({ action: Type.Union(ACTIONS.map(action => Type.Literal(action))) }),
    executionMode: "sequential",
    async execute(_id, params, signal) {
      try {
        const result = await requestOBS(params.action, signal);
        return { content: [{ type: "text", text: JSON.stringify(result) }], details: result, isError: result.ok === false };
      } catch (error) {
        const text = error instanceof Error ? error.message : "OBS request failed";
        return { content: [{ type: "text", text }], details: { ok: false }, isError: true };
      }
    },
  });
}
