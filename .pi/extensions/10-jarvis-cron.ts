import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

import { StringEnum } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

import { findAncestorFile, parseDotEnv } from "./lib/env";
import { truncate } from "./lib/text";

const ACTIONS = [
  "add",
  "list",
  "set_category",
  "remove",
  "enable",
  "disable",
  "run",
  "run_due",
  "runs",
  "output",
  "install",
  "uninstall",
  "status",
] as const;

const RUNNER_RELATIVE_PATH = "projects/operation-jarvis/jarvisd/jarvisd_core/scheduler/runner.py";

function runnerPath(cwd: string): string {
  return findAncestorFile(cwd, RUNNER_RELATIVE_PATH) ?? join(cwd, RUNNER_RELATIVE_PATH);
}

function projectRoot(cwd: string): string {
  return resolve(dirname(runnerPath(cwd)), "../../../../..");
}

function pythonPath(cwd: string): string {
  const root = projectRoot(cwd);
  const env = parseDotEnv(findAncestorFile(cwd, ".env"));
  if (env.PI_PYTHON) return resolve(root, env.PI_PYTHON);
  const venvPython = join(root, ".venv", "bin", "python");
  return existsSync(venvPython) ? venvPython : "python3";
}

// Tokenize quoted CLI arguments without evaluating shell expressions.
export function parseCronArguments(input: string): string[] {
  const args: string[] = [];
  let value = "";
  let quote = "";
  let escaped = false;
  let started = false;
  for (const char of input) {
    if (escaped) {
      value += char;
      escaped = false;
    } else if (char === "\\" && quote !== "'") {
      escaped = true;
      started = true;
    } else if (quote) {
      if (char === quote) quote = "";
      else value += char;
    } else if (char === '"' || char === "'") {
      quote = char;
      started = true;
    } else if (/\s/.test(char)) {
      if (started) args.push(value);
      value = "";
      started = false;
    } else {
      value += char;
      started = true;
    }
  }
  if (quote || escaped) throw new Error("Unclosed quote or trailing escape in cron command");
  if (started) args.push(value);
  return args;
}

function commandName(action: string): string {
  return action.replace(/_/g, "-");
}

function resultText(result: any): string {
  if (!result) return "No output";
  if (result.message) return String(result.message);
  if (result.error) return `Error: ${result.error}`;
  return JSON.stringify(result, null, 2);
}

function startDetached(cwd: string, args: string[]): number | undefined {
  const child = spawn(pythonPath(cwd), args, {
    cwd: projectRoot(cwd),
    detached: true,
    stdio: "ignore",
    env: process.env,
  });
  child.unref();
  return child.pid;
}

export default function registerJarvisCron(pi: ExtensionAPI) {
  pi.registerTool({
    name: "jarvis_cron",
    label: "JARVIS Jobs",
    description: "Manage private Pi/JARVIS scheduled jobs and their bounded local result history.",
    parameters: Type.Object({
      action: StringEnum(ACTIONS, { description: "Operation." }),
      name: Type.Optional(Type.String({ description: "Job name." })),
      category: Type.Optional(Type.String({ description: "Category for add/set_category, or list filter. Empty/Uncategorized clears assignment." })),
      schedule: Type.Optional(Type.String({ description: "+5m, ISO, 5m interval, or cron." })),
      prompt: Type.Optional(Type.String({ description: "Job prompt." })),
      jobId: Type.Optional(Type.String({ description: "Job id/name." })),
      runId: Type.Optional(Type.String({ description: "Result id." })),
      kind: Type.Optional(StringEnum(["once", "interval", "cron"] as const, { description: "Schedule kind." })),
      model: Type.Optional(Type.String({ description: "Pi model." })),
      description: Type.Optional(Type.String({ description: "Job note." })),
      limit: Type.Optional(Type.Number({ description: "Bounded result count." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const runner = runnerPath(ctx.cwd);
      if (!existsSync(runner)) throw new Error(`JARVIS scheduler not found: ${runner}`);
      const args = [runner, "--json", commandName(params.action)];
      if (params.action === "add") {
        if (!params.schedule || !params.prompt) throw new Error("jarvis_cron add requires schedule and prompt");
        if (params.name) args.push("--name", params.name);
        args.push("--schedule", params.schedule, "--prompt", params.prompt);
        if (params.kind) args.push("--kind", params.kind);
        if (params.model) args.push("--model", params.model);
        if (params.description) args.push("--description", params.description);
        if (params.category !== undefined) args.push("--category", params.category);
      } else if (params.action === "set_category") {
        if (!params.jobId || params.category === undefined) throw new Error("set_category requires jobId and category");
        args.push(params.jobId, "--category", params.category);
      } else if (params.action === "list") {
        if (params.category !== undefined) args.push("--category", params.category);
      } else if (["remove", "enable", "disable", "run"].includes(params.action)) {
        if (!params.jobId) throw new Error(`${params.action} requires jobId`);
        args.push(params.jobId);
      } else if (params.action === "output") {
        if (!params.runId) throw new Error("output requires runId");
        args.push(params.runId);
      } else if (params.action === "runs") {
        if (params.jobId) args.push("--job-id", params.jobId);
        if (params.limit) args.push("--limit", String(params.limit));
      }
      if (params.action === "run") {
        const pid = startDetached(ctx.cwd, args);
        const message = `Started manual JARVIS job run for **${params.jobId}**${pid ? ` (pid ${pid})` : ""}. The result will be retained locally.`;
        return { content: [{ type: "text", text: message }], details: { ok: true, message, detached: true, pid } };
      }
      const result = await pi.exec(pythonPath(ctx.cwd), args, { signal, timeout: 30_000 });
      const raw = result.stdout.trim() || result.stderr.trim();
      let parsed: any;
      try { parsed = JSON.parse(raw); } catch { parsed = { ok: result.code === 0, message: raw }; }
      if (result.code !== 0 || parsed?.ok === false) throw new Error(parsed?.error || result.stderr || raw || "JARVIS scheduler command failed");
      return { content: [{ type: "text", text: truncate(resultText(parsed)) }], details: parsed };
    },
    renderCall(args, theme) {
      return new Text(`${theme.fg("toolTitle", "jarvis_cron")} ${theme.fg("accent", args.action ?? "")}`, 0, 0);
    },
    renderResult(result, _options, theme) {
      const color = result.details?.ok === false ? "error" : "success";
      return new Text(truncate(theme.fg(color, resultText(result.details)), 4000), 0, 0);
    },
  });

  pi.registerCommand("jarvis-cron", {
    description: "Manage private Pi/JARVIS scheduled jobs. With no args, show status.",
    handler: async (args, ctx) => {
      const runner = runnerPath(ctx.cwd);
      const parts = args.trim() ? parseCronArguments(args) : ["status"];
      const commandIndex = parts[0] === "--json" ? 1 : 0;
      if (parts[commandIndex] === "run" && parts[commandIndex + 1]) {
        const pid = startDetached(ctx.cwd, [runner, ...parts]);
        ctx.ui.notify(`Started local job run${pid ? ` (pid ${pid})` : ""}.`, "info");
        return;
      }
      const result = await pi.exec(pythonPath(ctx.cwd), [runner, ...parts], { timeout: 30_000 });
      const output = result.stdout.trim() || result.stderr.trim();
      ctx.ui.notify(output.slice(0, 4000) || "No output", result.code === 0 ? "info" : "error");
    },
  });
}
