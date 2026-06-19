import { homedir } from "node:os";
import { join } from "node:path";

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

type MinecraftJarvisParams = {
  message: string;
  from?: string;
  target?: string;
  waitSeconds?: number;
  host?: string;
  user?: string;
  sshKey?: string;
};

const DEFAULT_HOST = process.env.JARVIS_MINECRAFT_HOST || process.env.MINECRAFT_JARVIS_HOST || "";
const DEFAULT_USER = process.env.JARVIS_MINECRAFT_SSH_USER || process.env.MINECRAFT_JARVIS_SSH_USER || process.env.MINECRAFT_JARVIS_USER || "";
const DEFAULT_SSH_KEY = process.env.JARVIS_MINECRAFT_SSH_KEY || process.env.MINECRAFT_JARVIS_SSH_KEY || join(homedir(), ".ssh", "jarvis_dashboard_host");
const DEFAULT_FROM = process.env.JARVIS_MINECRAFT_FROM || process.env.MINECRAFT_JARVIS_FROM || "player";
const DEFAULT_TARGET = process.env.JARVIS_MINECRAFT_TARGET || process.env.MINECRAFT_JARVIS_TARGET || "jarvis";

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

function cleanMessage(value: unknown): string {
  return String(value ?? "")
    .replace(/§./g, "")
    .replace(/[\r\n\t]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function boundedWaitSeconds(value: unknown, fallback: number): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
  return Math.max(0, Math.min(Math.round(value), 30));
}

function truncate(text: string, max = 12000): string {
  return text.length > max ? `${text.slice(0, max)}\n… truncated …` : text;
}

function buildRemoteScript(params: Required<Pick<MinecraftJarvisParams, "message" | "from" | "target" | "waitSeconds">>): string {
  const fakeChatLine = `<${params.from}> ${params.message}`;
  const tellrawJson = JSON.stringify({ text: fakeChatLine });
  const serverCommand = `tellraw ${params.target} ${tellrawJson}`;
  const wait = boundedWaitSeconds(params.waitSeconds, 8);

  return [
    "set -e",
    'BASE="$HOME/minecraft-server"',
    `"$BASE/bin/cmd.sh" ${shellQuote(serverCommand)}`,
    wait > 0 ? `sleep ${wait}` : undefined,
    "echo '--- sent to minecraft jarvis ---'",
    `echo ${shellQuote(fakeChatLine)}`,
    "echo '--- recent bot log ---'",
    "tail -n 80 \"$BASE/jarvis-bot/logs/bot.log\" || true",
    "echo '--- recent server jarvis chat ---'",
    "grep -iE 'jarvis|joke|sir' \"$BASE/server/logs/latest.log\" | tail -n 80 || true",
  ].filter(Boolean).join("\n");
}

async function sendMinecraftJarvisChat(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  rawParams: MinecraftJarvisParams,
  signal?: AbortSignal,
) {
  const message = cleanMessage(rawParams.message);
  if (!message) throw new Error("message is required");
  if (message.length > 500) throw new Error("message is too long for in-game chat; keep it under 500 characters");

  const from = cleanMessage(rawParams.from) || DEFAULT_FROM;
  const target = cleanMessage(rawParams.target) || DEFAULT_TARGET;
  const waitSeconds = boundedWaitSeconds(rawParams.waitSeconds, 8);
  const host = cleanMessage(rawParams.host) || DEFAULT_HOST;
  const user = cleanMessage(rawParams.user) || DEFAULT_USER;
  if (!host) throw new Error("Minecraft JARVIS SSH host is required; set JARVIS_MINECRAFT_HOST locally or pass host.");
  if (!user) throw new Error("Minecraft JARVIS SSH user is required; set JARVIS_MINECRAFT_SSH_USER locally or pass user.");
  const sshKey = cleanMessage(rawParams.sshKey) || DEFAULT_SSH_KEY;
  const remote = `${user}@${host}`;
  const script = buildRemoteScript({ message, from, target, waitSeconds });

  const result = await pi.exec("ssh", [
    "-i", sshKey,
    "-o", "IdentitiesOnly=yes",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=8",
    remote,
    `bash -lc ${shellQuote(script)}`,
  ], {
    signal,
    timeout: Math.max(20_000, (waitSeconds + 20) * 1000),
  });

  const output = [result.stdout.trim(), result.stderr.trim()].filter(Boolean).join("\n").trim();
  if (result.code !== 0) {
    throw new Error(output || `ssh exited with code ${result.code}`);
  }

  return {
    content: [{ type: "text" as const, text: truncate(output || `Sent to ${target}: ${message}`) }],
    details: {
      ok: true,
      host,
      user,
      target,
      from,
      message,
      waitSeconds,
      stdout: result.stdout,
      stderr: result.stderr,
    },
  };
}

export default function registerMinecraftJarvisChat(pi: ExtensionAPI) {
  pi.registerTool({
    name: "minecraft_jarvis",
    label: "Minecraft jarvis",
    description: "Send a plain-language prompt to a configured Minecraft jarvis bot on a private Paper server. The bot forwards chat to a local Pi RPC agent, which uses safe Mineflayer tools to converse or act.",
    promptSnippet: "Prompt the local Minecraft Pi agent through jarvis: minecraft_jarvis({ message: 'come here' }) or minecraft_jarvis({ message: 'tell me a joke' }).",
    promptGuidelines: [
      "Use minecraft_jarvis when the user wants to command or talk to the Minecraft jarvis bot from this Pi session instead of typing in Minecraft.",
      "Pass the user's plain-language instruction in message; do not pre-interpret it into Minecraft bot tools. The configured local Pi RPC agent decides whether to respond or act within its safe Mineflayer toolset.",
      "Keep messages short and non-destructive. The local Minecraft Pi agent currently starts with safe tools only: chat, observe/status, players, inventory, movement/follow/stop, block search, simple mining, and simple crafting.",
    ],
    parameters: Type.Object({
      message: Type.String({ description: "Plain-language chat message/instruction for the in-game jarvis bot, e.g. 'tell me a joke', 'come here', or 'describe what is around you'." }),
      from: Type.Optional(Type.String({ description: "Displayed sender in the fake chat line. Defaults to JARVIS_MINECRAFT_FROM or a generic player name." })),
      target: Type.Optional(Type.String({ description: "Minecraft player to receive the tellraw fake chat. Defaults to jarvis." })),
      waitSeconds: Type.Optional(Type.Number({ description: "Seconds to wait before returning recent bot/server logs. Default 8, max 30. Use 0 to return immediately." })),
      host: Type.Optional(Type.String({ description: "Advanced: Minecraft server host/IP. Defaults to JARVIS_MINECRAFT_HOST when configured locally." })),
      user: Type.Optional(Type.String({ description: "Advanced: SSH username. Defaults to JARVIS_MINECRAFT_SSH_USER when configured locally." })),
      sshKey: Type.Optional(Type.String({ description: "Advanced: SSH private key path. Defaults to JARVIS_MINECRAFT_SSH_KEY or ~/.ssh/jarvis_dashboard_host." })),
    }),
    async execute(_toolCallId, rawParams, signal, _onUpdate, ctx) {
      return sendMinecraftJarvisChat(pi, ctx, rawParams as MinecraftJarvisParams, signal);
    },
    renderCall(args, theme) {
      const message = typeof args.message === "string" ? args.message : "";
      return new Text(`${theme.fg("toolTitle", "minecraft_jarvis")} ${theme.fg("dim", message.slice(0, 80))}`, 0, 0);
    },
    renderResult(result, _options, theme) {
      const message = typeof result.details?.message === "string" ? result.details.message : "sent";
      return new Text(`${theme.fg("success", "✓ sent to Minecraft jarvis")} ${theme.fg("dim", message.slice(0, 80))}`, 0, 0);
    },
  });
}
