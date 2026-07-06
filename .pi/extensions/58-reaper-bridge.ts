import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { spawn } from "node:child_process";

const DEFAULT_HOST = "mac-mini-llm-16gb";
const DEFAULT_REMOTE_DIR = "/Users/dylanrapanan/reaper-bridge";
const DEFAULT_TIMEOUT_SECONDS = 10;
const MAX_TIMEOUT_SECONDS = 120;

type RunResult = {
  code: number | null;
  signal: NodeJS.Signals | null;
  stdout: string;
  stderr: string;
};

function clampTimeoutSeconds(value: unknown): number {
  const n = typeof value === "number" && Number.isFinite(value) ? value : DEFAULT_TIMEOUT_SECONDS;
  return Math.max(1, Math.min(MAX_TIMEOUT_SECONDS, n));
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'"'"'`)}'`;
}

function parseJsonMaybe(text: string): unknown | undefined {
  const trimmed = text.trim();
  if (!trimmed) return undefined;
  try {
    return JSON.parse(trimmed);
  } catch {
    return undefined;
  }
}

function truncateForTool(text: string, max = 60_000): string {
  if (text.length <= max) return text;
  return `${text.slice(0, max)}\n\n... [truncated ${text.length - max} chars]`;
}

async function runSsh(host: string, remoteCommand: string, stdin: string | undefined, timeoutSeconds: number, signal?: AbortSignal): Promise<RunResult> {
  return await new Promise<RunResult>((resolve, reject) => {
    const child = spawn("ssh", [host, remoteCommand], {
      stdio: ["pipe", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";
    let settled = false;

    const cleanup = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
    };

    const finish = (result: RunResult) => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve(result);
    };

    const fail = (error: Error) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    };

    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      setTimeout(() => child.kill("SIGKILL"), 1_000).unref();
      fail(new Error(`Timed out after ${timeoutSeconds}s running REAPER bridge command over SSH`));
    }, timeoutSeconds * 1000);
    timer.unref();

    const onAbort = () => {
      child.kill("SIGTERM");
      fail(new Error("Cancelled"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });

    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", fail);
    child.on("close", (code, sig) => finish({ code, signal: sig, stdout, stderr }));

    if (stdin !== undefined) child.stdin.write(stdin);
    child.stdin.end();
  });
}

async function runBridgeCli(params: {
  host?: string;
  remoteDir?: string;
  timeoutSeconds?: number;
  cliArgs: string[];
  stdin?: string;
  signal?: AbortSignal;
}) {
  const host = params.host?.trim() || DEFAULT_HOST;
  const remoteDir = params.remoteDir?.trim() || DEFAULT_REMOTE_DIR;
  const timeoutSeconds = clampTimeoutSeconds(params.timeoutSeconds);
  const cliTimeout = Math.max(1, Math.min(timeoutSeconds, MAX_TIMEOUT_SECONDS));
  const remoteCommand = [
    `cd ${shellQuote(remoteDir)}`,
    "&&",
    "python3 -m reaper_bridge",
    "--timeout",
    String(cliTimeout),
    ...params.cliArgs.map(shellQuote),
  ].join(" ");

  const result = await runSsh(host, remoteCommand, params.stdin, timeoutSeconds + 2, params.signal);
  if (result.code !== 0) {
    throw new Error([
      `REAPER bridge SSH command failed with code ${result.code}${result.signal ? ` signal ${result.signal}` : ""}.`,
      result.stderr.trim() ? `stderr:\n${truncateForTool(result.stderr.trim(), 20_000)}` : undefined,
      result.stdout.trim() ? `stdout:\n${truncateForTool(result.stdout.trim(), 20_000)}` : undefined,
    ].filter(Boolean).join("\n\n"));
  }
  return result;
}

export default function reaperBridgeExtension(pi: ExtensionAPI) {
  pi.registerTool({
    name: "reaper_ping",
    label: "REAPER Ping",
    description: "Ping the JARVIS REAPER bridge running on mac-mini-16 and return the live project status. Load with load_tools({ groups: [\"reaper\"] }) before use.",
    promptSnippet: "Ping the live REAPER bridge on mac-mini-16.",
    promptGuidelines: [
      "Use reaper_ping after loading the reaper tool group to verify the live REAPER bridge is running before larger Lua edits when useful.",
    ],
    parameters: Type.Object({
      timeoutSeconds: Type.Optional(Type.Number({ description: "Overall timeout in seconds. Default 10, max 120." })),
      host: Type.Optional(Type.String({ description: `SSH host alias. Default ${DEFAULT_HOST}.` })),
      remoteDir: Type.Optional(Type.String({ description: `Remote reaper-bridge directory. Default ${DEFAULT_REMOTE_DIR}.` })),
    }),
    async execute(_toolCallId, params, signal) {
      const result = await runBridgeCli({
        host: params.host,
        remoteDir: params.remoteDir,
        timeoutSeconds: params.timeoutSeconds,
        cliArgs: ["doctor"],
        signal,
      });
      const parsed = parseJsonMaybe(result.stdout);
      return {
        content: [{ type: "text", text: truncateForTool(result.stdout.trim() || "{}") }],
        details: { parsed, stderr: result.stderr, host: params.host || DEFAULT_HOST },
      };
    },
  });

  pi.registerTool({
    name: "reaper_lua",
    label: "REAPER Lua",
    description: "Run inline Lua inside the live REAPER session via the JARVIS bridge on mac-mini-16. The Lua is sent over stdin and is not saved as a script. Load with load_tools({ groups: [\"reaper\"] }) before use.",
    promptSnippet: "Run inline Lua in live REAPER via the bridge; code is not saved.",
    promptGuidelines: [
      "Use reaper_lua only after loading the reaper tool group. Send complete inline Lua that returns JSON-safe tables for inspection results.",
      "For edits via reaper_lua, include any desired reaper.Undo_BeginBlock()/Undo_EndBlock() directly in the Lua code; the bridge intentionally does not hardcode actions or safety wrappers.",
      "Do not save temporary task scripts for REAPER work; pass Lua inline through reaper_lua.",
      "Do not guess REAPER/ReaScript API signatures. Before using any unfamiliar REAPER API call, inspect the official ReaScript docs, local bridge examples, or known project examples.",
      "Official ReaScript API docs: https://www.reaper.fm/sdk/reascript/reascripthelp.html",
      "If a REAPER API call returns an unexpected value/type, stop immediately and look up the API before retrying. Do not make a second guessed attempt.",
      "Capture all return values for REAPER API functions unless the signature has been verified. Many REAPER functions return multiple values, e.g. local ok, name = reaper.GetTrackName(track, \"\") not C-style mutable buffers.",
      "For common checks, you may also use: reaper.APIExists(\"FunctionName\")",
    ],
    parameters: Type.Object({
      code: Type.String({ description: "Lua code to execute inside REAPER. Return a table/string/number/boolean/nil for JSON output." }),
      timeoutSeconds: Type.Optional(Type.Number({ description: "Overall timeout in seconds. Default 10, max 120." })),
      host: Type.Optional(Type.String({ description: `SSH host alias. Default ${DEFAULT_HOST}.` })),
      remoteDir: Type.Optional(Type.String({ description: `Remote reaper-bridge directory. Default ${DEFAULT_REMOTE_DIR}.` })),
    }),
    async execute(_toolCallId, params, signal) {
      const result = await runBridgeCli({
        host: params.host,
        remoteDir: params.remoteDir,
        timeoutSeconds: params.timeoutSeconds,
        cliArgs: ["run", "-"],
        stdin: params.code,
        signal,
      });
      const parsed = parseJsonMaybe(result.stdout);
      return {
        content: [{ type: "text", text: truncateForTool(result.stdout.trim() || "null") }],
        details: { parsed, stderr: result.stderr, host: params.host || DEFAULT_HOST },
      };
    },
  });
}
