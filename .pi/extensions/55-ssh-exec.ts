import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join, posix as pathPosix } from "node:path";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

type SshParams = {
  host?: string;
  command: string;
  cwd?: string;
  timeoutSeconds?: number;
  dryRun?: boolean;
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
  const blocked = blockedCommandReason(command);
  if (blocked) throw new Error(blocked);
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

function blockedCommandReason(command: string): string | undefined {
  const compact = command.replace(/\\\n/g, " ").replace(/\s+/g, " ").trim();
  if (/\bsudo\b/i.test(compact)) return "ssh is non-interactive and does not run sudo/password prompts. Use a non-sudo command or ask sir for an explicit privileged workflow.";
  if (/\bscreen\s+-(?:r|x|R|D?R)\b/i.test(compact) || /\btmux\s+(?:attach|a|new-session\s+-A)\b/i.test(compact)) {
    return "ssh is non-interactive; do not attach to screen/tmux sessions. Use status scripts, one-shot commands, or log tails instead.";
  }
  if (/\b(?:vi|vim|nvim|nano|emacs|less|more|top|htop|watch)\b/i.test(compact)) {
    return "ssh is non-interactive; do not launch editors, pagers, or live terminal UIs.";
  }
  if (/\btail\b(?=[^;&|]*\s-f\b)/i.test(compact)) return "ssh is non-interactive; use a finite tail such as `tail -n 80 file`, not `tail -f`.";
  if (/\brm\s+(-[A-Za-z]*r[A-Za-z]*f|-rf|-fr)\s+(?:\/(?:\s|$)|~(?:\s|\/|$)|\$HOME(?:\s|\/|$)|\*)/i.test(compact)) {
    return "Refusing a broad rm -rf target over SSH.";
  }
  return undefined;
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

function buildSshArgs(config: HostConfig, remoteScript: string): string[] {
  const remote = `${config.user}@${config.hostName}`;
  // For Windows cmd.exe, wrap in double quotes instead of single quotes
  const remoteCmd = config.shellType === "windows-cmd"
    ? `"${remoteScript}"`
    : shellQuote(remoteScript);
  return [
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

async function executeSsh(pi: ExtensionAPI, rawParams: SshParams, signal?: AbortSignal, onUpdate?: (partial: any) => void) {
  const { alias, config } = resolveHost(rawParams.host);
  const cwd = resolveCwd(config, rawParams.cwd);
  const command = cleanCommand(rawParams.command);
  const timeoutSeconds = optionalPositiveInteger(rawParams.timeoutSeconds) ?? DEFAULT_TIMEOUT_SECONDS;
  const remoteScript = buildRemoteScript(cwd, command, config.shellType);
  const sshArgs = buildSshArgs(config, remoteScript);
  const remote = `${config.user}@${config.hostName}`;

  if (rawParams.dryRun) {
    return {
      content: [{
        type: "text" as const,
        text: [
          `Dry run: ssh`,
          `host: ${alias} (${config.description})`,
          `remote: ${remote}`,
          `cwd: ${cwd}`,
          `timeout: ${timeoutSeconds === undefined ? "none" : `${timeoutSeconds}s`}`,
          "command:",
          command,
        ].join("\n"),
      }],
      details: { ok: true, dryRun: true, host: alias, remote, cwd, command, timeoutSeconds },
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
    description: `Run a non-interactive shell command over SSH on a trusted named host. Current aliases: ${HOST_ALIASES_DESCRIPTION}. Defaults to ${DEFAULT_HOST_DESCRIPTION}. By default no execution timeout is applied; pass timeoutSeconds to set one. Returns complete captured stdout/stderr with no tool-imposed output byte cap.`,
    promptSnippet: "Run non-interactive SSH commands on configured trusted hosts. ssh({ command: 'hostname' }).",
    promptGuidelines: [
      "Use ssh instead of raw `bash` SSH when administering configured trusted hosts; it pins the host, user, key, and cwd, and supports an optional timeoutSeconds value.",
      "Use ssh only for non-interactive commands that are expected to complete. Do not attach to screen/tmux, launch editors/pagers/live monitors, or rely on password prompts/sudo.",
      "Use minecraft_jarvis, not ssh, when the user wants to talk to or command an in-game Minecraft jarvis bot in plain language.",
      "For project-specific remote maintenance, prefer documented one-shot scripts on the configured host instead of interactive shells.",
      "Never use ssh to start, stop, or restart long-running services unless sir explicitly asks in that moment.",
    ],
    parameters: Type.Object({
      host: Type.Optional(Type.String({ description: `Trusted host alias. Defaults to ${DEFAULT_HOST_DESCRIPTION}. Allowed: ${HOST_ALIASES_DESCRIPTION}.` })),
      command: Type.String({ description: "Non-interactive shell command to run remotely. No tool-imposed command character cap; avoid sudo, screen/tmux attach, editors, pagers, and tail -f." }),
      cwd: Type.Optional(Type.String({ description: "Remote working directory. Defaults to the host's configured defaultCwd and must stay inside configured allowedCwdPrefixes." })),
      timeoutSeconds: Type.Optional(Type.Number({ description: "Optional execution timeout in seconds. If omitted, no SSH tool timeout is applied. Must be at least 1 when provided; no maximum is imposed by this tool." })),
      dryRun: Type.Optional(Type.Boolean({ description: "If true, show the resolved host/cwd/command without executing it." })),
    }),
    async execute(_toolCallId, rawParams, signal, onUpdate) {
      return executeSsh(pi, rawParams as SshParams, signal, onUpdate);
    },
    renderCall(args, theme, context) {
      const state = context.state as SshRenderState;
      if (context.executionStarted && state.startedAt === undefined) {
        state.startedAt = Date.now();
        state.endedAt = undefined;
      }
      const host = typeof args.host === "string" && args.host.trim() ? args.host.trim() : DEFAULT_HOST_DESCRIPTION;
      const command = typeof args.command === "string" ? args.command.trim() : "";
      const commandDisplay = command || "...";
      const text = context.lastComponent instanceof Text ? context.lastComponent : new Text("", 0, 0);
      text.setText(`${theme.fg("toolTitle", "ssh")} ${theme.fg("muted", host)} ${theme.fg("toolOutput", `$ ${commandDisplay}`)}`);
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

      const isDryRun = result.details?.dryRun === true;
      const ok = result.details?.ok === true;
      const host = typeof result.details?.host === "string"
        ? result.details.host
        : typeof context.args.host === "string" && context.args.host.trim()
          ? context.args.host.trim()
          : DEFAULT_HOST_DESCRIPTION;
      const code = result.details?.exitCode ?? "?";
      const truncated = result.details?.truncated ? " truncated" : "";
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

  pi.registerCommand("ssh-hosts", {
    description: "List trusted ssh host aliases.",
    handler: async (_args, ctx) => {
      const lines = HOST_CONFIGS.map((config) => `- ${config.aliases.join(", ")} -> ${config.user}@${config.hostName}, cwd ${config.defaultCwd}, allowed ${config.allowedCwdPrefixes.join(", ")}`);
      ctx.ui.notify(`ssh hosts:\n${lines.join("\n")}`, "info");
    },
  });
}
