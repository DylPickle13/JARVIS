import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

import { StringEnum } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

const ACTIONS = [
  "add",
  "list",
  "remove",
  "enable",
  "disable",
  "run",
  "run_due",
  "runs",
  "output",
  "setup_discord",
  "install_cron",
  "uninstall_cron",
  "setup",
  "status",
] as const;

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

function projectRoot(cwd: string): string {
  const runner = findAncestorFile(cwd, ".pi/discord-cron/runner.py") ?? join(cwd, ".pi", "discord-cron", "runner.py");
  return dirname(dirname(dirname(runner)));
}

function runnerPath(cwd: string): string {
  return findAncestorFile(cwd, ".pi/discord-cron/runner.py") ?? join(cwd, ".pi", "discord-cron", "runner.py");
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

function textFromResult(result: any): string {
  if (!result) return "No output";
  if (result.message) return String(result.message);
  if (result.error) return `Error: ${result.error}`;
  return JSON.stringify(result, null, 2);
}

function truncate(text: string, max = 12000): string {
  return text.length > max ? `${text.slice(0, max)}\n… truncated …` : text;
}

function startDetachedRunner(cwd: string, args: string[]): number | undefined {
  const child = spawn(pythonPath(cwd), args, {
    cwd: projectRoot(cwd),
    detached: true,
    stdio: "ignore",
    env: process.env,
  });
  child.unref();
  return child.pid;
}

function manualRunStartedMessage(jobId: string, pid: number | undefined): string {
  return `Started manual Discord cron run for **${jobId}**${pid ? ` (pid ${pid})` : ""}. Output will be posted to that job's Discord thread when it finishes.`;
}

export default function registerDiscordCron(pi: ExtensionAPI) {
  pi.registerTool({
    name: "discord_cron",
    label: "Discord Cron",
    description:
      "Manage Pi/JARVIS scheduled jobs whose output is posted to Discord. Use this for scheduled jobs only; use the discord group for immediate pings, notifications, or file delivery.",
    promptSnippet: "Inspect/manage scheduled Pi/JARVIS jobs posted to Discord; not for immediate Discord delivery",
    promptGuidelines: [
      "Use discord_cron only for Pi/JARVIS scheduled jobs posted to Discord, including questions about existing/running scheduled jobs; do not inspect system crontab unless OS-level cron/launchd is explicitly requested.",
      "Do not use discord_cron for immediate pings, notifications, or file delivery; load the discord group and use discord_ping or discord_send_file as appropriate.",
      "Do not start/restart the main JARVIS Discord bot unless the user explicitly asks.",
      "Use discord_cron action:'add' with schedule and prompt to create a job; schedule examples include +5m, interval-like strings, cron, or ISO depending on the runner.",
      "Use discord_cron status/list/runs/output to inspect jobs and results before changing them; run starts a detached manual job whose output is posted to Discord.",
      "Treat remove/disable/uninstall/setup changes as mutating operations that require clear user intent.",
    ],
    parameters: Type.Object({
      action: StringEnum(ACTIONS, { description: "Operation." }),
      name: Type.Optional(Type.String({ description: "Job name." })),
      schedule: Type.Optional(Type.String({ description: "+5m, ISO, 5m interval, or cron." })),
      prompt: Type.Optional(Type.String({ description: "Job prompt." })),
      jobId: Type.Optional(Type.String({ description: "Job id/name." })),
      runId: Type.Optional(Type.String({ description: "Run id/suffix." })),
      kind: Type.Optional(StringEnum(["once", "interval", "cron"] as const, { description: "Schedule kind." })),
      model: Type.Optional(Type.String({ description: "Pi model." })),
      description: Type.Optional(Type.String({ description: "Job note." })),
      guildId: Type.Optional(Type.String({ description: "Discord guild id." })),
      channelName: Type.Optional(Type.String({ description: "Discord channel." })),
      recreateChannel: Type.Optional(Type.Boolean({ description: "Recreate output channel." })),
      limit: Type.Optional(Type.Number({ description: "List limit." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const runner = runnerPath(ctx.cwd);
      if (!existsSync(runner)) {
        throw new Error(`Discord cron runner not found: ${runner}`);
      }

      const args = [runner, "--json", actionToCommand(params.action)];
      if (params.action === "add") {
        if (!params.schedule || !params.prompt) throw new Error("discord_cron add requires schedule and prompt");
        if (params.name) args.push("--name", params.name);
        args.push("--schedule", params.schedule, "--prompt", params.prompt);
        if (params.kind) args.push("--kind", params.kind);
        if (params.model) args.push("--model", params.model);
        if (params.description) args.push("--description", params.description);
      } else if (["remove", "enable", "disable", "run"].includes(params.action)) {
        if (!params.jobId) throw new Error(`${params.action} requires jobId`);
        args.push(params.jobId);
      } else if (params.action === "output") {
        if (!params.runId) throw new Error("output requires runId");
        args.push(params.runId);
      } else if (params.action === "runs") {
        if (params.jobId) args.push("--job-id", params.jobId);
        if (params.limit) args.push("--limit", String(params.limit));
      } else if (params.action === "setup" || params.action === "setup_discord") {
        if (params.guildId) args.push("--guild-id", params.guildId);
        if (params.channelName) args.push("--channel-name", params.channelName);
        if (params.recreateChannel) args.push("--recreate-channel");
      }

      if (params.action === "run") {
        const pid = startDetachedRunner(ctx.cwd, args);
        const message = manualRunStartedMessage(params.jobId!, pid);
        return {
          content: [{ type: "text", text: message }],
          details: { ok: true, message, detached: true, pid, jobId: params.jobId },
        };
      }

      const result = await pi.exec(pythonPath(ctx.cwd), args, { signal, timeout: 30_000 });
      const raw = result.stdout.trim() || result.stderr.trim();
      let parsed: any;
      try {
        parsed = JSON.parse(raw);
      } catch {
        parsed = { ok: result.code === 0, message: raw, stderr: result.stderr };
      }
      if (result.code !== 0 || parsed?.ok === false) {
        throw new Error(parsed?.error || result.stderr || raw || "discord_cron command failed");
      }
      return {
        content: [{ type: "text", text: truncate(textFromResult(parsed)) }],
        details: parsed,
      };
    },
    renderCall(args, theme) {
      return new Text(`${theme.fg("toolTitle", "discord_cron")} ${theme.fg("accent", args.action ?? "")}`, 0, 0);
    },
    renderResult(result, _options, theme) {
      const text = result.details?.ok === false ? theme.fg("error", textFromResult(result.details)) : theme.fg("success", textFromResult(result.details));
      return new Text(truncate(text, 4000), 0, 0);
    },
  });

  pi.registerCommand("discord-cron", {
    description: "Manage Pi/JARVIS scheduled cron jobs posted to Discord. With no args, show status.",
    handler: async (args, ctx) => {
      const runner = runnerPath(ctx.cwd);
      const py = pythonPath(ctx.cwd);
      const parts = args.trim() ? args.trim().split(/\s+/) : ["status"];
      const commandIndex = parts[0] === "--json" ? 1 : 0;
      if (parts[commandIndex] === "run" && parts[commandIndex + 1]) {
        const pid = startDetachedRunner(ctx.cwd, [runner, ...parts]);
        ctx.ui.notify(manualRunStartedMessage(parts[commandIndex + 1], pid), "info");
        return;
      }
      const result = await pi.exec(py, [runner, ...parts], { timeout: 30_000 });
      const output = result.stdout.trim() || result.stderr.trim();
      ctx.ui.notify(output.slice(0, 4000) || "No output", result.code === 0 ? "info" : "error");
    },
  });
}
