import { createReadStream, existsSync, readFileSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, isAbsolute, join, resolve } from "node:path";
import * as https from "node:https";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

const DISCORD_API_HOST = "discord.com";
const DISCORD_API_BASE_PATH = "/api/v10";
const DEFAULT_MAX_BYTES = 25 * 1024 * 1024;

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
      value = value
        .slice(1, -1)
        .replace(/\\n/g, "\n")
        .replace(/\\r/g, "\r")
        .replace(/\\t/g, "\t")
        .replace(/\\"/g, '"')
        .replace(/\\\\/g, "\\");
    } else if (value.length >= 2 && value.startsWith("'") && value.endsWith("'")) {
      value = value.slice(1, -1);
    } else {
      value = value.replace(/\s+#.*$/, "");
    }
    values[match[1]] = value;
  }
  return values;
}

function envValue(name: string, cwd: string): string {
  const direct = process.env[name]?.trim();
  if (direct) return direct;
  const env = parseDotEnv(findAncestorFile(cwd, ".env"));
  return env[name]?.trim() ?? "";
}

function discordContextChannelId(): string {
  return (
    process.env.JARVIS_DISCORD_CHANNEL_ID?.trim() ||
    process.env.PI_DISCORD_CHANNEL_ID?.trim() ||
    process.env.DISCORD_CURRENT_CHANNEL_ID?.trim() ||
    ""
  );
}

function discordContextActive(): boolean {
  return process.env.JARVIS_DISCORD_CONTEXT === "1" && Boolean(discordContextChannelId());
}

function formatBytes(bytes: number): string {
  const units = ["B", "KiB", "MiB", "GiB"];
  let value = bytes;
  for (const unit of units) {
    if (value < 1024 || unit === units[units.length - 1]) {
      return unit === "B" ? `${bytes} B` : `${value.toFixed(1)} ${unit}`;
    }
    value /= 1024;
  }
  return `${bytes} B`;
}

function normalizePathInput(rawPath: string): string {
  let cleaned = rawPath.trim();
  if (cleaned.startsWith("@")) cleaned = cleaned.slice(1).trim();
  if (cleaned === "~") return homedir();
  if (cleaned.startsWith("~/")) return join(homedir(), cleaned.slice(2));
  return cleaned;
}

function safeDiscordFilename(path: string): string {
  const name = basename(path).replace(/[\r\n"\\/]/g, "_").trim();
  return name || "attachment";
}

function safeContentFilename(filename: string): string {
  return filename.replace(/[\r\n`*_~|>@]/g, "_").slice(0, 120) || "attachment";
}

function configuredMaxBytes(cwd: string): number {
  const raw = envValue("JARVIS_DISCORD_SEND_FILE_MAX_BYTES", cwd) || envValue("DISCORD_SEND_FILE_MAX_BYTES", cwd);
  if (!raw) return DEFAULT_MAX_BYTES;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed < 0) return DEFAULT_MAX_BYTES;
  return Math.floor(parsed);
}

function jsonBuffer(value: unknown): Buffer {
  return Buffer.from(JSON.stringify(value), "utf8");
}

function multipartHeader(boundary: string, name: string, filename?: string, contentType?: string): Buffer {
  const lines = [`--${boundary}`, `Content-Disposition: form-data; name="${name}"${filename ? `; filename="${filename}"` : ""}`];
  if (contentType) lines.push(`Content-Type: ${contentType}`);
  lines.push("", "");
  return Buffer.from(lines.join("\r\n"), "utf8");
}

function requestBodyChunks(boundary: string, filename: string, fileSize: number, messageContent: string) {
  const payload = jsonBuffer({ content: messageContent, allowed_mentions: { parse: [] } });
  const payloadHeader = multipartHeader(boundary, "payload_json", undefined, "application/json");
  const fileHeader = multipartHeader(boundary, "files[0]", filename, "application/octet-stream");
  const newline = Buffer.from("\r\n", "utf8");
  const close = Buffer.from(`--${boundary}--\r\n`, "utf8");
  const contentLength = payloadHeader.length + payload.length + newline.length + fileHeader.length + fileSize + newline.length + close.length;
  return { payload, payloadHeader, fileHeader, newline, close, contentLength };
}

async function postFileToDiscord(params: {
  token: string;
  channelId: string;
  filePath: string;
  filename: string;
  fileSize: number;
  messageContent: string;
  signal?: AbortSignal;
}): Promise<any> {
  const boundary = `----jarvis-discord-file-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  const body = requestBodyChunks(boundary, params.filename, params.fileSize, params.messageContent);

  return await new Promise((resolvePromise, rejectPromise) => {
    const req = https.request(
      {
        method: "POST",
        hostname: DISCORD_API_HOST,
        path: `${DISCORD_API_BASE_PATH}/channels/${encodeURIComponent(params.channelId)}/messages`,
        headers: {
          Authorization: `Bot ${params.token}`,
          "Content-Type": `multipart/form-data; boundary=${boundary}`,
          "Content-Length": String(body.contentLength),
          "User-Agent": "JARVIS Pi discord_send_file (https://pi.dev)",
        },
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on("data", (chunk) => chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)));
        res.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf8");
          let parsed: any = undefined;
          try {
            parsed = text ? JSON.parse(text) : undefined;
          } catch {
            parsed = undefined;
          }
          if ((res.statusCode ?? 0) >= 200 && (res.statusCode ?? 0) < 300) {
            resolvePromise(parsed ?? { ok: true });
            return;
          }
          const error: any = new Error(`Discord API upload failed: HTTP ${res.statusCode}: ${text.slice(0, 800)}`);
          error.statusCode = res.statusCode;
          error.retryAfter = parsed?.retry_after;
          rejectPromise(error);
        });
      },
    );

    const fileStream = createReadStream(params.filePath);
    const abort = () => {
      fileStream.destroy();
      req.destroy(new Error("discord_send_file aborted"));
    };
    params.signal?.addEventListener("abort", abort, { once: true });

    req.on("error", rejectPromise);
    fileStream.on("error", (error) => req.destroy(error));
    req.write(body.payloadHeader);
    req.write(body.payload);
    req.write(body.newline);
    req.write(body.fileHeader);
    fileStream.pipe(req, { end: false });
    fileStream.on("end", () => {
      req.write(body.newline);
      req.end(body.close);
    });
  });
}

async function postFileWithRateLimitRetry(params: Parameters<typeof postFileToDiscord>[0]): Promise<any> {
  let attempt = 0;
  while (true) {
    try {
      return await postFileToDiscord(params);
    } catch (error: any) {
      attempt += 1;
      const retryAfter = Number(error?.retryAfter);
      if (error?.statusCode !== 429 || attempt > 2 || !Number.isFinite(retryAfter) || retryAfter > 10) {
        throw error;
      }
      await new Promise((resolveDelay) => setTimeout(resolveDelay, Math.max(0, retryAfter) * 1000));
    }
  }
}

export default function registerDiscordSendFile(pi: ExtensionAPI) {
  if (!discordContextActive()) {
    return;
  }

  pi.registerTool({
    name: "discord_send_file",
    label: "Discord Send File",
    description:
      "Upload a verified local file to the current Discord channel. Discord sessions only; not for pings or scheduled jobs.",
    promptSnippet: "Upload a verified local file to the current Discord channel; Discord sessions only",
    promptGuidelines: [
      "Use discord_send_file only to upload a local file that already exists and has been verified, when the user asks for an attachment or file delivery in the current Discord channel.",
      "Do not use discord_send_file for notifications, pings, or scheduled jobs; use discord_ping or discord_cron for those separate purposes.",
      "If there is no active Discord channel context, report that this tool is unavailable rather than substituting another Discord helper.",
    ],
    parameters: Type.Object({
      path: Type.String({ description: "Local file path." }),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const channelId = discordContextChannelId();
      if (!channelId) {
        throw new Error("No active Discord channel context is available for discord_send_file.");
      }
      const token = envValue("DISCORD_BOT_TOKEN", ctx.cwd);
      if (!token) {
        throw new Error("DISCORD_BOT_TOKEN is not available, so discord_send_file cannot upload.");
      }

      const rawPath = normalizePathInput(params.path);
      if (!rawPath) throw new Error("discord_send_file requires a non-empty path.");
      const filePath = isAbsolute(rawPath) ? resolve(rawPath) : resolve(ctx.cwd, rawPath);
      let stat;
      try {
        stat = statSync(filePath);
      } catch (error: any) {
        throw new Error(`File not found or not accessible: ${filePath}`);
      }
      if (!stat.isFile()) {
        throw new Error(`Path is not a regular file: ${filePath}`);
      }

      const maxBytes = configuredMaxBytes(ctx.cwd);
      if (maxBytes > 0 && stat.size > maxBytes) {
        throw new Error(`File is ${formatBytes(stat.size)}, above discord_send_file limit ${formatBytes(maxBytes)}. Set JARVIS_DISCORD_SEND_FILE_MAX_BYTES to raise the local guard if your Discord server allows larger uploads.`);
      }

      const filename = safeDiscordFilename(filePath);
      const messageContent = `📎 File from JARVIS: ${safeContentFilename(filename)}`;
      const message = await postFileWithRateLimitRetry({
        token,
        channelId,
        filePath,
        filename,
        fileSize: stat.size,
        messageContent,
        signal,
      });

      const discordMessageId = message?.id ? String(message.id) : undefined;
      const attachmentUrl = Array.isArray(message?.attachments) && message.attachments[0]?.url ? String(message.attachments[0].url) : undefined;
      const sent = `Sent ${filename} (${formatBytes(stat.size)}) to the current Discord channel${discordMessageId ? ` as message ${discordMessageId}` : ""}.`;
      return {
        content: [{ type: "text" as const, text: sent }],
        details: {
          ok: true,
          path: filePath,
          filename,
          sizeBytes: stat.size,
          channelId,
          discordMessageId,
          attachmentUrl,
        },
      };
    },
    renderCall(args, theme) {
      return new Text(`${theme.fg("toolTitle", "discord_send_file")} ${theme.fg("accent", args.path ?? "")}`, 0, 0);
    },
    renderResult(result, _options, theme) {
      const filename = result.details?.filename ? String(result.details.filename) : "file";
      const size = typeof result.details?.sizeBytes === "number" ? ` (${formatBytes(result.details.sizeBytes)})` : "";
      return new Text(theme.fg("success", `Sent ${filename}${size} to Discord`), 0, 0);
    },
  });
}
