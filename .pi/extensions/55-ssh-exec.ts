import { randomUUID } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { spawn } from "node:child_process";
import { join, posix as pathPosix } from "node:path";

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

import { createHeadlessTerminal, spawnSshPty, terminalScreen, type IPty, type Terminal } from "./lib/ssh-pty";

type SshAction = "exec" | "start" | "input" | "read" | "resize" | "signal" | "close" | "list";

type SshParams = {
  action?: SshAction;
  host?: string;
  command?: string;
  cwd?: string;
  timeoutSeconds?: number;
  dryRun?: boolean;
  pty?: boolean;
  sessionId?: string;
  input?: string;
  key?: string;
  cols?: number;
  rows?: number;
  signalName?: string;
  consume?: boolean;
};

type HostConfig = {
  aliases: readonly string[];
  description: string;
  hostName: string;
  user: string;
  identityFile: string;
  defaultCwd: string;
  allowedCwdPrefixes: readonly string[];
  connectTimeoutSeconds?: number;
  homeDir: string;
  shell: string;
  shellType: "posix" | "windows-cmd" | "windows-powershell";
};

type SshRenderState = {
  startedAt?: number;
  endedAt?: number;
  interval?: ReturnType<typeof setInterval>;
};

type InteractiveSession = {
  id: string;
  alias: string;
  description: string;
  remote: string;
  cwd: string;
  command: string;
  pty: IPty;
  terminal: Terminal;
  createdAt: number;
  lastActivityAt: number;
  output: string;
  pendingOutput: string;
  outputBytes: number;
  outputTruncated: boolean;
  exited: boolean;
  exitCode?: number;
  exitSignal?: number;
  idleTimer?: ReturnType<typeof setTimeout>;
  timeoutTimer?: ReturnType<typeof setTimeout>;
  terminalDisposed?: boolean;
};

const DEFAULT_SESSION_COLS = 120;
const DEFAULT_SESSION_ROWS = 40;
const DEFAULT_SESSION_IDLE_SECONDS = 30 * 60;
const DEFAULT_SESSION_OUTPUT_BYTES = 64 * 1024;
const SESSION_KEY_MAP: Record<string, string> = {
  ENTER: "\r",
  RETURN: "\r",
  TAB: "\t",
  ESC: "\x1b",
  SPACE: " ",
  BACKSPACE: "\x7f",
  DELETE: "\x1b[3~",
  UP: "\x1b[A",
  DOWN: "\x1b[B",
  RIGHT: "\x1b[C",
  LEFT: "\x1b[D",
  HOME: "\x1b[H",
  END: "\x1b[F",
  PAGEUP: "\x1b[5~",
  PAGEDOWN: "\x1b[6~",
  CTRL_C: "\x03",
  CTRL_D: "\x04",
  CTRL_Z: "\x1a",
  CTRL_L: "\x0c",
};
const INTERACTIVE_SESSIONS = new Map<string, InteractiveSession>();

const DEFAULT_IDENTITY_FILE = process.env.JARVIS_SSH_IDENTITY_FILE || join(homedir(), ".ssh", "id_ed25519");
const DEFAULT_HOST_ALIAS = (process.env.JARVIS_SSH_DEFAULT_HOST || "").trim();
const DEFAULT_TIMEOUT_SECONDS: number | undefined = undefined;
const DEFAULT_HOST_CONFIG_PATH = join(process.cwd(), ".pi", "ssh-hosts.json");
const HOST_CONFIG_PATH = (process.env.JARVIS_SSH_HOSTS_CONFIG || DEFAULT_HOST_CONFIG_PATH).trim();

type RawHostConfig = {
  alias?: unknown;
  aliases?: unknown;
  description?: unknown;
  host?: unknown;
  hostName?: unknown;
  user?: unknown;
  identityFile?: unknown;
  defaultCwd?: unknown;
  allowedCwdPrefixes?: unknown;
  connectTimeoutSeconds?: unknown;
  homeDir?: unknown;
  shell?: unknown;
  shellType?: unknown;
};

function cleanConfigString(value: unknown): string {
  return String(value ?? "")
    .replace(/[\r\n\t]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function asStringArray(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(cleanConfigString).filter(Boolean);
  const single = cleanConfigString(value);
  return single ? [single] : [];
}

function expandLocalPath(value: string): string {
  if (value === "~") return homedir();
  if (value.startsWith("~/")) return join(homedir(), value.slice(2));
  return value;
}

function positiveInteger(value: unknown, fallback: number): number {
  const raw = cleanConfigString(value);
  if (!raw) return fallback;
  const number = Number(raw);
  if (!Number.isFinite(number) || number < 1) return fallback;
  return Math.round(number);
}

function normalizeShellType(value: unknown): HostConfig["shellType"] {
  const shellType = cleanConfigString(value);
  if (shellType === "windows-cmd" || shellType === "windows-powershell" || shellType === "posix") return shellType;
  return "posix";
}

function defaultShell(shellType: HostConfig["shellType"]): string {
  if (shellType === "windows-cmd") return "cmd.exe /c";
  if (shellType === "windows-powershell") return "powershell.exe -NoProfile -Command";
  return "bash -lc";
}

function inferHomeDir(user: string, shellType: HostConfig["shellType"]): string {
  if (shellType === "windows-cmd" || shellType === "windows-powershell") return `C:\\Users\\${user}`;
  return `/home/${user}`;
}

function normalizeHostConfig(raw: RawHostConfig, index: number): HostConfig {
  const aliases = [...asStringArray(raw.aliases), ...asStringArray(raw.alias)];
  const hostName = cleanConfigString(raw.hostName) || cleanConfigString(raw.host);
  const user = cleanConfigString(raw.user);
  if (!aliases.length) throw new Error(`SSH host config #${index + 1} is missing aliases`);
  if (!hostName) throw new Error(`SSH host config ${aliases.join(", ")} is missing hostName`);
  if (!user) throw new Error(`SSH host config ${aliases.join(", ")} is missing user`);

  const shellType = normalizeShellType(raw.shellType);
  const defaultCwd = cleanConfigString(raw.defaultCwd) || "~";
  const homeDir = cleanConfigString(raw.homeDir) || inferHomeDir(user, shellType);
  const allowedCwdPrefixes = asStringArray(raw.allowedCwdPrefixes);

  return {
    aliases,
    description: cleanConfigString(raw.description) || aliases[0],
    hostName,
    user,
    identityFile: expandLocalPath(cleanConfigString(raw.identityFile) || DEFAULT_IDENTITY_FILE),
    defaultCwd,
    allowedCwdPrefixes: allowedCwdPrefixes.length ? allowedCwdPrefixes : [defaultCwd],
    connectTimeoutSeconds: positiveInteger(raw.connectTimeoutSeconds, 8),
    homeDir,
    shell: cleanConfigString(raw.shell) || defaultShell(shellType),
    shellType,
  };
}

function loadHostConfigsFromFile(path: string): HostConfig[] {
  if (!existsSync(path)) return [];
  const parsed = JSON.parse(readFileSync(path, "utf8"));
  if (!Array.isArray(parsed)) throw new Error(`SSH host config file must contain an array: ${path}`);
  return parsed.map((entry, index) => normalizeHostConfig(entry as RawHostConfig, index));
}

function loadHostConfigsFromEnv(): HostConfig[] {
  const hostName = process.env.JARVIS_SSH_HOST || process.env.SSH_HOST;
  const user = process.env.JARVIS_SSH_USER || process.env.SSH_USER;
  if (!cleanConfigString(hostName) && !cleanConfigString(user)) return [];

  return [normalizeHostConfig({
    aliases: process.env.JARVIS_SSH_ALIASES || process.env.JARVIS_SSH_ALIAS || DEFAULT_HOST_ALIAS || "default",
    description: process.env.JARVIS_SSH_DESCRIPTION || "Configured SSH host",
    hostName,
    user,
    identityFile: process.env.JARVIS_SSH_IDENTITY_FILE || DEFAULT_IDENTITY_FILE,
    defaultCwd: process.env.JARVIS_SSH_DEFAULT_CWD || "~",
    allowedCwdPrefixes: (process.env.JARVIS_SSH_ALLOWED_CWD_PREFIXES || "~").split(",").map((item) => item.trim()).filter(Boolean),
    connectTimeoutSeconds: process.env.JARVIS_SSH_CONNECT_TIMEOUT_SECONDS,
    homeDir: process.env.JARVIS_SSH_HOME_DIR,
    shell: process.env.JARVIS_SSH_SHELL,
    shellType: process.env.JARVIS_SSH_SHELL_TYPE,
  }, 0)];
}

function loadHostConfigs(): HostConfig[] {
  const fromFile = loadHostConfigsFromFile(HOST_CONFIG_PATH);
  return fromFile.length ? fromFile : loadHostConfigsFromEnv();
}

const HOST_CONFIGS: readonly HostConfig[] = loadHostConfigs();
const HOST_BY_ALIAS = new Map<string, HostConfig>();
for (const config of HOST_CONFIGS) {
  for (const alias of config.aliases) HOST_BY_ALIAS.set(alias.toLowerCase(), config);
}

const HOST_ALIASES = [...HOST_BY_ALIAS.keys()].sort();
const EFFECTIVE_DEFAULT_HOST_ALIAS = DEFAULT_HOST_ALIAS || HOST_ALIASES[0] || "";
const HOST_ALIASES_DESCRIPTION = HOST_ALIASES.length ? HOST_ALIASES.join(", ") : "none configured";
const DEFAULT_HOST_DESCRIPTION = EFFECTIVE_DEFAULT_HOST_ALIAS || "none";

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

function cleanSingleLine(value: unknown): string {
  return String(value ?? "")
    .replace(/[\r\n\t]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function cleanCommand(value: unknown): string {
  const command = String(value ?? "").replace(/\r\n?/g, "\n").trim();
  if (!command) throw new Error("command is required");
  if (/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/.test(command)) {
    throw new Error("command contains unsupported control characters");
  }
  // Command content is intentionally unrestricted. SSH execution still pins the
  // configured host, identity, and allowed remote working directory.
  return command;
}

function optionalPositiveInteger(value: unknown): number | undefined {
  if (value === undefined || value === null || value === "") return undefined;
  const number = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(number)) throw new Error("timeoutSeconds must be a finite number of seconds");
  const rounded = Math.round(number);
  if (rounded < 1) throw new Error("timeoutSeconds must be at least 1 second");
  return rounded;
}

function expandRemotePath(path: string, homeDir: string): string {
  if (path === "~" || path === "$HOME") return homeDir;
  if (path.startsWith("~/")) return `${homeDir}/${path.slice(2)}`;
  if (path.startsWith("$HOME/")) return `${homeDir}/${path.slice(6)}`;
  // Windows-style drive-letter paths pass through unchanged
  if (/^[A-Za-z]:\\/.test(path)) return path;
  return path;
}

function normalizeRemotePath(path: string, user: string, homeDir: string): string {
  const cleaned = cleanSingleLine(path);
  if (!cleaned) throw new Error("cwd is empty");
  if (/[\u0000-\u001F\u007F]/.test(cleaned)) throw new Error("cwd contains unsupported control characters");
  const expanded = expandRemotePath(cleaned, homeDir);
  // Allow Unix absolute paths or Windows drive-letter paths
  if (!expanded.startsWith("/") && !/^[A-Za-z]:\\/.test(expanded)) {
    throw new Error("cwd must be absolute or start with ~/ or $HOME/");
  }
  // Normalize Unix paths; pass Windows paths through as-is
  if (expanded.startsWith("/")) return pathPosix.normalize(expanded);
  return expanded;
}

function isPathWithin(path: string, prefix: string): boolean {
  return path === prefix || path.startsWith(`${prefix}/`);
}

function resolveHost(aliasValue: unknown): { alias: string; config: HostConfig } {
  const alias = (cleanSingleLine(aliasValue) || EFFECTIVE_DEFAULT_HOST_ALIAS).toLowerCase();
  if (!alias || !HOST_BY_ALIAS.size) {
    throw new Error(`No SSH hosts are configured. Set JARVIS_SSH_HOSTS_CONFIG to a local JSON host config file or provide JARVIS_SSH_HOST/JARVIS_SSH_USER locally.`);
  }
  const config = HOST_BY_ALIAS.get(alias);
  if (!config) {
    throw new Error(`Unsupported SSH host alias: ${alias}. Allowed aliases: ${HOST_ALIASES_DESCRIPTION}`);
  }
  return { alias, config };
}

function resolveCwd(config: HostConfig, rawCwd: unknown): string {
  const cwd = normalizeRemotePath(cleanSingleLine(rawCwd) || config.defaultCwd, config.user, config.homeDir);
  const allowedPrefixes = config.allowedCwdPrefixes.map((prefix) => normalizeRemotePath(prefix, config.user, config.homeDir));
  if (!allowedPrefixes.some((prefix) => isPathWithin(cwd, prefix))) {
    throw new Error(`cwd ${cwd} is outside the allowed SSH workspace for this host. Allowed prefixes: ${allowedPrefixes.join(", ")}`);
  }
  return cwd;
}

function formatSshOutput(stdout: string, stderr: string, metadata: string): string {
  const sections: string[] = [];
  if (stdout.trim()) sections.push(stdout.trimEnd());
  if (stderr.trim()) sections.push(`${stdout.trim() ? "--- stderr ---\n" : ""}${stderr.trimEnd()}`);
  if (sections.length === 0) sections.push("(no output)");
  sections.push(metadata);
  return sections.join("\n\n");
}

function formatDuration(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

function elapsedFooter(state: SshRenderState, isPartial: boolean, theme: any): string {
  if (state.startedAt === undefined) return "";
  const label = isPartial ? "Elapsed" : "Took";
  const endTime = state.endedAt ?? Date.now();
  const elapsedMs = Math.max(0, endTime - state.startedAt);
  return theme.fg("muted", `${label} ${formatDuration(elapsedMs)}`);
}

function resultContentText(content: unknown): string {
  if (!Array.isArray(content)) return "";
  return content
    .map((part) => {
      if (typeof part === "string") return part;
      if (part && typeof part === "object" && typeof (part as { text?: unknown }).text === "string") return (part as { text: string }).text;
      return "";
    })
    .filter(Boolean)
    .join("\n")
    .trim();
}

function previewOutput(text: string, maxLines = 8, maxChars = 1200): string {
  const lines = text
    .split("\n")
    .map((line) => line.trimEnd())
    .filter((line) => line.trim() && !line.startsWith("[ssh "));
  const preview = lines.slice(0, maxLines).join("\n");
  return preview.length > maxChars ? `${preview.slice(0, maxChars)}…` : preview;
}

function buildRemoteScript(cwd: string, command: string, shellType: string): string {
  if (shellType === "windows-cmd") {
    const winCwd = cwd.startsWith("/") ? cwd.replace(/^\//, "").replace(/\//g, "\\") : cwd;
    const safeCwd = winCwd.replace(/"/g, '\"');
    return `cd /d \"${safeCwd}\" || exit /b 1 & ${command}`;
  }
  // posix (bash/sh): cd || exit $?
  return [`cd ${shellQuote(cwd)} || exit $?`, command].join("\n");
}

function buildSshArgs(config: HostConfig, remoteScript: string, requestPty = false): string[] {
  const remote = `${config.user}@${config.hostName}`;
  // For Windows cmd.exe, wrap in double quotes instead of single quotes
  const remoteCmd = config.shellType === "windows-cmd"
    ? `"${remoteScript}"`
    : shellQuote(remoteScript);
  return [
    ...(requestPty ? ["-tt"] : []),
    "-i", config.identityFile,
    "-o", "IdentitiesOnly=yes",
    "-o", "BatchMode=yes",
    "-o", "NumberOfPasswordPrompts=0",
    "-o", `ConnectTimeout=${config.connectTimeoutSeconds ?? 8}`,
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=2",
    "-o", "LogLevel=ERROR",
    remote,
    `${config.shell} ${remoteCmd}`,
  ];
}

function configuredSessionIdleSeconds(): number {
  return positiveInteger(process.env.JARVIS_SSH_INTERACTIVE_IDLE_SECONDS, DEFAULT_SESSION_IDLE_SECONDS);
}

function configuredSessionOutputBytes(): number {
  return positiveInteger(process.env.JARVIS_SSH_INTERACTIVE_OUTPUT_BYTES, DEFAULT_SESSION_OUTPUT_BYTES);
}

function keepUtf8Tail(value: string, maxBytes: number): { text: string; truncated: boolean } {
  const bytes = Buffer.from(value, "utf8");
  if (bytes.length <= maxBytes) return { text: value, truncated: false };
  return {
    text: bytes.subarray(Math.max(0, bytes.length - maxBytes)).toString("utf8"),
    truncated: true,
  };
}

function stripTerminalOutput(value: string): string {
  return value
    .replace(/\u001b\][^\u0007]*(?:\u0007|\u001b\\)/g, "")
    .replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, "")
    .replace(/\u001b[()][0-2A-Z]/g, "")
    .replace(/\r/g, "")
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "")
    .trimEnd();
}

function touchInteractiveSession(session: InteractiveSession): void {
  session.lastActivityAt = Date.now();
  if (session.idleTimer) clearTimeout(session.idleTimer);
  session.idleTimer = setTimeout(() => {
    if (!INTERACTIVE_SESSIONS.has(session.id)) return;
    const idleMs = Date.now() - session.lastActivityAt;
    const limitMs = configuredSessionIdleSeconds() * 1000;
    if (idleMs >= limitMs) {
      closeInteractiveSession(session, "SIGHUP", true);
      return;
    }
    touchInteractiveSession(session);
  }, configuredSessionIdleSeconds() * 1000);
}

function appendInteractiveOutput(session: InteractiveSession, data: string): void {
  if (!data) return;
  session.outputBytes += Buffer.byteLength(data, "utf8");
  const maxBytes = configuredSessionOutputBytes();
  const output = keepUtf8Tail(`${session.output}${data}`, maxBytes);
  const pending = keepUtf8Tail(`${session.pendingOutput}${data}`, maxBytes);
  session.output = output.text;
  session.pendingOutput = pending.text;
  session.outputTruncated ||= output.truncated || pending.truncated;
}

function disposeSessionTerminal(session: InteractiveSession): void {
  if (session.terminalDisposed) return;
  session.terminalDisposed = true;
  session.terminal.dispose();
}

function closeInteractiveSession(session: InteractiveSession, signalName = "SIGHUP", remove = false): void {
  if (session.idleTimer) clearTimeout(session.idleTimer);
  if (session.timeoutTimer) clearTimeout(session.timeoutTimer);
  session.idleTimer = undefined;
  session.timeoutTimer = undefined;
  if (!session.exited) {
    try {
      session.pty.kill(signalName);
    } catch {
      // The PTY may already have exited between the state check and kill.
    }
  }
  if (remove) {
    INTERACTIVE_SESSIONS.delete(session.id);
    if (session.exited) disposeSessionTerminal(session);
  }
}

function sessionSummary(session: InteractiveSession): Record<string, unknown> {
  return {
    sessionId: session.id,
    host: session.alias,
    remote: session.remote,
    cwd: session.cwd,
    command: session.command,
    exited: session.exited,
    exitCode: session.exitCode ?? null,
    exitSignal: session.exitSignal ?? null,
    outputBytes: session.outputBytes,
    outputTruncated: session.outputTruncated,
    createdAt: new Date(session.createdAt).toISOString(),
    lastActivityAt: new Date(session.lastActivityAt).toISOString(),
  };
}

function sessionOutput(session: InteractiveSession, consume: boolean): string {
  const raw = consume ? session.pendingOutput : session.output;
  if (consume) session.pendingOutput = "";
  const screen = terminalScreen(session.terminal);
  const transcript = stripTerminalOutput(raw);
  if (screen) return `--- terminal screen (${session.terminal.cols}x${session.terminal.rows}) ---\n${screen}`;
  return transcript || "(no new output)";
}

function sessionStatusText(session: InteractiveSession, output: string): string {
  const state = session.exited
    ? `exited code=${session.exitCode ?? "unknown"}${session.exitSignal ? ` signal=${session.exitSignal}` : ""}`
    : "running";
  return [
    `SSH session ${session.id} ${state}`,
    output,
  ].join("\n\n");
}

function requireInteractiveSession(sessionId: unknown): InteractiveSession {
  const id = cleanSingleLine(sessionId);
  if (!id) throw new Error("sessionId is required");
  const session = INTERACTIVE_SESSIONS.get(id);
  if (!session) throw new Error(`Unknown SSH interactive session: ${id}`);
  return session;
}

function normalizeKeyInput(key: unknown): string {
  const normalized = cleanSingleLine(key).toUpperCase().replace(/[ -]+/g, "_");
  const value = SESSION_KEY_MAP[normalized];
  if (value === undefined) {
    throw new Error(`Unsupported SSH key ${normalized || "(empty)"}. Use raw input or a supported key such as ENTER, CTRL_C, ESC, UP, or LEFT.`);
  }
  return value;
}

function boundedDimension(value: unknown, fallback: number, name: string): number {
  if (value === undefined || value === null || value === "") return fallback;
  const number = Number(value);
  if (!Number.isFinite(number) || number < 1 || number > 1000) {
    throw new Error(`${name} must be a finite number between 1 and 1000`);
  }
  return Math.round(number);
}

async function waitForInteractiveStartup(session: InteractiveSession, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) {
    closeInteractiveSession(session, "SIGHUP", true);
    throw new Error("SSH interactive session startup was aborted");
  }
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, 150);
    const onAbort = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
      closeInteractiveSession(session, "SIGHUP", true);
      reject(new Error("SSH interactive session startup was aborted"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

function startInteractiveSession(
  alias: string,
  config: HostConfig,
  remote: string,
  cwd: string,
  command: string,
  sshArgs: string[],
  timeoutSeconds: number | undefined,
  cols: number,
  rows: number,
): InteractiveSession {
  const now = Date.now();
  const session: InteractiveSession = {
    id: `ssh-${randomUUID()}`,
    alias,
    description: config.description,
    remote,
    cwd,
    command,
    pty: spawnSshPty(sshArgs, { cols, rows }),
    terminal: createHeadlessTerminal(cols, rows),
    createdAt: now,
    lastActivityAt: now,
    output: "",
    pendingOutput: "",
    outputBytes: 0,
    outputTruncated: false,
    exited: false,
  };

  INTERACTIVE_SESSIONS.set(session.id, session);
  session.pty.onData((data) => {
    session.terminal.write(data);
    appendInteractiveOutput(session, data);
  });
  session.pty.onExit(({ exitCode, signal: exitSignal }) => {
    session.exited = true;
    session.exitCode = exitCode;
    session.exitSignal = exitSignal;
    if (session.timeoutTimer) clearTimeout(session.timeoutTimer);
    session.timeoutTimer = undefined;
    if (INTERACTIVE_SESSIONS.has(session.id)) touchInteractiveSession(session);
    else disposeSessionTerminal(session);
  });
  touchInteractiveSession(session);

  if (timeoutSeconds !== undefined) {
    session.timeoutTimer = setTimeout(() => {
      if (!session.exited) closeInteractiveSession(session, "SIGTERM", false);
    }, timeoutSeconds * 1000);
  }

  return session;
}

async function executeInteractiveSessionAction(rawParams: SshParams) {
  const action = rawParams.action;
  if (action === "list") {
    const sessions = [...INTERACTIVE_SESSIONS.values()].map(sessionSummary);
    return {
      content: [{ type: "text" as const, text: sessions.length ? JSON.stringify(sessions, null, 2) : "(no SSH interactive sessions)" }],
      details: { ok: true, action, sessions },
    };
  }

  const session = requireInteractiveSession(rawParams.sessionId);
  touchInteractiveSession(session);

  if (action === "input") {
    if (session.exited) throw new Error(`SSH interactive session ${session.id} has already exited`);
    const pieces: string[] = [];
    if (rawParams.input !== undefined) pieces.push(String(rawParams.input));
    if (rawParams.key !== undefined) pieces.push(normalizeKeyInput(rawParams.key));
    if (!pieces.length) throw new Error("input or key is required for SSH interactive input");
    session.pty.write(pieces.join(""));
    return {
      content: [{ type: "text" as const, text: `Sent input to SSH session ${session.id}.` }],
      details: { ok: true, action, ...sessionSummary(session), inputBytes: Buffer.byteLength(pieces.join(""), "utf8") },
    };
  }

  if (action === "read") {
    const consume = rawParams.consume !== false;
    const output = sessionOutput(session, consume);
    return {
      content: [{ type: "text" as const, text: sessionStatusText(session, output) }],
      details: { ok: true, action, ...sessionSummary(session), consume, output },
    };
  }

  if (action === "resize") {
    const cols = boundedDimension(rawParams.cols, session.pty.cols, "cols");
    const rows = boundedDimension(rawParams.rows, session.pty.rows, "rows");
    session.pty.resize(cols, rows);
    session.terminal.resize(cols, rows);
    return {
      content: [{ type: "text" as const, text: `Resized SSH session ${session.id} to ${cols}x${rows}.` }],
      details: { ok: true, action, ...sessionSummary(session), cols, rows },
    };
  }

  if (action === "signal") {
    const signalName = cleanSingleLine(rawParams.signalName) || "SIGINT";
    if (signalName === "SIGINT") session.pty.write("\x03");
    else session.pty.kill(signalName);
    return {
      content: [{ type: "text" as const, text: `Sent ${signalName} to SSH session ${session.id}.` }],
      details: { ok: true, action, ...sessionSummary(session), signal: signalName },
    };
  }

  if (action === "close") {
    const output = sessionOutput(session, true);
    closeInteractiveSession(session, cleanSingleLine(rawParams.signalName) || "SIGHUP", true);
    return {
      content: [{ type: "text" as const, text: `Closed SSH session ${session.id}.\n\n${output}` }],
      details: { ok: true, action, ...sessionSummary(session), output },
    };
  }

  throw new Error(`Unsupported SSH interactive action: ${action || "(empty)"}`);
}

async function executeAttachedSsh(
  ctx: ExtensionContext,
  sshArgs: string[],
  timeoutSeconds: number | undefined,
  signal?: AbortSignal,
): Promise<{ exitCode: number | null; killed: boolean; signal?: string }> {
  if (ctx.mode !== "tui") {
    throw new Error("pty:true requires local Pi TUI mode. In Discord/RPC use action:'start', then action:'input' and action:'read'.");
  }

  return ctx.ui.custom((tui, _theme, _keybindings, done) => {
    let finished = false;
    let killed = false;
    let timeoutId: ReturnType<typeof setTimeout> | undefined;
    let forceKillId: ReturnType<typeof setTimeout> | undefined;
    let child: ReturnType<typeof spawn>;

    const restoreTui = () => {
      try {
        tui.start();
        tui.requestRender(true);
      } catch {
        // The parent TUI may already be shutting down.
      }
    };
    const finish = (result: { exitCode: number | null; killed: boolean; signal?: string }) => {
      if (finished) return;
      finished = true;
      if (timeoutId) clearTimeout(timeoutId);
      if (forceKillId) clearTimeout(forceKillId);
      signal?.removeEventListener("abort", onAbort);
      restoreTui();
      done(result);
    };
    const terminate = () => {
      if (finished || child?.killed) return;
      killed = true;
      child.kill("SIGTERM");
      forceKillId = setTimeout(() => {
        if (!finished) child.kill("SIGKILL");
      }, 2_000);
    };
    const onAbort = () => terminate();

    tui.stop();
    process.stdout.write("\x1b[2J\x1b[H");
    try {
      child = spawn("ssh", sshArgs, { stdio: "inherit" });
    } catch {
      finish({ exitCode: 1, killed });
      return { render: () => [], invalidate: () => {} };
    }
    child.once("error", () => finish({ exitCode: 1, killed }));
    child.once("close", (code, signalName) => finish({ exitCode: typeof code === "number" ? code : null, killed, signal: signalName ?? undefined }));
    signal?.addEventListener("abort", onAbort, { once: true });
    if (timeoutSeconds !== undefined) timeoutId = setTimeout(terminate, timeoutSeconds * 1000);

    return { render: () => [], invalidate: () => {} };
  });
}

async function executeSsh(
  pi: ExtensionAPI,
  rawParams: SshParams,
  signal?: AbortSignal,
  onUpdate?: (partial: any) => void,
  ctx?: ExtensionContext,
): Promise<any> {
  const action: SshAction = rawParams.action ?? "exec";
  if (["input", "read", "resize", "signal", "close", "list"].includes(action)) {
    return executeInteractiveSessionAction({ ...rawParams, action });
  }
  if (action !== "exec" && action !== "start") throw new Error(`Unsupported SSH action: ${action}`);

  const { alias, config } = resolveHost(rawParams.host);
  const cwd = resolveCwd(config, rawParams.cwd);
  const command = cleanCommand(rawParams.command);
  const timeoutSeconds = optionalPositiveInteger(rawParams.timeoutSeconds) ?? DEFAULT_TIMEOUT_SECONDS;
  const remoteScript = buildRemoteScript(cwd, command, config.shellType);
  const requestPty = action === "start" || rawParams.pty === true;
  const sshArgs = buildSshArgs(config, remoteScript, requestPty);
  const remote = `${config.user}@${config.hostName}`;

  if (rawParams.dryRun) {
    return {
      content: [{
        type: "text" as const,
        text: [
          "Dry run: ssh",
          `action: ${action}`,
          `pty: ${requestPty}`,
          `host: ${alias} (${config.description})`,
          `remote: ${remote}`,
          `cwd: ${cwd}`,
          `timeout: ${timeoutSeconds === undefined ? "none" : `${timeoutSeconds}s`}`,
          "command:",
          command,
        ].join("\n"),
      }],
      details: { ok: true, dryRun: true, action, pty: requestPty, host: alias, remote, cwd, command, timeoutSeconds },
    };
  }

  if (action === "start") {
    const cols = boundedDimension(rawParams.cols, DEFAULT_SESSION_COLS, "cols");
    const rows = boundedDimension(rawParams.rows, DEFAULT_SESSION_ROWS, "rows");
    onUpdate?.({ content: [{ type: "text" as const, text: `Starting interactive SSH session on ${alias} (${remote})...` }] });
    const session = startInteractiveSession(alias, config, remote, cwd, command, sshArgs, timeoutSeconds, cols, rows);
    await waitForInteractiveStartup(session, signal);
    const output = sessionOutput(session, true);
    const ok = !session.exited || session.exitCode === 0;
    const text = [
      session.exited
        ? `SSH interactive session ${session.id} exited during startup with code ${session.exitCode ?? "unknown"}.`
        : `Started SSH interactive session ${session.id} on ${alias} (${remote}).`,
      !session.exited ? `Use ssh action input/read/resize/signal/close with sessionId ${session.id}.` : undefined,
      output !== "(no new output)" ? output : undefined,
    ].filter(Boolean).join("\n\n");
    return {
      content: [{ type: "text" as const, text }],
      details: { ok, action, pty: true, ...sessionSummary(session), cols, rows, output },
    };
  }

  if (rawParams.pty === true) {
    if (!ctx) throw new Error("SSH PTY execution context is unavailable");
    onUpdate?.({ content: [{ type: "text" as const, text: `Attaching terminal to ${alias} (${remote})...` }] });
    const result = await executeAttachedSsh(ctx, sshArgs, timeoutSeconds, signal);
    const ok = result.exitCode === 0 && !result.killed;
    const metadata = `[ssh pty=true host=${alias} remote=${remote} cwd=${cwd} exit=${result.exitCode ?? "unknown"}${result.killed ? " killed=true" : ""}]`;
    return {
      content: [{ type: "text" as const, text: `Interactive SSH terminal closed.\n\n${metadata}` }],
      details: { ok, action, pty: true, host: alias, remote, cwd, command, timeoutSeconds, ...result },
    };
  }

  onUpdate?.({ content: [{ type: "text" as const, text: `Connecting to ${alias} (${remote})...` }] });
  const execOptions = timeoutSeconds === undefined
    ? { signal }
    : { signal, timeout: timeoutSeconds * 1000 };
  const result = await pi.exec("ssh", sshArgs, execOptions);
  const exitCode = typeof result.code === "number" ? result.code : null;
  const killed = Boolean((result as any).killed);
  const stdout = String(result.stdout ?? "");
  const stderr = String(result.stderr ?? "");
  const ok = exitCode === 0 && !killed;
  const metadata = `[ssh host=${alias} remote=${remote} cwd=${cwd} exit=${exitCode ?? "unknown"}${killed ? " killed=true" : ""}]`;
  const output = formatSshOutput(stdout, stderr, metadata);
  const outputBytes = Buffer.byteLength(output, "utf8");

  return {
    content: [{ type: "text" as const, text: output }],
    details: {
      ok,
      action,
      pty: false,
      host: alias,
      remote,
      cwd,
      command,
      timeoutSeconds,
      exitCode,
      killed,
      stdoutBytes: Buffer.byteLength(stdout, "utf8"),
      stderrBytes: Buffer.byteLength(stderr, "utf8"),
      totalOutputBytes: outputBytes,
      outputBytes,
      truncated: false,
    },
  };
}

export default function registerSsh(pi: ExtensionAPI) {
  pi.registerTool({
    name: "ssh",
    label: "SSH",
    description: `Run unrestricted commands over SSH on a trusted named host, including interactive terminal programs. Current aliases: ${HOST_ALIASES_DESCRIPTION}. Defaults to ${DEFAULT_HOST_DESCRIPTION}. Use action exec for captured commands, pty:true for a directly attached local TUI terminal, or stateful start/input/read/resize/signal/close actions for Discord/RPC interactive sessions.`,
    promptSnippet: "Run unrestricted SSH commands, or manage a stateful interactive SSH PTY session.",
    promptGuidelines: [
      "Use ssh instead of raw `bash` SSH when administering configured trusted hosts; it pins the host, user, key, and allowed cwd.",
      "Command content is unrestricted. action:'exec' captures a command to completion. In local Pi TUI, pty:true attaches the real terminal for editors, pagers, tmux, sudo prompts, and live UIs.",
      "In Discord/RPC, use action:'start' with command to create a stateful PTY, then action:'read', action:'input' with input and/or key, action:'resize', action:'signal', and action:'close' using the returned sessionId.",
      "For line input, send input plus key:'ENTER'. Supported named keys include ENTER, TAB, ESC, arrows, BACKSPACE, CTRL_C, CTRL_D, CTRL_Z, and CTRL_L.",
      "Use minecraft_jarvis, not ssh, when the user wants to talk to or command an in-game Minecraft jarvis bot in plain language.",
      "Never use ssh to start, stop, or restart long-running services unless sir explicitly asks in that moment.",
    ],
    parameters: Type.Object({
      action: Type.Optional(Type.Union([
        Type.Literal("exec"), Type.Literal("start"), Type.Literal("input"), Type.Literal("read"),
        Type.Literal("resize"), Type.Literal("signal"), Type.Literal("close"), Type.Literal("list"),
      ], { description: "SSH action. Defaults to exec." })),
      host: Type.Optional(Type.String({ description: `Trusted host alias. Defaults to ${DEFAULT_HOST_DESCRIPTION}. Allowed: ${HOST_ALIASES_DESCRIPTION}.` })),
      command: Type.Optional(Type.String({ description: "Unrestricted remote command. Required for exec/start." })),
      cwd: Type.Optional(Type.String({ description: "Remote working directory. Defaults to the host's configured defaultCwd and must stay inside configured allowedCwdPrefixes." })),
      timeoutSeconds: Type.Optional(Type.Number({ description: "Optional command/session lifetime in seconds. If omitted, no execution timeout is applied." })),
      dryRun: Type.Optional(Type.Boolean({ description: "Resolve an exec/start request without executing it." })),
      pty: Type.Optional(Type.Boolean({ description: "For action exec in local TUI only: attach the real terminal using ssh -tt." })),
      sessionId: Type.Optional(Type.String({ description: "Interactive session ID returned by action start." })),
      input: Type.Optional(Type.String({ description: "Raw text/escape input for action input. Preserved exactly." })),
      key: Type.Optional(Type.String({ description: "Named key for action input, e.g. ENTER, CTRL_C, ESC, UP, LEFT." })),
      cols: Type.Optional(Type.Number({ description: "PTY columns for start/resize (1-1000)." })),
      rows: Type.Optional(Type.Number({ description: "PTY rows for start/resize (1-1000)." })),
      signalName: Type.Optional(Type.String({ description: "Signal for signal/close. signal defaults SIGINT; close defaults SIGHUP." })),
      consume: Type.Optional(Type.Boolean({ description: "For read: consume pending output (default true); false returns retained output." })),
    }),
    async execute(_toolCallId, rawParams, signal, onUpdate, ctx) {
      return executeSsh(pi, rawParams as SshParams, signal, onUpdate, ctx);
    },
    renderCall(args, theme, context) {
      const state = context.state as SshRenderState;
      if (context.executionStarted && state.startedAt === undefined) {
        state.startedAt = Date.now();
        state.endedAt = undefined;
      }
      const host = typeof args.host === "string" && args.host.trim() ? args.host.trim() : DEFAULT_HOST_DESCRIPTION;
      const action = typeof args.action === "string" ? args.action : "exec";
      const command = typeof args.command === "string" ? args.command.trim() : "";
      const sessionId = typeof args.sessionId === "string" ? args.sessionId.trim() : "";
      const display = command || sessionId || "...";
      const text = context.lastComponent instanceof Text ? context.lastComponent : new Text("", 0, 0);
      text.setText(`${theme.fg("toolTitle", `ssh ${action}`)} ${theme.fg("muted", host)} ${theme.fg("toolOutput", display)}`);
      return text;
    },
    renderResult(result, options, theme, context) {
      const state = context.state as SshRenderState;
      if (state.startedAt !== undefined && options.isPartial && !state.interval) {
        state.interval = setInterval(() => context.invalidate(), 1000);
      }
      if (!options.isPartial || context.isError) {
        state.endedAt ??= Date.now();
        if (state.interval) {
          clearInterval(state.interval);
          state.interval = undefined;
        }
      }

      const details = result.details as any;
      const isDryRun = details?.dryRun === true;
      const ok = details?.ok === true;
      const host = typeof details?.host === "string"
        ? details.host
        : typeof context.args.host === "string" && context.args.host.trim()
          ? context.args.host.trim()
          : DEFAULT_HOST_DESCRIPTION;
      const code = details?.exitCode ?? "?";
      const truncated = details?.truncated ? " truncated" : "";
      const label = options.isPartial
        ? theme.fg("toolTitle", "ssh")
        : ok
          ? theme.fg("success", "✓ ssh")
          : theme.fg("warning", "ssh exit");
      const status = options.isPartial
        ? "running"
        : isDryRun
          ? "dry-run"
          : `code=${code}${truncated}`;
      const header = `${label} ${theme.fg("muted", host)} ${theme.fg("dim", status)}`;
      const output = resultContentText(result.content);
      const footer = elapsedFooter(state, options.isPartial, theme);
      const lines = [header];
      if (output) {
        if (options.expanded) lines.push(output);
        else {
          const preview = previewOutput(output);
          if (preview) lines.push(theme.fg("dim", preview));
        }
      }
      if (footer) lines.push(footer);

      const text = context.lastComponent instanceof Text ? context.lastComponent : new Text("", 0, 0);
      text.setText(lines.join("\n"));
      return text;
    },
  });

  pi.on("session_shutdown", () => {
    for (const session of INTERACTIVE_SESSIONS.values()) closeInteractiveSession(session, "SIGHUP", true);
  });

  pi.registerCommand("ssh-hosts", {
    description: "List trusted ssh host aliases.",
    handler: async (_args, ctx) => {
      const lines = HOST_CONFIGS.map((config) => `- ${config.aliases.join(", ")} -> ${config.user}@${config.hostName}, cwd ${config.defaultCwd}, allowed ${config.allowedCwdPrefixes.join(", ")}`);
      ctx.ui.notify(`ssh hosts:\n${lines.join("\n")}`, "info");
    },
  });
}
