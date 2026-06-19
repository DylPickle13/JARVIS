import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

import { StringEnum } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

const ACTIONS = ["search", "status", "index", "install_cron", "uninstall_cron"] as const;

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
  for (const raw of readFileSync(envPath, "utf8").split(/\r?\n/)) {
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
  return findAncestorFile(cwd, ".pi/session-search/session_search.py") ?? join(cwd, ".pi", "session-search", "session_search.py");
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

function actionToCommand(action: string): string {
  return action.replace(/_/g, "-");
}

function truncate(text: string, max = 14000): string {
  return text.length > max ? `${text.slice(0, max)}\n… truncated …` : text;
}

function formatResult(result: any): string {
  if (!result) return "No output";
  if (result.ok === false) return `Error: ${result.error ?? "session_search failed"}`;
  if (Array.isArray(result.results)) {
    if (result.results.length === 0) return `No session-search results for: ${result.query}`;
    const lines = [`Session search results for: ${result.query}`];
    for (const item of result.results) {
      const where = `${item.session_file ?? item.session_path} chunk ${item.chunk_index} lines ${(item.line_range ?? []).join("-")}`;
      lines.push(`\n[${item.score}] ${where}\n${item.text ?? ""}`);
    }
    return truncate(lines.join("\n"));
  }
  if (typeof result.pending_files === "number") {
    return `Session search index status: ${result.indexed_files}/${result.session_files} files indexed, ${result.pending_files} pending, ${result.changed_files} changed, ${result.chunks} chunks, ${result.embeddings} embeddings.\nDB: ${result.db_path}\nModel: ${result.model}\nEndpoint: ${result.endpoint}`;
  }
  if (typeof result.indexed_files === "number") {
    return `Session index: ${result.indexed_files} files / ${result.indexed_chunks ?? 0} chunks indexed, ${result.skipped_files ?? 0} skipped, ${result.removed_files ?? 0} removed in ${result.duration_seconds ?? "?"}s.`;
  }
  if (result.message) return String(result.message);
  return JSON.stringify(result, null, 2);
}

export default function registerSessionSearch(pi: ExtensionAPI) {
  pi.registerTool({
    name: "session_search",
    label: "Session Search",
    description:
      "Search/manage the local semantic index of prior Pi/JARVIS sessions.",
    promptSnippet: "Search prior Pi/JARVIS sessions",
    promptGuidelines: [
      "Use session_search before scanning raw old session files when the user asks about prior Pi/JARVIS sessions, decisions, logs, or previous work.",
      "Start with session_search action:'search' plus a natural-language query and small limit; set includeText:true only when snippets are insufficient.",
      "Use session_search action:'status' to check freshness; run action:'index' only when requested or when status/search results indicate the index is stale.",
    ],
    parameters: Type.Object({
      action: StringEnum(ACTIONS, { description: "Operation." }),
      query: Type.Optional(Type.String({ description: "Search query." })),
      limit: Type.Optional(Type.Number({ description: "Result limit." })),
      includeText: Type.Optional(Type.Boolean({ description: "Full chunk text." })),
      rebuild: Type.Optional(Type.Boolean({ description: "Re-embed all." })),
      maxFiles: Type.Optional(Type.Number({ description: "Index file cap." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const runner = runnerPath(ctx.cwd);
      if (!existsSync(runner)) throw new Error(`Session search runner not found: ${runner}`);

      const args = [runner, "--json", actionToCommand(params.action)];
      if (params.action === "search") {
        if (!params.query) throw new Error("session_search search requires query");
        args.push(params.query);
        if (params.limit) args.push("--limit", String(params.limit));
        if (params.includeText) args.push("--include-text");
      } else if (params.action === "index") {
        if (params.rebuild) args.push("--rebuild");
        if (params.maxFiles) args.push("--max-files", String(params.maxFiles));
      }

      const timeout = params.action === "index" ? 3_600_000 : 300_000;
      const result = await pi.exec(pythonPath(ctx.cwd), args, { signal, timeout });
      const raw = result.stdout.trim() || result.stderr.trim();
      let parsed: any;
      try {
        parsed = JSON.parse(raw);
      } catch {
        parsed = { ok: result.code === 0, message: raw, stderr: result.stderr };
      }
      if (result.code !== 0 || parsed?.ok === false) {
        throw new Error(parsed?.error || result.stderr || raw || "session_search command failed");
      }
      return {
        content: [{ type: "text", text: formatResult(parsed) }],
        details: parsed,
      };
    },
    renderCall(args, theme) {
      return new Text(`${theme.fg("toolTitle", "session_search")} ${theme.fg("accent", args.action ?? "")}`, 0, 0);
    },
    renderResult(result, _options, theme) {
      const text = result.details?.ok === false ? theme.fg("error", formatResult(result.details)) : theme.fg("success", formatResult(result.details));
      return new Text(truncate(text, 4000), 0, 0);
    },
  });

  pi.registerCommand("session-search", {
    description: "Search or manage the semantic Pi session-history index. Usage: /session-search status | index | search <query>",
    handler: async (args, ctx) => {
      const runner = runnerPath(ctx.cwd);
      const py = pythonPath(ctx.cwd);
      const trimmed = args.trim();
      const parts = trimmed ? trimmed.split(/\s+/) : ["status"];
      const command = parts.shift() ?? "status";
      const cliArgs = [runner, "--json", command === "install_cron" ? "install-cron" : command === "uninstall_cron" ? "uninstall-cron" : command];
      if (command === "search") cliArgs.push(parts.join(" "));
      else cliArgs.push(...parts);
      const result = await pi.exec(py, cliArgs, { timeout: command === "index" ? 3_600_000 : 300_000 });
      const raw = result.stdout.trim() || result.stderr.trim();
      let parsed: any;
      try {
        parsed = JSON.parse(raw);
      } catch {
        parsed = { ok: result.code === 0, message: raw };
      }
      ctx.ui.notify(formatResult(parsed).slice(0, 4000), result.code === 0 && parsed.ok !== false ? "info" : "error");
    },
  });
}
