import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

import { StringEnum } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

const ACTIONS = ["search", "remember", "update", "forget", "list", "status"] as const;
const KINDS = ["preference", "fact", "lesson", "project", "workflow"] as const;
const SCOPES = ["global", "project", "discord-channel"] as const;

function findAncestorFile(startDir: string, fileName: string): string | undefined {
  let current = resolve(startDir);
  while (true) {
    const candidate = join(current, fileName);
    if (existsSync(candidate)) return candidate;
    const parent = dirname(current);
    if (parent === current) return undefined;
    current = parent;
  }
}

function parseDotEnv(envPath: string | undefined): Record<string, string> {
  if (!envPath) return {};
  const values: Record<string, string> = {};
  let text = "";
  try {
    text = readFileSync(envPath, "utf8");
  } catch {
    return values;
  }
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const match = line.match(/^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (!match) continue;
    let value = match[2].trim();
    if (value.length >= 2 && value.startsWith('"') && value.endsWith('"')) {
      value = value.slice(1, -1).replace(/\\n/g, "\n").replace(/\\r/g, "\r").replace(/\\t/g, "\t").replace(/\\"/g, '"').replace(/\\\\/g, "\\");
    } else if (value.length >= 2 && value.startsWith("'") && value.endsWith("'")) {
      value = value.slice(1, -1);
    } else {
      value = value.replace(/\s+#.*$/, "");
    }
    values[match[1]] = value;
  }
  return values;
}

function runnerPath(cwd: string): string {
  return findAncestorFile(cwd, ".pi/memory/memory.py") ?? join(cwd, ".pi", "memory", "memory.py");
}

function projectRoot(cwd: string): string {
  const runner = runnerPath(cwd);
  return dirname(dirname(dirname(runner)));
}

function pythonPath(cwd: string): string {
  const root = projectRoot(cwd);
  const env = parseDotEnv(findAncestorFile(cwd, ".env"));
  if (env.PI_PYTHON) return resolve(root, env.PI_PYTHON);
  const venvPython = join(root, ".venv", "bin", "python");
  if (existsSync(venvPython)) return venvPython;
  return "python3";
}

function discordChannelId(): string {
  return process.env.JARVIS_DISCORD_CHANNEL_ID?.trim() || "";
}

function truncate(text: string, max = 12000): string {
  return text.length > max ? `${text.slice(0, max)}\n… truncated …` : text;
}

function memoryLine(memory: any): string {
  const tags = Array.isArray(memory.tags) && memory.tags.length ? ` tags=${memory.tags.join(",")}` : "";
  const deleted = memory.deleted_at ? " [deleted]" : "";
  return `${memory.id} [${memory.kind}/${memory.scope}] ${memory.text}${tags}${deleted}`;
}

function formatResult(result: any): string {
  if (!result) return "No output";
  if (result.ok === false) return `Error: ${result.error ?? "memory command failed"}`;
  if (result.message) return String(result.message);
  if (Array.isArray(result.results)) {
    if (result.results.length === 0) return result.query ? `No memories found for: ${result.query}` : "No memories found.";
    const prefix = result.query ? `Memories for: ${result.query}` : "Memories";
    return truncate([prefix, ...result.results.map(memoryLine)].join("\n"));
  }
  if (result.memory) return memoryLine(result.memory);
  if (typeof result.active_memories === "number") {
    return [
      `Memory: ${result.active_memories} active, ${result.deleted_memories} deleted, ${result.events} events`,
      `DB: ${result.db_path}`,
      `By kind: ${JSON.stringify(result.by_kind ?? {})}`,
      `By scope: ${JSON.stringify(result.by_scope ?? {})}`,
    ].join("\n");
  }
  return JSON.stringify(result, null, 2);
}

function buildArgs(params: any, ctxCwd: string): string[] {
  const runner = runnerPath(ctxCwd);
  const args = [runner, "--json", params.action];

  if (params.action === "search") {
    if (!params.query) throw new Error("memory search requires query");
    args.push(params.query);
    if (params.limit) args.push("--limit", String(params.limit));
    if (params.kind) args.push("--kind", params.kind);
    if (params.scope) args.push("--scope", params.scope);
    if (params.includeDeleted) args.push("--include-deleted");
  } else if (params.action === "remember") {
    if (!params.text) throw new Error("memory remember requires text");
    args.push("--text", params.text);
    if (params.kind) args.push("--kind", params.kind);
    if (params.tags?.length) args.push("--tags", Array.isArray(params.tags) ? params.tags.join(",") : String(params.tags));
    if (params.scope) args.push("--scope", params.scope);
    if (params.confidence !== undefined) args.push("--confidence", String(params.confidence));
    if (params.source) args.push("--source", params.source);
    args.push("--cwd", ctxCwd);
    const channelId = discordChannelId();
    if (channelId) args.push("--discord-channel-id", channelId);
  } else if (params.action === "update") {
    if (!params.id) throw new Error("memory update requires id");
    args.push("--id", params.id);
    if (params.text !== undefined) args.push("--text", params.text);
    if (params.kind) args.push("--kind", params.kind);
    if (params.tags !== undefined) args.push("--tags", Array.isArray(params.tags) ? params.tags.join(",") : String(params.tags));
    if (params.scope) args.push("--scope", params.scope);
    if (params.confidence !== undefined) args.push("--confidence", String(params.confidence));
  } else if (params.action === "forget") {
    if (!params.id) throw new Error("memory forget requires id");
    args.push("--id", params.id);
  } else if (params.action === "list") {
    if (params.limit) args.push("--limit", String(params.limit));
    if (params.kind) args.push("--kind", params.kind);
    if (params.scope) args.push("--scope", params.scope);
    if (params.includeDeleted) args.push("--include-deleted");
  }

  return args;
}

async function runMemory(pi: ExtensionAPI, cwd: string, args: string[], signal?: AbortSignal, timeout = 30_000): Promise<any> {
  const runner = runnerPath(cwd);
  if (!existsSync(runner)) throw new Error(`Memory runner not found: ${runner}`);
  const result = await pi.exec(pythonPath(cwd), args, { signal, timeout });
  const raw = result.stdout.trim() || result.stderr.trim();
  let parsed: any;
  try {
    parsed = JSON.parse(raw);
  } catch {
    parsed = { ok: result.code === 0, message: raw, stderr: result.stderr };
  }
  if (result.code !== 0 || parsed?.ok === false) {
    throw new Error(parsed?.error || result.stderr || raw || "memory command failed");
  }
  return parsed;
}

export default function registerMemory(pi: ExtensionAPI) {
  pi.registerTool({
    name: "memory",
    label: "Memory",
    description:
      "Single action-dispatched project-local durable memory tool: search/remember/update/forget/list/status. Never store secrets or sensitive personal data.",
    promptSnippet: "Use memory with action=search/remember/update/forget/list/status",
    promptGuidelines: [
      "Use the single memory tool with the appropriate action; search memory when durable preferences/facts may matter; remember only explicit/stable safe info; never store secrets/sensitive data; forget on request.",
    ],
    parameters: Type.Object({
      action: StringEnum(ACTIONS, { description: "Operation." }),
      query: Type.Optional(Type.String({ description: "Search query." })),
      id: Type.Optional(Type.String({ description: "Memory id." })),
      kind: Type.Optional(StringEnum(KINDS, { description: "Kind." })),
      text: Type.Optional(Type.String({ description: "Memory text." })),
      tags: Type.Optional(Type.Array(Type.String({ description: "Tags." }))),
      scope: Type.Optional(StringEnum(SCOPES, { description: "Scope." })),
      confidence: Type.Optional(Type.Number({ description: "0..1 confidence." })),
      source: Type.Optional(Type.String({ description: "Source note." })),
      limit: Type.Optional(Type.Number({ description: "Result limit." })),
      includeDeleted: Type.Optional(Type.Boolean({ description: "Include deleted." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const args = buildArgs(params, ctx.cwd);
      const parsed = await runMemory(pi, ctx.cwd, args, signal);
      return {
        content: [{ type: "text" as const, text: formatResult(parsed) }],
        details: parsed,
      };
    },
    renderCall(args, theme) {
      const target = args.query || args.id || args.kind || "";
      return new Text(`${theme.fg("toolTitle", "memory")} ${theme.fg("accent", args.action ?? "")} ${theme.fg("muted", target)}`, 0, 0);
    },
    renderResult(result, _options, theme) {
      const text = result.details?.ok === false ? theme.fg("error", formatResult(result.details)) : theme.fg("success", formatResult(result.details));
      return new Text(truncate(text, 4000), 0, 0);
    },
  });

  pi.on("before_agent_start", async (event, ctx) => {
    const runner = runnerPath(ctx.cwd);
    if (!existsSync(runner)) return;
    const env = parseDotEnv(findAncestorFile(ctx.cwd, ".env"));
    const disabled = (env.JARVIS_MEMORY_AUTO_RECALL ?? process.env.JARVIS_MEMORY_AUTO_RECALL ?? "1").trim() === "0";
    if (disabled) return;

    try {
      const limit = Number(env.JARVIS_MEMORY_RECALL_LIMIT ?? process.env.JARVIS_MEMORY_RECALL_LIMIT ?? 3) || 3;
      const maxChars = Number(env.JARVIS_MEMORY_RECALL_MAX_CHARS ?? process.env.JARVIS_MEMORY_RECALL_MAX_CHARS ?? 1500) || 1500;
      const args = [runner, "--json", "recall", event.prompt, "--limit", String(limit), "--max-chars", String(maxChars)];
      const parsed = await runMemory(pi, ctx.cwd, args, ctx.signal, 5_000);
      const block = typeof parsed.block === "string" ? parsed.block.trim() : "";
      if (!block) return;
      return { systemPrompt: `${event.systemPrompt}\n\n${block}\n` };
    } catch {
      return;
    }
  });

  pi.registerCommand("memory", {
    description: "Manage project-local JARVIS memory. Usage: /memory status | search <query> | list | remember <text>",
    handler: async (args, ctx) => {
      const trimmed = args.trim();
      const parts = trimmed ? trimmed.split(/\s+/) : ["status"];
      const command = parts.shift() ?? "status";
      let cliArgs: string[];
      if (command === "search") {
        cliArgs = [runnerPath(ctx.cwd), "--json", "search", parts.join(" ")];
      } else if (command === "remember") {
        const text = parts.join(" ").trim();
        if (!text) {
          ctx.ui.notify("Usage: /memory remember <text>", "error");
          return;
        }
        cliArgs = [runnerPath(ctx.cwd), "--json", "remember", "--text", text, "--kind", "fact", "--source", "user", "--cwd", ctx.cwd];
      } else if (["status", "list"].includes(command)) {
        cliArgs = [runnerPath(ctx.cwd), "--json", command, ...parts];
      } else {
        ctx.ui.notify("Usage: /memory status | search <query> | list | remember <text>", "error");
        return;
      }
      const parsed = await runMemory(pi, ctx.cwd, cliArgs, undefined, 30_000);
      ctx.ui.notify(formatResult(parsed).slice(0, 4000), "info");
    },
  });
}
