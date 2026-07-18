import { createReadStream, statSync } from "node:fs";
import * as https from "node:https";
import { isAbsolute, resolve } from "node:path";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

import { envValue, findAncestorFile, firstEnvValue, parseDotEnv } from "./lib/env";
import { jsonBuffer, multipartHeader, safeDiscordFilename } from "./lib/discord";
import { normalizePathInput } from "./lib/path";
import { formatBytes, truncateForDiscord } from "./lib/text";

const DISCORD_API_HOST = "discord.com";
const DISCORD_API_BASE_PATH = "/api/v10";
const DEFAULT_HELPERS_CHANNEL_NAME = "jarvis-helpers";
const DEFAULT_THREAD_NAME = "pings";
const DEFAULT_USER_QUERY = "";
const DEFAULT_AUTO_ARCHIVE_MINUTES = 1440;
const DEFAULT_MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024;
const MAX_DISCORD_MESSAGE_CHARS = 2000;
const MAX_DISCORD_ATTACHMENTS = 10;

const CHANNEL_TYPE_GUILD_TEXT = 0;
const CHANNEL_TYPE_GUILD_ANNOUNCEMENT = 5;
const CHANNEL_TYPE_ANNOUNCEMENT_THREAD = 10;
const CHANNEL_TYPE_PUBLIC_THREAD = 11;

class DiscordApiError extends Error {
  statusCode?: number;
  retryAfter?: number;
  responseText?: string;
}

type DiscordRequestOptions = {
  token: string;
  method: "GET" | "POST" | "PATCH" | "PUT";
  path: string;
  query?: Record<string, string | number | boolean | undefined>;
  body?: unknown;
  signal?: AbortSignal;
  expectJson?: boolean;
};

type ChannelInfo = {
  id: string;
  name?: string;
  type?: number;
};

type ThreadResolution = {
  thread: Record<string, any>;
  created: boolean;
  unarchived: boolean;
};

type PingAttachment = {
  path: string;
  filename: string;
  sizeBytes: number;
};

type SentAttachment = PingAttachment & {
  url?: string;
};

type PingResult = {
  ok: true;
  summary: string;
  guildId: string;
  helpersChannelId: string;
  helpersChannelName: string;
  threadId: string;
  threadName: string;
  userId: string;
  discordMessageId?: string;
  messageLink?: string;
  attachments: SentAttachment[];
  createdThread: boolean;
  unarchivedThread: boolean;
};

function envValues(cwd: string): Record<string, string> {
  return parseDotEnv(findAncestorFile(cwd, ".env"));
}

function stripDiscordDecorators(value: string): string {
  return value.trim().replace(/^[@#]/, "").trim();
}

function normalizeSnowflake(value: string | undefined): string {
  if (!value) return "";
  const match = String(value).match(/\d{5,}/);
  return match ? match[0] : "";
}

function splitCsv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function firstSnowflake(value: string): string {
  for (const item of splitCsv(value)) {
    const id = normalizeSnowflake(item);
    if (id) return id;
  }
  return normalizeSnowflake(value);
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

function coerceAutoArchiveMinutes(value: unknown, cwd: string, dotenv: Record<string, string>): number {
  const raw = value ?? envValue("DISCORD_PING_THREAD_AUTO_ARCHIVE_MINUTES", cwd, dotenv) ?? DEFAULT_AUTO_ARCHIVE_MINUTES;
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : DEFAULT_AUTO_ARCHIVE_MINUTES;
}

function configuredMaxAttachmentBytes(cwd: string, dotenv: Record<string, string>): number {
  const raw =
    envValue("DISCORD_PING_ATTACHMENT_MAX_BYTES", cwd, dotenv) ||
    envValue("JARVIS_DISCORD_SEND_FILE_MAX_BYTES", cwd, dotenv) ||
    envValue("DISCORD_SEND_FILE_MAX_BYTES", cwd, dotenv);
  if (!raw) return DEFAULT_MAX_ATTACHMENT_BYTES;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed < 0) return DEFAULT_MAX_ATTACHMENT_BYTES;
  return Math.floor(parsed);
}

function coerceAttachmentPaths(params: any): string[] {
  const rawPaths: unknown[] = [];
  if (typeof params.attachmentPath === "string") rawPaths.push(params.attachmentPath);
  if (Array.isArray(params.attachmentPaths)) rawPaths.push(...params.attachmentPaths);
  return unique(
    rawPaths
      .map((value) => (typeof value === "string" ? normalizePathInput(value) : ""))
      .filter(Boolean),
  ).slice(0, MAX_DISCORD_ATTACHMENTS);
}

function resolvePingAttachments(params: any, cwd: string, dotenv: Record<string, string>): PingAttachment[] {
  const maxBytes = configuredMaxAttachmentBytes(cwd, dotenv);
  return coerceAttachmentPaths(params).map((rawPath) => {
    const filePath = isAbsolute(rawPath) ? resolve(rawPath) : resolve(cwd, rawPath);
    let stat;
    try {
      stat = statSync(filePath);
    } catch {
      throw new Error(`Attachment file not found or not accessible: ${filePath}`);
    }
    if (!stat.isFile()) throw new Error(`Attachment path is not a regular file: ${filePath}`);
    if (maxBytes > 0 && stat.size > maxBytes) {
      throw new Error(
        `Attachment ${filePath} is ${formatBytes(stat.size)}, above discord_ping limit ${formatBytes(maxBytes)}. Set DISCORD_PING_ATTACHMENT_MAX_BYTES to raise the local guard if your Discord server allows larger uploads.`,
      );
    }
    return { path: filePath, filename: safeDiscordFilename(filePath), sizeBytes: stat.size };
  });
}

function buildRequestPath(path: string, query?: DiscordRequestOptions["query"]): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === "") continue;
    params.set(key, String(value));
  }
  const queryString = params.toString();
  return queryString ? `${path}?${queryString}` : path;
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) return Promise.reject(new Error("discord_ping aborted"));
  return new Promise((resolveSleep, rejectSleep) => {
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolveSleep();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      rejectSleep(new Error("discord_ping aborted"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

async function discordApiRequest(options: DiscordRequestOptions): Promise<any> {
  const requestPath = buildRequestPath(options.path, options.query);
  const payload = options.body === undefined ? undefined : Buffer.from(JSON.stringify(options.body), "utf8");

  return await new Promise((resolvePromise, rejectPromise) => {
    if (options.signal?.aborted) {
      rejectPromise(new Error("discord_ping aborted"));
      return;
    }

    const headers: Record<string, string> = {
      Authorization: `Bot ${options.token}`,
      "User-Agent": "JARVIS Pi discord_ping (https://pi.dev)",
    };
    if (payload) {
      headers["Content-Type"] = "application/json";
      headers["Content-Length"] = String(payload.length);
    }

    const req = https.request(
      {
        method: options.method,
        hostname: DISCORD_API_HOST,
        path: `${DISCORD_API_BASE_PATH}${requestPath}`,
        headers,
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on("data", (chunk) => chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)));
        res.on("end", () => {
          cleanup();
          const text = Buffer.concat(chunks).toString("utf8");
          let parsed: any = undefined;
          try {
            parsed = text ? JSON.parse(text) : undefined;
          } catch {
            parsed = undefined;
          }

          const statusCode = res.statusCode ?? 0;
          if (statusCode >= 200 && statusCode < 300) {
            resolvePromise(options.expectJson === false ? parsed ?? { ok: true } : parsed ?? {});
            return;
          }

          const error = new DiscordApiError(
            `Discord API ${options.method} ${requestPath} failed: HTTP ${statusCode}: ${text.slice(0, 800)}`,
          );
          error.statusCode = statusCode;
          error.responseText = text;
          const retryAfter = Number(parsed?.retry_after ?? res.headers["retry-after"]);
          if (Number.isFinite(retryAfter)) error.retryAfter = retryAfter;
          rejectPromise(error);
        });
      },
    );

    const cleanup = () => options.signal?.removeEventListener("abort", abort);
    const abort = () => {
      req.destroy(new Error("discord_ping aborted"));
    };
    options.signal?.addEventListener("abort", abort, { once: true });

    req.setTimeout(15_000, () => req.destroy(new Error("Discord API request timed out")));
    req.on("error", (error) => {
      cleanup();
      rejectPromise(error);
    });
    if (payload) req.write(payload);
    req.end();
  });
}

async function discordApiRequestWithRetry(options: DiscordRequestOptions): Promise<any> {
  let attempt = 0;
  while (true) {
    try {
      return await discordApiRequest(options);
    } catch (error: any) {
      attempt += 1;
      const retryAfter = Number(error?.retryAfter);
      if (error?.statusCode !== 429 || attempt > 3 || !Number.isFinite(retryAfter) || retryAfter > 10) {
        throw error;
      }
      await sleep(Math.max(0, retryAfter) * 1000, options.signal);
    }
  }
}

function multipartMessageBody(boundary: string, payloadJson: unknown, attachments: PingAttachment[]) {
  const payload = jsonBuffer(payloadJson);
  const payloadHeader = multipartHeader(boundary, "payload_json", undefined, "application/json");
  const newline = Buffer.from("\r\n", "utf8");
  const close = Buffer.from(`--${boundary}--\r\n`, "utf8");
  const fileHeaders = attachments.map((attachment, index) =>
    multipartHeader(boundary, `files[${index}]`, attachment.filename, "application/octet-stream"),
  );
  const contentLength =
    payloadHeader.length +
    payload.length +
    newline.length +
    attachments.reduce((sum, attachment, index) => sum + fileHeaders[index].length + attachment.sizeBytes + newline.length, 0) +
    close.length;
  return { payload, payloadHeader, newline, close, fileHeaders, contentLength };
}

async function postDiscordMessageWithAttachments(params: {
  token: string;
  channelId: string;
  content: string;
  userId: string;
  attachments: PingAttachment[];
  signal?: AbortSignal;
}): Promise<any> {
  if (params.attachments.length === 0) {
    return await discordApiRequestWithRetry({
      token: params.token,
      method: "POST",
      path: `/channels/${params.channelId}/messages`,
      body: {
        content: params.content,
        allowed_mentions: { parse: [], users: [params.userId] },
      },
      signal: params.signal,
    });
  }

  const boundary = `----jarvis-discord-ping-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  const payloadJson = {
    content: params.content,
    allowed_mentions: { parse: [], users: [params.userId] },
  };
  const body = multipartMessageBody(boundary, payloadJson, params.attachments);

  return await new Promise((resolvePromise, rejectPromise) => {
    if (params.signal?.aborted) {
      rejectPromise(new Error("discord_ping aborted"));
      return;
    }

    const req = https.request(
      {
        method: "POST",
        hostname: DISCORD_API_HOST,
        path: `${DISCORD_API_BASE_PATH}/channels/${encodeURIComponent(params.channelId)}/messages`,
        headers: {
          Authorization: `Bot ${params.token}`,
          "Content-Type": `multipart/form-data; boundary=${boundary}`,
          "Content-Length": String(body.contentLength),
          "User-Agent": "JARVIS Pi discord_ping (https://pi.dev)",
        },
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on("data", (chunk) => chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)));
        res.on("end", () => {
          cleanup();
          const text = Buffer.concat(chunks).toString("utf8");
          let parsed: any = undefined;
          try {
            parsed = text ? JSON.parse(text) : undefined;
          } catch {
            parsed = undefined;
          }

          const statusCode = res.statusCode ?? 0;
          if (statusCode >= 200 && statusCode < 300) {
            resolvePromise(parsed ?? { ok: true });
            return;
          }

          const error = new DiscordApiError(`Discord API upload failed: HTTP ${statusCode}: ${text.slice(0, 800)}`);
          error.statusCode = statusCode;
          error.responseText = text;
          const retryAfter = Number(parsed?.retry_after ?? res.headers["retry-after"]);
          if (Number.isFinite(retryAfter)) error.retryAfter = retryAfter;
          rejectPromise(error);
        });
      },
    );

    const streams = params.attachments.map((attachment) => createReadStream(attachment.path));
    const cleanup = () => params.signal?.removeEventListener("abort", abort);
    const abort = () => {
      for (const stream of streams) stream.destroy();
      req.destroy(new Error("discord_ping aborted"));
    };
    params.signal?.addEventListener("abort", abort, { once: true });

    req.setTimeout(60_000, () => req.destroy(new Error("Discord API upload timed out")));
    req.on("error", (error) => {
      cleanup();
      rejectPromise(error);
    });

    const writeFile = (index: number) => {
      if (index >= streams.length) {
        req.end(body.close);
        return;
      }
      const stream = streams[index];
      req.write(body.fileHeaders[index]);
      stream.on("error", (error) => req.destroy(error));
      stream.pipe(req, { end: false });
      stream.on("end", () => {
        req.write(body.newline);
        writeFile(index + 1);
      });
    };

    req.write(body.payloadHeader);
    req.write(body.payload);
    req.write(body.newline);
    writeFile(0);
  });
}

async function postDiscordMessageWithAttachmentsAndRetry(params: Parameters<typeof postDiscordMessageWithAttachments>[0]): Promise<any> {
  let attempt = 0;
  while (true) {
    try {
      return await postDiscordMessageWithAttachments(params);
    } catch (error: any) {
      attempt += 1;
      const retryAfter = Number(error?.retryAfter);
      if (error?.statusCode !== 429 || attempt > 3 || !Number.isFinite(retryAfter) || retryAfter > 10) {
        throw error;
      }
      await sleep(Math.max(0, retryAfter) * 1000, params.signal);
    }
  }
}

async function resolveGuildId(params: any, cwd: string, dotenv: Record<string, string>, token: string, signal?: AbortSignal): Promise<string> {
  const configured =
    normalizeSnowflake(params.guildId) ||
    normalizeSnowflake(
      firstEnvValue(["DISCORD_PING_GUILD_ID", "JARVIS_DISCORD_GUILD_ID", "DISCORD_GUILD_ID", "DISCORD_CRON_GUILD_ID"], cwd, dotenv),
    );
  if (configured) return configured;

  const payload = await discordApiRequestWithRetry({ token, method: "GET", path: "/users/@me/guilds", signal });
  const guilds = Array.isArray(payload) ? payload : [];
  if (guilds.length === 1 && guilds[0]?.id) return String(guilds[0].id);
  if (guilds.length === 0) {
    throw new Error("The Discord bot is not in any guilds, so discord_ping cannot find #jarvis-helpers.");
  }
  const names = guilds
    .slice(0, 8)
    .map((guild: any) => `${guild?.name ?? "unknown"} (${guild?.id ?? "unknown"})`)
    .join(", ");
  throw new Error(
    `The Discord bot is in multiple guilds; set DISCORD_PING_GUILD_ID in .env or pass guildId. Available guilds include: ${names}`,
  );
}

async function resolveHelpersChannel(
  params: any,
  cwd: string,
  dotenv: Record<string, string>,
  token: string,
  guildId: string,
  signal?: AbortSignal,
): Promise<ChannelInfo> {
  const directChannelId = normalizeSnowflake(envValue("DISCORD_PING_HELPERS_CHANNEL_ID", cwd, dotenv));
  const channelName = stripDiscordDecorators(
    params.channelName ||
      envValue("DISCORD_PING_HELPERS_CHANNEL_NAME", cwd, dotenv) ||
      envValue("DISCORD_WORKOUT_TRACKER_HELPERS_CHANNEL_NAME", cwd, dotenv) ||
      DEFAULT_HELPERS_CHANNEL_NAME,
  );
  if (directChannelId) return { id: directChannelId, name: channelName };

  const payload = await discordApiRequestWithRetry({ token, method: "GET", path: `/guilds/${guildId}/channels`, signal });
  const channels = Array.isArray(payload) ? payload : [];
  const target = channelName.toLowerCase();
  const matches = channels.filter((channel: any) => String(channel?.name ?? "").toLowerCase() === target);
  const preferred =
    matches.find((channel: any) => Number(channel?.type) === CHANNEL_TYPE_GUILD_TEXT) ??
    matches.find((channel: any) => Number(channel?.type) === CHANNEL_TYPE_GUILD_ANNOUNCEMENT) ??
    matches[0];
  if (!preferred?.id) {
    throw new Error(`Could not find Discord text channel #${channelName} in guild ${guildId}.`);
  }
  return {
    id: String(preferred.id),
    name: String(preferred.name ?? channelName),
    type: typeof preferred.type === "number" ? preferred.type : Number(preferred.type),
  };
}

function findMatchingThread(threads: any[], parentChannelId: string, threadName: string): Record<string, any> | undefined {
  const target = threadName.toLowerCase();
  return threads.find(
    (thread: any) => String(thread?.parent_id ?? "") === parentChannelId && String(thread?.name ?? "").toLowerCase() === target,
  );
}

function isArchivedThread(thread: Record<string, any>): boolean {
  return Boolean(thread?.thread_metadata?.archived ?? thread?.archived);
}

async function unarchiveThreadIfNeeded(
  token: string,
  thread: Record<string, any>,
  autoArchiveMinutes: number,
  signal?: AbortSignal,
): Promise<{ thread: Record<string, any>; unarchived: boolean }> {
  if (!isArchivedThread(thread)) return { thread, unarchived: false };
  const updated = await discordApiRequestWithRetry({
    token,
    method: "PATCH",
    path: `/channels/${thread.id}`,
    body: { archived: false, auto_archive_duration: autoArchiveMinutes },
    signal,
  });
  return { thread: updated && updated.id ? updated : { ...thread, archived: false }, unarchived: true };
}

async function findExistingThread(
  token: string,
  guildId: string,
  parentChannelId: string,
  threadName: string,
  signal?: AbortSignal,
): Promise<Record<string, any> | undefined> {
  const activePayload = await discordApiRequestWithRetry({ token, method: "GET", path: `/guilds/${guildId}/threads/active`, signal });
  const activeThreads = Array.isArray(activePayload?.threads) ? activePayload.threads : [];
  const active = findMatchingThread(activeThreads, parentChannelId, threadName);
  if (active) return active;

  for (const archiveType of ["public", "private"] as const) {
    try {
      const archivedPayload = await discordApiRequestWithRetry({
        token,
        method: "GET",
        path: `/channels/${parentChannelId}/threads/archived/${archiveType}`,
        query: { limit: 100 },
        signal,
      });
      const archivedThreads = Array.isArray(archivedPayload?.threads) ? archivedPayload.threads : [];
      const archived = findMatchingThread(archivedThreads, parentChannelId, threadName);
      if (archived) return archived;
    } catch (error: any) {
      if (![403, 404].includes(Number(error?.statusCode))) throw error;
    }
  }

  return undefined;
}

async function resolvePingThread(
  params: any,
  cwd: string,
  dotenv: Record<string, string>,
  token: string,
  guildId: string,
  channel: ChannelInfo,
  autoArchiveMinutes: number,
  signal?: AbortSignal,
): Promise<ThreadResolution> {
  const threadName = String(params.threadName || envValue("DISCORD_PING_THREAD_NAME", cwd, dotenv) || DEFAULT_THREAD_NAME).trim() || DEFAULT_THREAD_NAME;
  const directThreadId = normalizeSnowflake(envValue("DISCORD_PING_THREAD_ID", cwd, dotenv));
  if (directThreadId) {
    const directThread = await discordApiRequestWithRetry({ token, method: "GET", path: `/channels/${directThreadId}`, signal });
    const active = await unarchiveThreadIfNeeded(
      token,
      directThread?.id ? directThread : { id: directThreadId, name: threadName, parent_id: channel.id },
      autoArchiveMinutes,
      signal,
    );
    return { thread: active.thread, created: false, unarchived: active.unarchived };
  }

  const existing = await findExistingThread(token, guildId, channel.id, threadName, signal);
  if (existing) {
    const active = await unarchiveThreadIfNeeded(token, existing, autoArchiveMinutes, signal);
    return { thread: active.thread, created: false, unarchived: active.unarchived };
  }

  const threadType = channel.type === CHANNEL_TYPE_GUILD_ANNOUNCEMENT ? CHANNEL_TYPE_ANNOUNCEMENT_THREAD : CHANNEL_TYPE_PUBLIC_THREAD;
  const created = await discordApiRequestWithRetry({
    token,
    method: "POST",
    path: `/channels/${channel.id}/threads`,
    body: {
      name: threadName,
      auto_archive_duration: autoArchiveMinutes,
      type: threadType,
    },
    signal,
  });
  if (!created?.id) {
    throw new Error(`Discord did not return a thread id after creating ${threadName}.`);
  }
  return { thread: created, created: true, unarchived: false };
}

function memberNames(member: any): string[] {
  const user = member?.user && typeof member.user === "object" ? member.user : {};
  const username = typeof user.username === "string" ? user.username.trim() : "";
  const discriminator = typeof user.discriminator === "string" ? user.discriminator.trim() : "";
  return [
    typeof member?.nick === "string" ? member.nick : "",
    typeof user.global_name === "string" ? user.global_name : "",
    username,
    username ? `@${username}` : "",
    username && discriminator && discriminator !== "0" ? `${username}#${discriminator}` : "",
  ]
    .map((name) => name.trim())
    .filter(Boolean);
}

function pickMemberId(members: any[], query: string): string {
  const cleanedNeedle = stripDiscordDecorators(query).toLowerCase();
  const rawNeedle = query.trim().toLowerCase();
  let fallback = "";
  for (const member of members) {
    const userId = normalizeSnowflake(String(member?.user?.id ?? ""));
    if (!userId) continue;
    const names = memberNames(member).map((name) => name.toLowerCase());
    if (names.some((name) => name === cleanedNeedle || name === rawNeedle || `@${name}` === rawNeedle)) {
      return userId;
    }
    if (!fallback && names.some((name) => name.includes(cleanedNeedle) || cleanedNeedle.includes(name))) {
      fallback = userId;
    }
  }
  return fallback;
}

async function searchMemberId(token: string, guildId: string, query: string, signal?: AbortSignal): Promise<string> {
  const cleaned = stripDiscordDecorators(query);
  if (!cleaned) return "";
  const payload = await discordApiRequestWithRetry({
    token,
    method: "GET",
    path: `/guilds/${guildId}/members/search`,
    query: { query: cleaned, limit: 25 },
    signal,
  });
  return pickMemberId(Array.isArray(payload) ? payload : [], cleaned);
}

async function resolvePingUserId(
  params: any,
  cwd: string,
  dotenv: Record<string, string>,
  token: string,
  guildId: string,
  signal?: AbortSignal,
): Promise<string> {
  const configured =
    normalizeSnowflake(params.userId) ||
    normalizeSnowflake(envValue("DISCORD_PING_USER_ID", cwd, dotenv)) ||
    firstSnowflake(envValue("DISCORD_AUTO_THREAD_MEMBER_IDS", cwd, dotenv));
  if (configured) return configured;

  const queries = unique([
    stripDiscordDecorators(params.userQuery || ""),
    stripDiscordDecorators(envValue("DISCORD_PING_USER_QUERY", cwd, dotenv)),
    DEFAULT_USER_QUERY,
    stripDiscordDecorators(envValue("DISCORD_AUTO_THREAD_MEMBER_QUERY", cwd, dotenv)),
    "dyl pickle",
  ]);

  for (const query of queries) {
    try {
      const userId = await searchMemberId(token, guildId, query, signal);
      if (userId) return userId;
    } catch (error: any) {
      if (![403, 404].includes(Number(error?.statusCode))) throw error;
    }
  }

  throw new Error(
    `Could not resolve @${DEFAULT_USER_QUERY} in guild ${guildId}. Set DISCORD_PING_USER_ID in .env to the configured user's Discord user ID.`,
  );
}

async function addUserToThreadIfPossible(token: string, threadId: string, userId: string, signal?: AbortSignal): Promise<void> {
  try {
    await discordApiRequestWithRetry({
      token,
      method: "PUT",
      path: `/channels/${threadId}/thread-members/${userId}`,
      signal,
      expectJson: false,
    });
  } catch (error: any) {
    if (![403, 404, 405].includes(Number(error?.statusCode))) throw error;
  }
}

function buildPingContent(userId: string, message: string): string {
  const cleanMessage = message.trim() || "Task complete.";
  const prefix = `<@${userId}> `;
  return `${prefix}${truncateForDiscord(cleanMessage, MAX_DISCORD_MESSAGE_CHARS - prefix.length)}`;
}

async function sendCompletionPing(params: any, cwd: string, signal?: AbortSignal): Promise<PingResult> {
  const dotenv = envValues(cwd);
  const token = envValue("DISCORD_BOT_TOKEN", cwd, dotenv);
  if (!token) {
    throw new Error("DISCORD_BOT_TOKEN is not available, so discord_ping cannot post to Discord.");
  }

  const message = String(params.message ?? "").trim();
  if (!message) throw new Error("discord_ping requires a non-empty completion message.");

  const guildId = await resolveGuildId(params, cwd, dotenv, token, signal);
  const helpersChannel = await resolveHelpersChannel(params, cwd, dotenv, token, guildId, signal);
  const autoArchiveMinutes = coerceAutoArchiveMinutes(params.autoArchiveMinutes, cwd, dotenv);
  const threadResolution = await resolvePingThread(params, cwd, dotenv, token, guildId, helpersChannel, autoArchiveMinutes, signal);
  const threadId = String(threadResolution.thread.id);
  const threadName = String(threadResolution.thread.name || params.threadName || envValue("DISCORD_PING_THREAD_NAME", cwd, dotenv) || DEFAULT_THREAD_NAME);
  const userId = await resolvePingUserId(params, cwd, dotenv, token, guildId, signal);

  await addUserToThreadIfPossible(token, threadId, userId, signal);

  const attachments = resolvePingAttachments(params, cwd, dotenv);
  const content = buildPingContent(userId, message);
  const discordMessage = await postDiscordMessageWithAttachmentsAndRetry({
    token,
    channelId: threadId,
    content,
    userId,
    attachments,
    signal,
  });
  const discordMessageId = discordMessage?.id ? String(discordMessage.id) : undefined;
  const messageLink = discordMessageId ? `https://discord.com/channels/${guildId}/${threadId}/${discordMessageId}` : undefined;
  const sentAttachments = attachments.map((attachment, index) => ({
    ...attachment,
    url: Array.isArray(discordMessage?.attachments) && discordMessage.attachments[index]?.url ? String(discordMessage.attachments[index].url) : undefined,
  }));
  const attachmentSummary = sentAttachments.length
    ? ` with ${sentAttachments.length} attachment${sentAttachments.length === 1 ? "" : "s"}`
    : "";
  const summary = `Pinged <@${userId}> in #${helpersChannel.name ?? DEFAULT_HELPERS_CHANNEL_NAME} → ${threadName}${attachmentSummary}${messageLink ? ` (${messageLink})` : ""}.`;

  return {
    ok: true,
    summary,
    guildId,
    helpersChannelId: helpersChannel.id,
    helpersChannelName: helpersChannel.name ?? DEFAULT_HELPERS_CHANNEL_NAME,
    threadId,
    threadName,
    userId,
    discordMessageId,
    messageLink,
    attachments: sentAttachments,
    createdThread: threadResolution.created,
    unarchivedThread: threadResolution.unarchived,
  };
}

export default function registerDiscordPing(pi: ExtensionAPI) {
  pi.registerTool({
    name: "discord_ping",
    label: "Discord Ping",
    description:
      "Send an immediate one-off Discord ping/notification to the configured user in #jarvis-helpers → pings, optionally with local file attachments. Use for explicit user-facing pings or file delivery; not for scheduled jobs.",
    parameters: Type.Object({
      message: Type.String({ description: "Concise completion/result message to send after the user-requested goal is achieved." }),
      guildId: Type.Optional(Type.String({ description: "Optional Discord guild/server id override. Normally omit." })),
      channelName: Type.Optional(Type.String({ description: "Optional helpers text channel name override. Defaults to jarvis-helpers." })),
      threadName: Type.Optional(Type.String({ description: "Optional thread name override. Defaults to pings." })),
      userId: Type.Optional(Type.String({ description: "Optional Discord user id override. Normally omit; defaults to the configured user." })),
      userQuery: Type.Optional(Type.String({ description: "Optional member search query when DISCORD_PING_USER_ID is not set. Defaults to the configured user search query." })),
      autoArchiveMinutes: Type.Optional(Type.Number({ description: "Optional thread auto-archive duration in minutes. Defaults to 1440." })),
      attachmentPath: Type.Optional(Type.String({ description: "Optional local file path to attach to the ping." })),
      attachmentPaths: Type.Optional(Type.Array(Type.String({ description: "Local file path to attach to the ping." }), { description: "Optional local file paths to attach to the ping. Maximum 10 files." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const result = await sendCompletionPing(params, ctx.cwd, signal);
      return {
        content: [{ type: "text" as const, text: result.summary }],
        details: result,
      };
    },
    renderCall(args, theme) {
      const preview = typeof args.message === "string" ? args.message.slice(0, 80) : "";
      return new Text(`${theme.fg("toolTitle", "discord_ping")} ${theme.fg("accent", preview)}`, 0, 0);
    },
    renderResult(result, _options, theme) {
      const text = String(result.details?.summary ?? "Discord ping sent.");
      return new Text(theme.fg("success", text), 0, 0);
    },
  });

  pi.registerCommand("discord-ping", {
    description: "Send a manual one-off ping to the configured user in #jarvis-helpers → pings. Usage: /discord-ping <message>",
    handler: async (args, ctx) => {
      const message = args.trim() || "Test ping from JARVIS.";
      try {
        const result = await sendCompletionPing({ message }, ctx.cwd);
        ctx.ui.notify(result.summary, "info");
      } catch (error: any) {
        ctx.ui.notify(`discord_ping failed: ${error?.message ?? String(error)}`, "error");
      }
    },
  });
}
