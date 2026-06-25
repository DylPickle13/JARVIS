import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

import { truncate } from "./lib/text";

const DEFAULT_JARVIS_ROOT = resolve(process.env.JARVIS_ROOT || process.cwd());
const IMAGE_COMMANDS = new Set(["screenshot", "snapshot"]);

type AgentPhoneParams = {
  args: string[];
  stdin?: string;
  timeout?: number;
  attachImage?: boolean;
};

type ProcessResult = {
  code: number | null;
  stdout: string;
  stderr: string;
  killed: boolean;
};

function findProjectRoot(cwd: string): string {
  let current = resolve(cwd);
  while (true) {
    if (existsSync(join(current, ".pi")) && existsSync(join(current, "projects", "phone", "agent_phone.py"))) return current;
    const parent = dirname(current);
    if (parent === current) break;
    current = parent;
  }
  return DEFAULT_JARVIS_ROOT;
}

function pythonPath(cwd: string): string {
  const root = findProjectRoot(cwd);
  const rootPython = join(root, ".venv", "bin", "python");
  if (existsSync(rootPython)) return rootPython;
  return "python3";
}

function agentPhoneScript(cwd: string): string {
  const root = findProjectRoot(cwd);
  return join(root, "projects", "phone", "agent_phone.py");
}

function commandName(args: string[]): string | undefined {
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    if (!arg.startsWith("--")) return arg;
    // Global options with values. Keep this small; it only helps rendering and timeouts.
    if (["--mode", "--serial", "--adb-path", "--adb-server-socket", "--remote-host", "--remote-user", "--remote-adb", "--ssh-key", "--runtime-dir"].includes(arg) && i + 1 < args.length) {
      i += 1;
    }
  }
  return undefined;
}

function timeoutMs(args: string[], explicitSeconds?: number): number {
  if (explicitSeconds !== undefined) return Math.max(1, explicitSeconds) * 1000;
  const command = commandName(args);
  if (command === "wait") {
    const index = args.indexOf("--timeout");
    const waitSeconds = index >= 0 && index + 1 < args.length ? Number(args[index + 1]) : 20;
    return Math.ceil((Number.isFinite(waitSeconds) ? waitSeconds : 20) * 1000 + 30_000);
  }
  if (command === "batch") return 180_000;
  if (command === "snapshot" || command === "screenshot") return 90_000;
  if (command === "scrcpy") return 45_000;
  if (command === "status" || command === "devices") return 60_000;
  return 45_000;
}

function shouldAttachImage(params: AgentPhoneParams, payload: any): boolean {
  if (params.attachImage === true) return true;
  if (params.args.includes("--image")) return true;
  if (payload?.details?.imageRequested === true) return true;
  return false;
}

function imagePathFromPayload(payload: any): string | undefined {
  const candidates = [
    payload?.details?.screenshotPath,
    payload?.screenshotPath,
    payload?.details?.imagePath,
    payload?.imagePath,
  ];
  return candidates.find((value) => typeof value === "string" && value.length > 0);
}

function runProcess(command: string, args: string[], options: { cwd: string; stdin?: string; signal?: AbortSignal; timeout: number }): Promise<ProcessResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      stdio: ["pipe", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";
    let killed = false;
    let settled = false;

    const finish = (fn: () => void) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      options.signal?.removeEventListener("abort", onAbort);
      fn();
    };

    const timer = setTimeout(() => {
      killed = true;
      child.kill("SIGTERM");
      setTimeout(() => {
        child.kill("SIGKILL");
      }, 1500).unref?.();
    }, options.timeout);

    const onAbort = () => {
      killed = true;
      child.kill("SIGTERM");
    };
    options.signal?.addEventListener("abort", onAbort, { once: true });

    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("error", (error) => finish(() => reject(error)));
    child.on("close", (code) => finish(() => resolve({ code, stdout, stderr, killed })));

    if (options.stdin !== undefined) {
      child.stdin.write(options.stdin);
    }
    child.stdin.end();
  });
}

function parsePayload(stdout: string, stderr: string): any {
  const raw = stdout.trim() || stderr.trim();
  if (!raw) return { ok: true, text: "agent-phone completed with no output.", details: {} };
  try {
    return JSON.parse(raw);
  } catch {
    return { ok: true, text: raw, details: { stdout: stdout.trim(), stderr: stderr.trim() } };
  }
}

function validateArgs(args: unknown): string[] {
  if (!Array.isArray(args) || args.length === 0) {
    throw new Error("agent_phone requires args, e.g. { args: [\"snapshot\", \"-i\"] }.");
  }
  const cleaned = args.map((arg) => String(arg));
  const firstCommand = commandName(cleaned);
  if (firstCommand === "agent-phone" || firstCommand === "agent_phone.py" || firstCommand?.endsWith("/agent-phone") || firstCommand?.endsWith("/agent_phone.py")) {
    throw new Error("agent_phone args are CLI tokens after the binary; omit `agent-phone` itself.");
  }
  return cleaned;
}

function summarizeArgs(args: string[]): string {
  return args.map((arg) => /\s/.test(arg) ? JSON.stringify(arg) : arg).join(" ");
}

export default function registerAgentPhone(pi: ExtensionAPI) {
  pi.registerTool({
    name: "agent_phone",
    label: "Agent Phone",
    description: "Control a configured Android phone through a safe agent-phone CLI wrapper. Pass CLI tokens in args, excluding the binary. Main flow: status, snapshot -i, tap @ref, type text, press BACK/HOME, wait for text, launch apps, screenshot. The target serial and ADB host should be configured locally via environment or global flags.",
    promptSnippet: "Control the configured Android phone. Example: agent_phone({ args: [\"snapshot\", \"-i\"] }); then tap refs with agent_phone({ args: [\"tap\", \"@3\"] }).",
    promptGuidelines: [
      "Use `agent_phone` only after loading the `phone` tool group with `load_tools({ groups: [\"phone\"] })`; then call `agent_phone` directly.",
      "Call shape: `agent_phone({ args: [\"snapshot\", \"-i\"] })`; `args` are CLI tokens after the `agent-phone` binary, never including `agent-phone` itself.",
      "Typical control loop: `status` → `snapshot -i` → interact with `@refs` using `tap @ref`, `type`, `press BACK/HOME/ENTER`, or `swipe` → run `snapshot -i` again after every screen change.",
      "Prefer `tap @ref` from the latest snapshot over raw coordinates; use `tap-text TEXT` for quick text/description/resource-id matches when refs are obvious.",
      "Use `wait --text ...` after launching apps, opening URLs, or tapping buttons that navigate; use `snapshot -i --image` or `attachImage: true` only when visual pixels are needed, because screenshots add image payload.",
      "Do not use bash/raw ADB for phone control unless explicitly debugging the adapter. The adapter intentionally does not expose raw shell, APK install, SMS/calls, purchases, or account/security changes.",
      "Before sending messages/calls, buying anything, deleting data, changing accounts/security settings, or interacting with private content, stop and ask for explicit confirmation.",
    ],
    parameters: Type.Object({
      args: Type.Array(Type.String(), {
        minItems: 1,
        description: "agent-phone CLI tokens after the binary. Examples: ['status']; ['snapshot','-i']; ['tap','@3']; ['type','hello']; ['press','BACK']; ['wait','--text','Continue']; ['screenshot','--image'].",
      }),
      stdin: Type.Optional(Type.String({ description: "Only for `batch`: JSON array of command token arrays, e.g. [[\"snapshot\",\"-i\"],[\"tap\",\"@1\"]]." })),
      timeout: Type.Optional(Type.Number({ description: "Optional timeout in seconds for this agent-phone invocation." })),
      attachImage: Type.Optional(Type.Boolean({ description: "Attach the screenshot PNG to the tool result when the command produced one. Prefer args including --image for model-readable intent." })),
    }),
    async execute(_toolCallId, rawParams, signal, onUpdate, ctx) {
      const params = rawParams as AgentPhoneParams;
      const args = validateArgs(params.args);
      const script = agentPhoneScript(ctx.cwd);
      if (!existsSync(script)) throw new Error(`agent-phone adapter not found: ${script}`);
      const python = pythonPath(ctx.cwd);
      const fullArgs = [script, "--json", ...args];
      const command = summarizeArgs(args);
      onUpdate?.({ content: [{ type: "text", text: `Running agent-phone ${command}...` }] });
      const result = await runProcess(python, fullArgs, {
        cwd: ctx.cwd,
        stdin: params.stdin,
        signal,
        timeout: timeoutMs(args, params.timeout),
      });

      const payload = parsePayload(result.stdout, result.stderr);
      if (signal?.aborted) throw new Error("agent_phone cancelled");
      if (result.killed) throw new Error(`agent_phone timed out: ${command}`);
      if (result.code !== 0 || payload?.ok === false) {
        throw new Error(payload?.error || payload?.text || result.stderr.trim() || result.stdout.trim() || `agent-phone exited with code ${result.code}`);
      }

      const text = truncate(String(payload?.text || result.stdout.trim() || "agent-phone completed."), 20_000);
      const content: Array<{ type: "text"; text: string } | { type: "image"; data: string; mimeType: string }> = [{ type: "text", text }];
      const imagePath = imagePathFromPayload(payload);
      const attach = shouldAttachImage(params, payload);
      let attachedImage = false;
      if (attach && imagePath && existsSync(imagePath) && IMAGE_COMMANDS.has(commandName(args) || "")) {
        const data = readFileSync(imagePath).toString("base64");
        content.push({ type: "image", data, mimeType: "image/png" });
        attachedImage = true;
      }

      return {
        content,
        details: {
          ok: true,
          command: [python, ...fullArgs],
          args,
          stdout: result.stdout.trim(),
          stderr: result.stderr.trim(),
          attachedImage,
          ...payload?.details,
        },
      };
    },
    renderCall(args, theme) {
      const inputArgs = Array.isArray(args.args) ? args.args.map(String) : [];
      return new Text(`${theme.fg("toolTitle", "agent_phone")} ${theme.fg("accent", summarizeArgs(inputArgs).slice(0, 100))}`, 0, 0);
    },
    renderResult(result, _options, theme) {
      const summary = Array.isArray(result.content)
        ? result.content.map((part: any) => part?.type === "text" ? String(part.text || "") : "[image]").join(" ")
        : "completed";
      return new Text(`${theme.fg("success", "✓ agent_phone")} ${theme.fg("dim", summary.replace(/\s+/g, " ").slice(0, 100))}`, 0, 0);
    },
  });
}
