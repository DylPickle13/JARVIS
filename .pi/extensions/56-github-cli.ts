import { spawn } from "node:child_process";
import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, resolve } from "node:path";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

import { truncate } from "./lib/text";

type GithubCliParams = {
  args: string[];
  cwd?: string;
  stdin?: string;
  timeoutSeconds?: number;
  allowDangerous?: boolean;
};

type ProcessResult = {
  code: number | null;
  stdout: string;
  stderr: string;
  killed: boolean;
};

const DEFAULT_ROOT = resolve(process.env.JARVIS_ROOT || process.cwd());
const DEFAULT_TIMEOUT_SECONDS = 120;
const MAX_TIMEOUT_SECONDS = 900;
const TOKEN_KEYS = ["GH_TOKEN", "GITHUB_TOKEN", "GITHUB_TOKEN_WRITE", "GITHUB_TOKEN_READ"] as const;
const TOKEN_LIKE_PATTERN = /\b(?:github_pat_[A-Za-z0-9_]+|gh[pousr]_[A-Za-z0-9_]{20,})\b/g;

const EXTRA_DANGEROUS_EXAMPLES = [
  "repo delete/archive/rename/transfer/edit",
  "api DELETE/PATCH/PUT/POST to repo/admin endpoints",
  "secret/variable set/delete",
  "workflow disable/delete",
  "release delete",
  "gist delete",
  "codespace delete",
].join("; ");

function cleanString(value: unknown): string {
  return String(value ?? "").replace(/\r\n?/g, "\n").trim();
}

function containsControlCharacters(value: string): boolean {
  return /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/.test(value);
}

function parseEnvValue(value: string): string {
  let v = value.trim();
  if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
    v = v.slice(1, -1);
  }
  return v;
}

function findEnvPath(startCwd: string): string | undefined {
  let current = resolve(startCwd || DEFAULT_ROOT);
  while (true) {
    const candidate = `${current}/.env`;
    if (existsSync(candidate)) return candidate;
    const parent = dirname(current);
    if (parent === current) break;
    current = parent;
  }
  const fallback = `${DEFAULT_ROOT}/.env`;
  return existsSync(fallback) ? fallback : undefined;
}

function loadToken(cwd: string): { token: string; source: string } {
  for (const key of TOKEN_KEYS) {
    const value = process.env[key];
    if (value && value.trim()) return { token: value.trim(), source: `process.env.${key}` };
  }

  const envPath = findEnvPath(cwd);
  if (envPath) {
    const lines = readFileSync(envPath, "utf8").split(/\n/);
    const values = new Map<string, string>();
    for (const raw of lines) {
      const line = raw.trim();
      if (!line || line.startsWith("#") || !line.includes("=")) continue;
      const [key, ...rest] = line.split("=");
      const normalizedKey = key.trim().replace(/^export\s+/, "");
      values.set(normalizedKey, parseEnvValue(rest.join("=")));
    }
    for (const key of TOKEN_KEYS) {
      const value = values.get(key);
      if (value && value.trim() && value !== "paste_your_github_token_here") {
        return { token: value.trim(), source: envPath };
      }
    }
  }

  throw new Error(`No GitHub token found. Set GITHUB_TOKEN or GH_TOKEN in ${envPath || `${DEFAULT_ROOT}/.env`} first.`);
}

function redact(text: string, token?: string): string {
  let output = String(text ?? "");
  if (token) output = output.split(token).join("[REDACTED_GITHUB_TOKEN]");
  return output.replace(TOKEN_LIKE_PATTERN, "[REDACTED_GITHUB_TOKEN]");
}

function sanitizeForDisplay(value: string, token?: string): string {
  const redacted = redact(value, token);
  if (/\s/.test(redacted)) return JSON.stringify(redacted);
  return redacted;
}

function summarizeArgs(args: string[], token?: string): string {
  return args.map((arg) => sanitizeForDisplay(arg, token)).join(" ");
}

function normalizeCwd(rawCwd: unknown, ctxCwd: string): string {
  const cwd = resolve(cleanString(rawCwd) || ctxCwd || DEFAULT_ROOT);
  if (!existsSync(cwd)) throw new Error(`cwd does not exist: ${cwd}`);
  if (!statSync(cwd).isDirectory()) throw new Error(`cwd is not a directory: ${cwd}`);
  return cwd;
}

function validateArgs(args: unknown): string[] {
  if (!Array.isArray(args) || args.length === 0) {
    throw new Error("github_cli requires args, e.g. { args: [\"repo\", \"list\", \"DylPickle13\", \"--limit\", \"100\"] }.");
  }
  const cleaned = args.map((arg) => String(arg));
  const first = cleaned[0];
  if (first === "gh" || first.endsWith("/gh")) {
    throw new Error("github_cli args are CLI tokens after the `gh` binary; omit `gh` itself.");
  }
  for (const arg of cleaned) {
    if (containsControlCharacters(arg)) throw new Error("github_cli args contain unsupported control characters.");
    if (TOKEN_LIKE_PATTERN.test(arg)) {
      TOKEN_LIKE_PATTERN.lastIndex = 0;
      throw new Error("Do not pass GitHub tokens in github_cli args. Store the token in .env as GITHUB_TOKEN instead.");
    }
    TOKEN_LIKE_PATTERN.lastIndex = 0;
    if (/^authorization\s*:/i.test(arg) || /^bearer\s+/i.test(arg)) {
      throw new Error("Do not pass Authorization/Bearer headers through github_cli args. The tool injects GH_TOKEN from .env.");
    }
  }
  return cleaned;
}

function optionValue(args: string[], names: string[]): string | undefined {
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    for (const name of names) {
      if (arg === name && i + 1 < args.length) return args[i + 1];
      if (arg.startsWith(`${name}=`)) return arg.slice(name.length + 1);
    }
  }
  return undefined;
}

function apiMethod(args: string[]): string {
  return (optionValue(args, ["-X", "--method"]) || "GET").toUpperCase();
}

function hasFlag(args: string[], names: readonly string[]): boolean {
  return args.some((arg) => names.some((name) => arg === name || arg.startsWith(`${name}=`)));
}

function firstNonOptionCommand(args: string[]): string | undefined {
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    if (!arg.startsWith("-")) return arg;
    if (["--hostname", "--repo", "-R", "--jq", "-q", "--template", "-t"].includes(arg) && i + 1 < args.length) i += 1;
  }
  return undefined;
}

function hasAny(args: string[], values: readonly string[]): boolean {
  return args.some((arg) => values.includes(arg));
}

function dangerousReason(args: string[]): string | undefined {
  const command = firstNonOptionCommand(args);
  if (!command) return undefined;
  const lower = args.map((arg) => arg.toLowerCase());

  if (command === "auth") {
    if (lower.includes("token") || lower.includes("--show-token")) {
      return "Blocked permanently: `gh auth token` / `--show-token` can print the GitHub token.";
    }
    const sub = lower.find((arg) => !arg.startsWith("-") && arg !== "auth");
    if (sub && sub !== "status") return "GitHub auth mutation/login commands are blocked. Use .env GH_TOKEN/GITHUB_TOKEN instead.";
  }

  if (hasAny(lower, ["--show-token"])) {
    return "Blocked permanently: `--show-token` can print the GitHub token.";
  }

  if (command === "repo") {
    const sub = lower.find((arg, index) => index > lower.indexOf("repo") && !arg.startsWith("-"));
    if (sub && ["delete", "archive", "unarchive", "rename", "transfer", "edit"].includes(sub)) {
      return `Potentially destructive repo command: gh repo ${sub}.`;
    }
  }

  if (command === "api") {
    const method = apiMethod(args);
    if (["DELETE", "PATCH", "PUT", "POST"].includes(method)) {
      return `Mutating GitHub API request: ${method}.`;
    }
    if (hasFlag(args, ["-f", "--raw-field", "-F", "--field", "--input"])) {
      return "GitHub API request includes body/field/input data and may mutate state.";
    }
  }

  if (command === "secret" || command === "variable") {
    const sub = lower.find((arg, index) => index > lower.indexOf(command) && !arg.startsWith("-"));
    if (sub && ["set", "delete", "remove"].includes(sub)) return `Sensitive GitHub ${command} mutation: ${sub}.`;
  }

  if (command === "workflow") {
    const sub = lower.find((arg, index) => index > lower.indexOf("workflow") && !arg.startsWith("-"));
    if (sub && ["disable", "delete"].includes(sub)) return `Potentially disruptive workflow command: gh workflow ${sub}.`;
  }

  for (const cmd of ["release", "gist", "codespace"]) {
    if (command === cmd) {
      const sub = lower.find((arg, index) => index > lower.indexOf(cmd) && !arg.startsWith("-"));
      if (sub === "delete") return `Destructive GitHub command: gh ${cmd} delete.`;
    }
  }

  return undefined;
}

function timeoutMs(params: GithubCliParams, args: string[]): number {
  const explicit = params.timeoutSeconds;
  if (explicit !== undefined) {
    if (!Number.isFinite(explicit)) throw new Error("timeoutSeconds must be finite.");
    return Math.max(1, Math.min(Math.round(explicit), MAX_TIMEOUT_SECONDS)) * 1000;
  }
  const command = firstNonOptionCommand(args);
  if (command === "repo" && args.map((arg) => arg.toLowerCase()).includes("clone")) return 300_000;
  if (command === "release") return 300_000;
  if (command === "api") return 90_000;
  return DEFAULT_TIMEOUT_SECONDS * 1000;
}

function runGh(args: string[], options: { cwd: string; token: string; stdin?: string; signal?: AbortSignal; timeout: number }): Promise<ProcessResult> {
  return new Promise((resolveResult, reject) => {
    const env = {
      ...process.env,
      GH_TOKEN: options.token,
      GITHUB_TOKEN: options.token,
      GH_PROMPT_DISABLED: "1",
      GIT_TERMINAL_PROMPT: "0",
    };
    const ghBinary = process.env.JARVIS_GH_PATH || process.env.GH_PATH || "gh";
    const child = spawn(ghBinary, args, {
      cwd: options.cwd,
      env,
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
      setTimeout(() => child.kill("SIGKILL"), 1500).unref?.();
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
    child.on("error", (error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") {
        finish(() => reject(new Error("GitHub CLI `gh` is not installed or not on PATH. Install it with `brew install gh`.")));
        return;
      }
      finish(() => reject(error));
    });
    child.on("close", (code) => finish(() => resolveResult({ code, stdout, stderr, killed })));

    if (options.stdin !== undefined) child.stdin.write(options.stdin);
    child.stdin.end();
  });
}

export default function registerGithubCli(pi: ExtensionAPI) {
  pi.registerTool({
    name: "github_cli",
    label: "GitHub CLI",
    description: "Run the official GitHub CLI (`gh`) with args passed as tokens after the binary. The tool loads GITHUB_TOKEN/GH_TOKEN from the local .env, exports it as GH_TOKEN, redacts token-like output, disables prompts, and blocks token-printing/auth commands plus dangerous mutations unless allowDangerous is true.",
    promptSnippet: "GitHub/`gh` => github_cli; args are tokens after `gh`.",
    promptGuidelines: [
      "GitHub/`gh` => always-on `github_cli`; never bash `gh`. Local `git` status/diff/add/commit/log/branch => bash. If `github_cli` unavailable, report tool failure.",
    ],
    parameters: Type.Object({
      args: Type.Array(Type.String(), {
        minItems: 1,
        description: "GitHub CLI tokens after the `gh` binary. Examples: ['auth','status']; ['repo','list','DylPickle13','--limit','100']; ['repo','list','DylPickle13','--visibility','private']; ['repo','clone','DylPickle13/EnGem']; ['api','/user/repos','--paginate']; ['pr','list','--json','number,title,url'].",
      }),
      cwd: Type.Optional(Type.String({ description: "Working directory for the gh command. Defaults to the current Pi working directory." })),
      stdin: Type.Optional(Type.String({ description: "Optional stdin for commands that read from standard input, e.g. body files or gh api --input -. Do not include tokens/secrets unless explicitly required by the user." })),
      timeoutSeconds: Type.Optional(Type.Number({ description: `Timeout in seconds. Default ${DEFAULT_TIMEOUT_SECONDS}; max ${MAX_TIMEOUT_SECONDS}. Clone/release/API commands get longer defaults.` })),
      allowDangerous: Type.Optional(Type.Boolean({ description: `Set true only after explicit user confirmation for dangerous mutations (${EXTRA_DANGEROUS_EXAMPLES}). Token-printing auth commands remain blocked.` })),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, rawParams, signal, onUpdate, ctx) {
      const params = rawParams as GithubCliParams;
      const args = validateArgs(params.args);
      const cwd = normalizeCwd(params.cwd, ctx.cwd);
      const { token, source } = loadToken(cwd);
      const reason = dangerousReason(args);
      if (reason) {
        const permanentlyBlocked = reason.startsWith("Blocked permanently") || reason.includes("auth mutation/login");
        if (permanentlyBlocked || params.allowDangerous !== true) {
          throw new Error(`${reason}${permanentlyBlocked ? "" : " Re-run only after explicit user confirmation with allowDangerous: true."}`);
        }
      }

      const commandSummary = summarizeArgs(args, token);
      onUpdate?.({ content: [{ type: "text", text: `Running gh ${commandSummary}...` }] });
      const result = await runGh(args, {
        cwd,
        token,
        stdin: params.stdin,
        signal,
        timeout: timeoutMs(params, args),
      });

      const stdout = redact(result.stdout.trim(), token);
      const stderr = redact(result.stderr.trim(), token);
      if (signal?.aborted) throw new Error("github_cli cancelled");
      if (result.killed) throw new Error(`github_cli timed out: gh ${commandSummary}`);
      if (result.code !== 0) {
        const message = [stderr, stdout].filter(Boolean).join("\n").trim();
        throw new Error(message || `gh exited with code ${result.code}`);
      }

      const output = [stdout, stderr ? `stderr:\n${stderr}` : ""].filter(Boolean).join("\n").trim() || "gh completed with no output.";
      return {
        content: [{ type: "text" as const, text: truncate(output, 40_000) }],
        details: {
          ok: true,
          command: ["gh", ...args.map((arg) => redact(arg, token))],
          cwd,
          tokenSource: source.includes(".env") ? source : "process.env",
          dangerous: Boolean(reason),
          dangerousReason: reason,
          stdout: truncate(stdout, 50_000),
          stderr: truncate(stderr, 20_000),
        },
      };
    },
    renderCall(args, theme) {
      const inputArgs = Array.isArray(args.args) ? args.args.map(String) : [];
      return new Text(`${theme.fg("toolTitle", "github_cli")} ${theme.fg("accent", summarizeArgs(inputArgs).slice(0, 120))}`, 0, 0);
    },
    renderResult(result, _options, theme) {
      const summary = Array.isArray(result.content)
        ? result.content.map((part: any) => part?.type === "text" ? String(part.text || "") : "[non-text]").join(" ")
        : "completed";
      return new Text(`${theme.fg("success", "✓ github_cli")} ${theme.fg("dim", summary.replace(/\s+/g, " ").slice(0, 120))}`, 0, 0);
    },
  });
}
